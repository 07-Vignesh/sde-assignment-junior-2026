import sqlite3

import pytest

from pipeline.db import connect
from pipeline.security import PiiProtector


def test_hash_deterministic_and_keyed():
    a = PiiProtector(b"key-one")
    b = PiiProtector(b"key-two")
    assert a.phone_hash("+919876543210") == a.phone_hash("+919876543210")
    assert a.phone_hash("+919876543210") != b.phone_hash("+919876543210")


def test_hash_hides_number():
    h = PiiProtector(b"k").phone_hash("+919876543210")
    assert "9876543210" not in h
    assert len(h) == 64


def test_encrypt_roundtrip():
    p = PiiProtector(b"k")
    token = p.encrypt_json({"customer_name": "Aarav Menon"})
    assert "Aarav" not in token
    assert p.decrypt_json(token) == {"customer_name": "Aarav Menon"}


def _db_with_event():
    conn = connect(":memory:")
    conn.execute("INSERT INTO ingested_files (drop_name, rel_path, kind, sha256) "
                 "VALUES ('d', 'p', 'events', 'x')")
    conn.execute("INSERT INTO events (event_id, event_type, payload_json, file_id) "
                 "VALUES ('e1', 'call.initiated', '{}', 1)")
    return conn


def test_tables_exist():
    conn = connect(":memory:")
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"ingested_files", "leads", "lead_rejections", "events"} <= names


def test_events_update_blocked():
    conn = _db_with_event()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE events SET call_id = 'x' WHERE event_id = 'e1'")


def test_events_delete_blocked():
    conn = _db_with_event()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM events WHERE event_id = 'e1'")


def test_duplicate_event_id_rejected():
    conn = _db_with_event()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO events (event_id, event_type, payload_json, file_id) "
                     "VALUES ('e1', 'call.initiated', '{}', 1)")


def test_lead_identity_unique():
    conn = connect(":memory:")
    sql = ("INSERT INTO leads (workflow_id, batch_id, phone_hash, phone_last4, "
           "external_ref, fields_json, pii_enc) VALUES ('w', 'b', 'h', '1234', 'r', '{}', 'e')")
    conn.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)