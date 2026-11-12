import argparse
from pathlib import Path

from .db import DEFAULT_DB, connect
from .events import ingest_event_drop
from .leads import ingest_lead_drop
from .report import build_reports
from .schema_loader import load_dispositions, load_workflow_schemas
from .security import PiiProtector, load_master_key


def _describe(r):
    if r.get("skipped"):
        return f"  {r['file']}: already ingested, skipped"
    details = ", ".join(f"{k}={v}" for k, v in r.items() if k not in ("file", "skipped"))
    return f"  {r['file']}: {details}"


def cmd_ingest(args):
    drop = Path(args.drop_dir)
    if not drop.is_dir():
        print(f"error: {drop} is not a folder")
        return 2
    conn = connect(args.db)
    protector = PiiProtector(load_master_key())
    print(f"Ingesting {drop} into {args.db}")
    print("Leads:")
    for r in ingest_lead_drop(conn, protector, load_workflow_schemas(), drop):
        print(_describe(r))
    print("Events:")
    for r in ingest_event_drop(conn, protector, drop):
        print(_describe(r))
    return 0


def cmd_report(args):
    conn = connect(args.db)
    dq = build_reports(conn, load_dispositions(), args.out)
    print(f"Reports written to {args.out}")
    print(f"  orphan events: {dq['orphan_events']}, "
          f"unknown dispositions: {dq['unknown_disposition_events']}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite file (default: pipeline.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest one drop folder")
    p_ingest.add_argument("drop_dir")
    p_ingest.set_defaults(func=cmd_ingest)

    p_report = sub.add_parser("report", help="write the five report files")
    p_report.add_argument("--out", required=True)
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)