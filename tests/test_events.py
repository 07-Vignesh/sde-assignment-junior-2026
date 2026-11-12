import json

import pytest

from pipeline.db import connect
from pipeline.events import ingest_event_drop
from pipeline.normalize import parse_ts
from pipeline.security import PiiProtector


def ev(event_id, etype="call.initiated", phone="9876543210", call_id="c1",
       ts="2026-10-05T13:20:21Z", payload=None, workflow="motor_renewal"):
    d = {"event_id": event_id, "event_type": etype, "workflow_id": workflow,
         "call_id": call_id, "occurred_at": ts, "payload": payload or {}}
    if phone is not None:
        d["phone"] = phone
    return json.dumps(d)


def write_events(drop, name, lines):
    folder = drop / "events"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def env():
    return connect(":memory:"), PiiProtector(b"test-key")


def test_parse_ts():
    assert parse_ts("2026-10-05T13:20:21Z") == "2026-10-05T13:20:21.000000Z"
    assert parse_ts("2026-10-05T18:50:21+05:30") == "2026-10-05T13:20:21.000000Z"
    assert parse_ts("2026-10-03 10:01:00") == "2026-10-03T04:31:00.000000Z"  # naive = IST
    assert parse_ts("garbage") is None
    assert parse_ts(None) is None


def test_malformed_and_duplicates(env, tmp_path):
    conn, prot = env
    drop = tmp_path / "drop_1"
    write_events(drop, "events_0001.jsonl", [
        ev("e1"),
        "not json",
        json.dumps({"no_id": 1}),
        ev("e1"),                 # duplicate inside the same file
        ev("e2", etype="call.connected"),
        "",                       # empty: not counted
        "   ",                    # whitespace: not counted
        "[1, 2]",                 # valid JSON but not an event
    ])
    res = ingest_event_drop(conn, prot, drop)[0]
    assert res["events_total"] == 6
    assert res["malformed_events"] == 3
    assert res["duplicate_events"] == 1
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


def test_phone_hashed_and_override_has_none(env, tmp_path):
    conn, prot = env
    drop = tmp_path / "drop_1"
    write_events(drop, "events_0001.jsonl", [
        ev("e1", phone="91-98765-43210"),
        ev("e2", etype="disposition.override", phone=None,
           payload={"disposition_code": "renewed"}),
    ])
    ingest_event_drop(conn, prot, drop)
    rows = {r["event_id"]: r for r in conn.execute("SELECT * FROM events")}
    assert rows["e1"]["phone_hash"] == prot.phone_hash("+919876543210")
    assert rows["e2"]["phone_hash"] is None
    dump = str([tuple(r) for r in conn.execute("SELECT * FROM events")])
    assert "9876543210" not in dump and "98765-43210" not in dump


def test_invalid_phone_stored_without_hash(env, tmp_path):
    conn, prot = env
    drop = tmp_path / "drop_1"
    write_events(drop, "events_0001.jsonl", [ev("e1", phone="12345")])
    ingest_event_drop(conn, prot, drop)
    row = conn.execute("SELECT * FROM events").fetchone()
    assert row["phone_hash"] is None


def test_duplicate_across_drops(env, tmp_path):
    conn, prot = env
    d1, d2 = tmp_path / "drop_1", tmp_path / "drop_2"
    write_events(d1, "events_0001.jsonl", [ev("e1")])
    write_events(d2, "events_1001.jsonl", [ev("e1"), ev("e2")])
    ingest_event_drop(conn, prot, d1)
    res = ingest_event_drop(conn, prot, d2)[0]
    assert res["duplicate_events"] == 1
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


def test_reingest_is_noop(env, tmp_path):
    conn, prot = env
    drop = tmp_path / "drop_1"
    write_events(drop, "events_0001.jsonl", [ev("e1")])
    ingest_event_drop(conn, prot, drop)
    again = ingest_event_drop(conn, prot, drop)
    assert again[0]["skipped"] is True
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1