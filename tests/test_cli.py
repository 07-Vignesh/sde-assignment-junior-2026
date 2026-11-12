import csv
import json

from pipeline.cli import main


def make_drop(root):
    (root / "leads" / "motor_renewal").mkdir(parents=True)
    (root / "events").mkdir()
    with open(root / "leads" / "motor_renewal" / "batch_001.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_name", "phone", "policy_number"])
        w.writerow(["Asha", "9876543210", "P1"])
    ev = {"event_id": "e1", "event_type": "call.initiated", "workflow_id": "motor_renewal",
          "call_id": "c1", "occurred_at": "2026-10-05T13:20:21Z", "phone": "9876543210",
          "payload": {}}
    (root / "events" / "events_0001.jsonl").write_text(json.dumps(ev) + "\n")


def test_ingest_twice_then_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PIPELINE_PII_KEY", "test-key")
    drop, db, out = tmp_path / "drop_1", str(tmp_path / "t.db"), tmp_path / "reports"
    make_drop(drop)

    assert main(["--db", db, "ingest", str(drop)]) == 0
    capsys.readouterr()
    assert main(["--db", db, "ingest", str(drop)]) == 0
    assert "skipped" in capsys.readouterr().out      # second run changes nothing

    assert main(["--db", db, "report", "--out", str(out)]) == 0
    for name in ["batch_summary.csv", "daily_overview.csv", "lead_report.csv",
                 "rejections.csv", "data_quality.json"]:
        assert (out / name).exists()
    rows = list(csv.DictReader(open(out / "lead_report.csv", newline="")))
    assert rows[0]["total_calls"] == "1" and rows[0]["phone_masked"] == "+91******3210"


def test_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_PII_KEY", "test-key")
    assert main(["--db", str(tmp_path / "t.db"), "ingest", str(tmp_path / "nope")]) == 2