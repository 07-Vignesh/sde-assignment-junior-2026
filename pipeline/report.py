import csv
import json
from collections import defaultdict
from pathlib import Path

from .derive import build_call, ist_date, summarize_lead

BUCKETS = ["yet_to_reach_out", "in_progress_telephony_failed",
           "in_progress_dialed", "completed"]

EVENT_SQL = ("SELECT event_id, event_type, workflow_id, call_id, occurred_at_utc, "
             "phone_hash, payload_json FROM events ORDER BY seq")


def _load_leads(conn):
    leads, by_identity = {}, {}
    for r in conn.execute("SELECT id, workflow_id, batch_id, phone_hash, phone_last4, "
                          "external_ref FROM leads"):
        leads[r["id"]] = dict(r)
        by_identity[(r["workflow_id"], r["phone_hash"])] = r["id"]
    return leads, by_identity


def _link_events(conn, leads, by_identity, dispositions):
    """Returns (events grouped by (lead_id, call_id), orphan_count, unknown_count)."""
    linked, pending, call_lead = [], [], {}
    orphans = unknown = 0

    # Pass 1: events that carry a phone link by (workflow_id, phone_hash)
    for r in conn.execute(EVENT_SQL):
        if r["phone_hash"] is None:
            pending.append(r)
            continue
        lid = by_identity.get((r["workflow_id"], r["phone_hash"]))
        if lid is None:
            orphans += 1
            continue
        linked.append((r, lid))
        if r["call_id"]:
            call_lead.setdefault(r["call_id"], lid)

    # Pass 2: overrides have no phone. They link through their call_id.
    for r in pending:
        lid = None
        if r["event_type"] == "disposition.override" and r["call_id"]:
            lid = call_lead.get(r["call_id"])
            if (lid is not None and r["workflow_id"]
                    and leads[lid]["workflow_id"] != r["workflow_id"]):
                lid = None
        if lid is None:
            orphans += 1
        else:
            linked.append((r, lid))

    # Unknown dispositions are checked only on events that linked (orphan wins)
    by_call = defaultdict(list)
    for r, lid in linked:
        code = None
        if r["event_type"].startswith("disposition."):
            code = json.loads(r["payload_json"]).get("disposition_code")
            if not isinstance(code, str):
                code = None
            if (leads[lid]["workflow_id"], code) not in dispositions:
                unknown += 1
        if r["call_id"]:
            by_call[(lid, r["call_id"])].append({
                "event_id": r["event_id"], "event_type": r["event_type"],
                "occurred_at_utc": r["occurred_at_utc"], "code": code})
    return by_call, orphans, unknown


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def build_reports(conn, dispositions, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    known, terminal, success = defaultdict(set), defaultdict(set), defaultdict(set)
    for (wf, code), flags in dispositions.items():
        known[wf].add(code)
        if flags["is_terminal"]:
            terminal[wf].add(code)
        if flags["is_success"]:
            success[wf].add(code)

    leads, by_identity = _load_leads(conn)
    by_call, orphans, unknown = _link_events(conn, leads, by_identity, dispositions)

    calls_by_lead = defaultdict(list)
    for (lid, call_id), evs in by_call.items():
        call = build_call(call_id, evs, known[leads[lid]["workflow_id"]])
        if call:
            calls_by_lead[lid].append(call)

    lead_rows = []
    batches = defaultdict(lambda: {"total": 0, **dict.fromkeys(BUCKETS, 0)})
    daily = defaultdict(lambda: [0, 0, set()])   # total, connected, success lead ids

    for lid, lead in leads.items():
        wf = lead["workflow_id"]
        calls = calls_by_lead.get(lid, [])
        s = summarize_lead(calls, terminal[wf], success[wf])
        lead_rows.append((wf, lead["external_ref"], lid, [
            wf, lead["external_ref"], lead["batch_id"],
            "+91******" + lead["phone_last4"], s["bucket"], s["total_calls"],
            s["connected_calls"], s["last_call_at"], s["current_disposition"],
            "true" if s["ever_success"] else "false"]))
        b = batches[(wf, lead["batch_id"])]
        b["total"] += 1
        b[s["bucket"]] += 1
        for c in calls:
            d = daily[(wf, ist_date(c["initiated_at"]))]
            d[0] += 1
            if c["connected"]:
                d[1] += 1
            if c["disposition"] in success[wf]:
                d[2].add(lid)

    # 1. batch_summary.csv
    _write_csv(out / "batch_summary.csv",
               ["workflow_id", "batch_id", "total_leads", *BUCKETS],
               [[wf, bid, b["total"], *[b[k] for k in BUCKETS]]
                for (wf, bid), b in sorted(batches.items())])

    # 2. daily_overview.csv
    _write_csv(out / "daily_overview.csv",
               ["workflow_id", "date", "total_calls", "connected_calls",
                "connectivity_rate", "success_leads"],
               [[wf, day, d[0], d[1], f"{d[1] / d[0]:.4f}", len(d[2])]
                for (wf, day), d in sorted(daily.items())])

    # 3. lead_report.csv
    _write_csv(out / "lead_report.csv",
               ["workflow_id", "external_ref", "batch_id", "phone_masked", "bucket",
                "total_calls", "connected_calls", "last_call_at",
                "current_disposition", "ever_success"],
               [row for _, _, _, row in sorted(lead_rows, key=lambda x: x[:3])])

    # 4. rejections.csv
    _write_csv(out / "rejections.csv",
               ["workflow_id", "batch_id", "row_number", "reason"],
               [list(r) for r in conn.execute(
                   "SELECT workflow_id, batch_id, row_number, reason FROM lead_rejections "
                   "ORDER BY workflow_id, batch_id, row_number")])

    # 5. data_quality.json
    sums = conn.execute(
        "SELECT COALESCE(SUM(rows_total),0), COALESCE(SUM(rows_rejected),0), "
        "COALESCE(SUM(duplicates_merged),0), COALESCE(SUM(field_warnings),0), "
        "COALESCE(SUM(events_total),0), COALESCE(SUM(malformed_events),0), "
        "COALESCE(SUM(duplicate_events),0) FROM ingested_files").fetchone()
    dq = {
        "lead_rows_total": sums[0],
        "lead_rows_rejected": sums[1],
        "rejections_by_reason": {r[0]: r[1] for r in conn.execute(
            "SELECT reason, COUNT(*) FROM lead_rejections GROUP BY reason ORDER BY reason")},
        "duplicate_lead_rows_merged": sums[2],
        "field_warnings": sums[3],
        "events_total": sums[4],
        "malformed_events": sums[5],
        "duplicate_events_dropped": sums[6],
        "orphan_events": orphans,
        "unknown_disposition_events": unknown,
    }
    (out / "data_quality.json").write_text(json.dumps(dq, indent=2) + "\n",
                                           encoding="utf-8")
    return dq