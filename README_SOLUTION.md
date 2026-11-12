# Assignment A: Interaction Ledger & Reporting Pipeline

## Requirements
- Python 3.11+
- `pip install pytest cryptography`

## Run

```bash
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data

python -m pipeline ingest data/drop_1
python -m pipeline ingest data/drop_2
python -m pipeline report --out reports/
```

Re-running `ingest` on a drop that was already ingested changes nothing.

## Options
- `--db PATH` (before the command) or the `PIPELINE_DB` variable: SQLite file. Default `pipeline.db`. Delete it to start from scratch.
- `PIPELINE_PII_KEY`: secret used to hash and encrypt PII. If unset, a key is created in `.pii_key` on first run. Keep the same key for the life of a database.

## Tests

```bash
python -m pytest -q
python check_idempotency.py
```

## Layout
- `pipeline/normalize.py`: header, phone, date, decimal, enum and timestamp rules
- `pipeline/schema_loader.py`: workflow schemas and disposition catalogue
- `pipeline/db.py`: SQLite schema, including the append-only `events` ledger
- `pipeline/security.py`: HMAC phone hash and Fernet field encryption
- `pipeline/leads.py`, `pipeline/events.py`: ingestion
- `pipeline/derive.py`: effective disposition, calls, buckets
- `pipeline/report.py`: linking, orphans and the five report files
- `pipeline/cli.py`: command line