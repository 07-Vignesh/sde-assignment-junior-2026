"""Compares report output across ingest scenarios. Run from the project root."""
import filecmp
import os
import shutil
import tempfile
from pathlib import Path

from pipeline.db import connect
from pipeline.events import ingest_event_drop
from pipeline.leads import ingest_lead_drop
from pipeline.report import build_reports
from pipeline.schema_loader import load_dispositions, load_workflow_schemas
from pipeline.security import PiiProtector, load_master_key

DROPS = ["data/drop_1", "data/drop_2"]
FILES = ["batch_summary.csv", "daily_overview.csv", "lead_report.csv",
         "rejections.csv", "data_quality.json"]


def run(label, steps, tmp):
    """steps: list of (kind, drop). kind is 'leads' or 'events'."""
    conn = connect(str(tmp / f"{label}.db"))
    prot, schemas = PiiProtector(load_master_key()), load_workflow_schemas()
    for kind, drop in steps:
        if kind == "leads":
            ingest_lead_drop(conn, prot, schemas, drop)
        else:
            ingest_event_drop(conn, prot, drop)
    out = tmp / label
    build_reports(conn, load_dispositions(), out)
    conn.close()
    return out


def same(a, b):
    return all(filecmp.cmp(a / f, b / f, shallow=False) for f in FILES)


def main():
    tmp = Path(tempfile.mkdtemp())
    d1, d2 = DROPS
    normal = [("leads", d1), ("events", d1), ("leads", d2), ("events", d2)]

    a = run("A_rerun", normal + normal, tmp)
    # B: all events first (drop_2 leads still arrive last), leads in the same order
    b = run("B_events_first",
            [("events", d1), ("events", d2), ("leads", d1), ("leads", d2)], tmp)
    c = run("C_baseline", normal, tmp)

    print("A (re-ingest everything) == baseline:", same(a, c))
    print("B (events before leads)  == baseline:", same(b, c))

    # Compare against the reports you wrote with the CLI, if present
    if Path("reports").is_dir():
        print("CLI reports/             == baseline:", same(Path("reports"), c))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    main()