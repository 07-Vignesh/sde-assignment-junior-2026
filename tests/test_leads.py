import csv
import json

import pytest

from pipeline.db import connect
from pipeline.leads import ingest_lead_drop
from pipeline.schema_loader import load_workflow_schemas
from pipeline.security import PiiProtector

# Deliberately renamed headers, plus an extra junk column
HEADER = ["Name", "Mobile No", "Policy", "Expiry Date", "Premium", "Language", "Junk"]


def write_batch(drop, name, rows, workflow="motor_renewal"):
    folder = drop / "leads" / workflow
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)


@pytest.fixture
def env():
    return connect(":memory:"), PiiProtector(b"test-key"), load_workflow_schemas()


def test_rejections_and_warnings(env, tmp_path):
    conn, prot, schemas = env
    drop = tmp_path / "drop_1"
    write_batch(drop, "batch_001", [
        ["", "", "", "", "", "", ""],                                      # blank: skipped
        ["Asha", "98765 43210", "P1", "31/02/2026", "abc", "Hindi", "x"],  # kept, 3 warnings
        ["", "9876543211", "P2", "", "", "", ""],                          # row 2: no name
        ["Ben", "12345", "P3", "", "", "", ""],                            # row 3: bad phone
        ["Cy", "9876543212", "", "", "", "", ""],                          # row 4: no policy
        ["Dee", "123", "P4", "bad date", "", "", ""],                      # row 5: bad phone
    ])
    res = ingest_lead_drop(conn, prot, schemas, drop)[0]
    assert res["rows_total"] == 5
    assert res["rows_rejected"] == 4
    assert res["field_warnings"] == 3      # Dee's date warning must NOT count
    reasons = [(r["row_number"], r["reason"]) for r in conn.execute(
        "SELECT row_number, reason FROM lead_rejections ORDER BY row_number")]
    assert reasons == [(2, "missing_required:customer_name"), (3, "invalid_phone"),
                       (4, "missing_required:policy_number"), (5, "invalid_phone")]
    lead = conn.execute("SELECT * FROM leads").fetchone()
    fields = json.loads(lead["fields_json"])
    assert fields["policy_expiry"] is None
    assert fields["preferred_language"] is None    # default NOT applied at ingest
    assert lead["phone_last4"] == "3210"


def test_merge_last_write_wins(env, tmp_path):
    conn, prot, schemas = env
    drop = tmp_path / "drop_1"
    write_batch(drop, "batch_001",
                [["Asha", "9876543210", "P1", "2026-10-01", "1000", "ta", ""]])
    write_batch(drop, "batch_002",
                [["Asha K", "+91 98765 43210", "P1-NEW", "", "2000", "", ""]])
    results = ingest_lead_drop(conn, prot, schemas, drop)
    assert sum(r["duplicates_merged"] for r in results) == 1
    lead = conn.execute("SELECT * FROM leads").fetchone()
    assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1
    assert lead["batch_id"] == "batch_001"          # first batch kept forever
    assert lead["external_ref"] == "P1-NEW"
    fields = json.loads(lead["fields_json"])
    assert fields["premium_amount"] == "2000.00"    # overwritten
    assert fields["policy_expiry"] == "2026-10-01"  # empty value did not erase it
    assert fields["preferred_language"] == "ta"
    assert prot.decrypt_json(lead["pii_enc"])["customer_name"] == "Asha K"


def test_reingest_is_noop(env, tmp_path):
    conn, prot, schemas = env
    drop = tmp_path / "drop_1"
    write_batch(drop, "batch_001",
                [["Asha", "9876543210", "P1", "", "", "", ""]])
    ingest_lead_drop(conn, prot, schemas, drop)
    again = ingest_lead_drop(conn, prot, schemas, drop)
    assert again[0]["skipped"] is True
    assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM ingested_files").fetchone()[0] == 1


def test_no_plaintext_pii(env, tmp_path):
    conn, prot, schemas = env
    drop = tmp_path / "drop_1"
    write_batch(drop, "batch_001",
                [["Asha Menon", "9876543210", "P1", "", "", "", ""]])
    ingest_lead_drop(conn, prot, schemas, drop)
    dump = str([tuple(r) for r in conn.execute("SELECT * FROM leads")])
    assert "Asha" not in dump
    assert "9876543210" not in dump