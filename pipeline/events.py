import hashlib
import json
from pathlib import Path

from .normalize import norm_phone, parse_ts


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ingest_event_file(conn, protector, drop_name, path):
    """Ingest one .jsonl file into the ledger. Returns a counters dict."""
    path = Path(path)
    rel_path = f"events/{path.name}"

    if conn.execute("SELECT 1 FROM ingested_files WHERE drop_name = ? AND rel_path = ?",
                    (drop_name, rel_path)).fetchone():
        return {"file": rel_path, "skipped": True}

    file_id = conn.execute(
        "INSERT INTO ingested_files (drop_name, rel_path, kind, sha256) "
        "VALUES (?, ?, 'events', ?)",
        (drop_name, rel_path, _sha256(path))).lastrowid

    total = malformed = duplicates = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue                      # empty lines are not counted
            total += 1

            # 1. Malformed: not valid JSON, not an object, or no event_id
            try:
                ev = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            event_id = ev.get("event_id") if isinstance(ev, dict) else None
            if not isinstance(event_id, str) or not event_id.strip():
                malformed += 1
                continue

            # 2. Duplicate: event_id already in the ledger (any drop, or earlier in this file)
            if conn.execute("SELECT 1 FROM events WHERE event_id = ?",
                            (event_id,)).fetchone():
                duplicates += 1
                continue

            # Store it. The phone is hashed and then thrown away; never stored as-is.
            raw_phone = ev.get("phone")
            canonical = None
            if raw_phone not in (None, ""):
                canonical = norm_phone(str(raw_phone))
            phone_hash = protector.phone_hash(canonical) if canonical else None

            payload = ev.get("payload")
            if not isinstance(payload, dict):
                payload = {}

            conn.execute(
                "INSERT INTO events (event_id, event_type, workflow_id, call_id, "
                "occurred_at_utc, phone_hash, payload_json, file_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, str(ev.get("event_type") or ""), ev.get("workflow_id"),
                 ev.get("call_id"), parse_ts(ev.get("occurred_at")), phone_hash,
                 json.dumps(payload, sort_keys=True), file_id))

    conn.execute(
        "UPDATE ingested_files SET events_total = ?, malformed_events = ?, "
        "duplicate_events = ? WHERE id = ?", (total, malformed, duplicates, file_id))
    return {"file": rel_path, "skipped": False, "events_total": total,
            "malformed_events": malformed, "duplicate_events": duplicates}


def ingest_event_drop(conn, protector, drop_dir):
    """Ingest every events_*.jsonl in a drop, in filename order, in one transaction."""
    drop_dir = Path(drop_dir)
    results = []
    with conn:
        for path in sorted((drop_dir / "events").glob("*.jsonl")):
            results.append(ingest_event_file(conn, protector, drop_dir.name, path))
    return results