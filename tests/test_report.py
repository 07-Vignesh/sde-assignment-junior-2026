import csv
import json

from pipeline.db import connect
from pipeline.events import ingest_event_drop
from pipeline.leads import ingest_lead_drop
from pipeline.report import build_reports
from pipeline.schema_loader import load_dispositions, load_workflow_schemas
from pipeline.security import PiiProtector


def ev(event_id, etype, call_id, ts, phone="9876543210", payload=None):
    d = {"event_id": event_id, "event_type": etype, "workflow_id": "motor_renewal",
         "call_id": call_id, "occurred_at": ts, "payload": payload or {}}
    if phone:
        d["phone"] = phone
    return json.dumps(d)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def setup(tmp_path):
    d1, d2 = tmp_path / "drop_1", tmp_path / "drop_2"
    (d1 / "events").mkdir(parents=True)
    (d2 / "leads" / "motor_renewal").mkdir(parents=True)
    lines = [
        ev("e1", "call.initiated", "c1", "2026-10-05T13:20:21Z"),
        ev("e2", "call.connected", "c1", "2026-10-05T13:21:00Z"),
        ev("e3", "disposition.set", "c1", "2026-10-05T13:25:00Z",
           payload={"disposition_code": "callback_requested"}),
        ev("e4", "disposition.override", "c1", "2026-10-05T14:00:00Z", phone=None,
           payload={"disposition_code": "renewed"}),
        ev("e5", "call.initiated", "c2", "2026-10-05T20:00:00Z"),
        ev("e6", "call.telephony_failed", "c2", "2026-10-05T20:00:05Z"),
        ev("e7", "call.initiated", "c9", "2026-10-05T10:00:00Z", phone="9000000000"),
        ev("e8", "disposition.set", "c1", "2026-10-05T13:30:00Z",
           payload={"disposition_code": "bogus"}),
        ev("e9", "disposition.override", "c99", "2026-10-05T10:00:00Z", phone=None,
           payload={"disposition_code": "renewed"}),
    ]
    (d1 / "events" / "events_0001.jsonl").write_text("\n".join(lines) + "\n")
    with open(d2 / "leads" / "motor_renewal" / "batch_001.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_name", "phone", "policy_number", "policy_expiry",
                    "premium_amount", "preferred_language"])
        w.writerow(["Asha", "9876543210", "P1", "", "", ""])
        w.writerow(["Ben", "9876543211", "P2", "", "", ""])
        w.writerow(["", "9876543212", "P3", "", "", ""])      # rejected
    return d1, d2


def test_orphans_resolve_when_lead_arrives(tmp_path):
    conn, prot = connect(":memory:"), PiiProtector(b"k")
    schemas, disp = load_workflow_schemas(), load_dispositions()
    d1, d2 = setup(tmp_path)

    ingest_event_drop(conn, prot, d1)                    # events first, no leads yet
    dq = build_reports(conn, disp, tmp_path / "r1")
    assert dq["orphan_events"] == 9 and dq["unknown_disposition_events"] == 0

    ingest_lead_drop(conn, prot, schemas, d2)            # now the lead arrives
    out = tmp_path / "r2"
    dq = build_reports(conn, disp, out)
    assert dq["orphan_events"] == 2                      # e7 and e9 only
    assert dq["unknown_disposition_events"] == 1         # e8
    assert dq["events_total"] == 9
    assert dq["lead_rows_total"] == 3 and dq["lead_rows_rejected"] == 1
    assert dq["rejections_by_reason"] == {"missing_required:customer_name": 1}

    leads = read_csv(out / "lead_report.csv")
    assert leads[0] == {
        "workflow_id": "motor_renewal", "external_ref": "P1", "batch_id": "batch_001",
        "phone_masked": "+91******3210", "bucket": "completed", "total_calls": "2",
        "connected_calls": "1", "last_call_at": "2026-10-06T01:30:00+05:30",
        "current_disposition": "renewed", "ever_success": "true"}
    assert leads[1]["bucket"] == "yet_to_reach_out"
    assert leads[1]["last_call_at"] == "" and leads[1]["ever_success"] == "false"

    daily = read_csv(out / "daily_overview.csv")
    assert [(r["date"], r["total_calls"], r["connected_calls"],
             r["connectivity_rate"], r["success_leads"]) for r in daily] == [
        ("2026-10-05", "1", "1", "1.0000", "1"),
        ("2026-10-06", "1", "0", "0.0000", "0")]

    batch = read_csv(out / "batch_summary.csv")
    assert batch == [{"workflow_id": "motor_renewal", "batch_id": "batch_001",
                      "total_leads": "2", "yet_to_reach_out": "1",
                      "in_progress_telephony_failed": "0", "in_progress_dialed": "0",
                      "completed": "1"}]

    rej = read_csv(out / "rejections.csv")
    assert rej == [{"workflow_id": "motor_renewal", "batch_id": "batch_001",
                    "row_number": "3", "reason": "missing_required:customer_name"}]


def test_report_is_repeatable_and_pii_free(tmp_path):
    conn, prot = connect(":memory:"), PiiProtector(b"k")
    d1, d2 = setup(tmp_path)
    ingest_event_drop(conn, prot, d1)
    ingest_lead_drop(conn, prot, load_workflow_schemas(), d2)
    disp = load_dispositions()
    build_reports(conn, disp, tmp_path / "a")
    build_reports(conn, disp, tmp_path / "b")
    names = ["batch_summary.csv", "daily_overview.csv", "lead_report.csv",
             "rejections.csv", "data_quality.json"]
    for n in names:
        a = (tmp_path / "a" / n).read_bytes()
        assert a == (tmp_path / "b" / n).read_bytes()
        assert b"Asha" not in a and b"9876543210" not in a