# Submission

## Candidate
- **Name:** Vikneshwaran
- **Assignment chosen:** A (Data)
- **Time spent (honest estimate):** about 5h

## How to run
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (Mac/Linux: source .venv/bin/activate)
pip install pytest cryptography

python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data
python -m pipeline ingest data/drop_1
python -m pipeline ingest data/drop_2
python -m pipeline report --out reports/

python -m pytest -q
python check_idempotency.py
```
Delete `pipeline.db` to start from scratch. Options are in `README_SOLUTION.md`.

## Design
Python standard library plus `cryptography`, with SQLite storage. **Ingestion only stores facts. Linking, orphan detection and derived facts are computed at report time from the whole database.** This is what lets an event that arrives before its lead count correctly once the lead appears.

**Tables**
- `ingested_files`: one row per file, keyed by `(drop_name, rel_path)`, with sha256 and per-file counters. It is the idempotency record and the source of the counters in `data_quality.json`.
- `leads`: UNIQUE `(workflow_id, phone_hash)`. Holds batch_id, external_ref, last 4 digits, non-PII fields as JSON and encrypted PII as JSON.
- `lead_rejections`: file, workflow, batch, row number, reason. No PII.
- `events`: the append-only interaction ledger.

**Ledger**
- `event_id` is UNIQUE. SQLite triggers abort any UPDATE or DELETE on `events` (tested).
- Events store no `lead_id`. They join to leads through `(workflow_id, phone_hash)` at report time, so late leads need no backfill.
- An override is a new row. The original is never edited. The report decides which one wins.
- `occurred_at_utc` is a fixed-width UTC string, so string order equals time order. IST conversion happens only in reports.

**PII**
- Phone is never stored, not even encrypted. I store `HMAC-SHA256(key, canonical_phone)` plus the last 4 digits. A keyed hash is used because plain SHA-256 over about 4 billion Indian mobile numbers can be brute-forced.
- Customer name is encrypted with Fernet. Two sub-keys are derived from one master secret (`PIPELINE_PII_KEY`, or the git-ignored `.pii_key`).
- Event phones are hashed on ingest and the raw value is discarded. Reports and rejections contain no names or full phones (tested).

**Idempotency**
- Files already in `ingested_files` are skipped. Each drop is one transaction. Duplicate events are also blocked by the UNIQUE `event_id`.
- Reports are recomputed from the full database, so drop_1 then drop_2 equals everything at once.

## Decisions & assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| Enum compared only against the schema `values`; `Hindi`, `tamil`, `english` become null + 1 warning | Spec says compare against values. Mapping names to codes would invent a rule | Map language names to codes |
| Defaults not stored at ingest | Spec: defaults apply after merging to still-null fields. No report uses them | Apply `en` at insert time |
| Merge overwrites only non-null fields, including `external_ref`; `batch_id` never changes | Spec wording | Keep first `external_ref` |
| Orphan status decided at report time, not ingest | Events can arrive before their lead | Mark orphans at ingest and re-check later |
| Invalid or missing phone on a non-override event: NULL hash, counts as orphan | It can never link to a lead | Count as malformed |
| Phone-less override links through the `call_id` of an event that linked by phone; otherwise orphan | Spec: override links via its call | Link by `call_id` alone |
| Orphan check before unknown-disposition check | Spec order. An orphan is never also "unknown" | Count both |
| Any valid override beats any set, even a later-dated set | Spec: override wins; set is used only if no override | Latest event of either type wins |
| Unknown codes ignored when computing effective disposition | An unknown override should not hide a valid set | Treat as the effective code |
| Timestamp ties broken by `event_id` | Spec is silent. Gives deterministic output | Arrival order |
| Several `call.initiated` on one call: earliest defines time and date | Spec is silent | Latest |
| Unparseable timestamp stored as NULL; a call with no valid initiated time is not counted | Cannot place it in IST or order it | Reject the event as malformed |
| Malformed = invalid JSON, non-object JSON, or missing/empty/non-string `event_id` | Spec says "no event_id" | Count only invalid JSON |
| Empty event lines not counted in `events_total` | Spec: "non-empty line" | Count them |
| Events without `call_id` cannot join a call | Calls are grouped by call_id | Group by phone |
| `batch_summary.csv` lists only batches with at least one lead | A fully rejected batch has no leads to count | Emit all-zero rows |
| Files identified by drop name and path, not content | Simple and predictable | Identify by sha256 |

## Failure modes considered
- **Bad input**: blank rows, missing fields, invalid phones, impossible dates and non-numeric amounts are handled per spec. Malformed JSON lines are counted, not fatal.
- **Re-runs**: skipped by file record. Duplicate events blocked by UNIQUE `event_id`.
- **Crash mid-drop**: each drop is one transaction, so nothing half-done is committed.
- **Late-arriving leads**: handled by report-time linking.
- **Not handled**:
  - A file replaced under the same name is skipped, not re-ingested. The sha256 is stored but not compared.
  - If the PII key changes, old hashes stop matching new data.
  - Event payloads are stored as received. `overridden_by` identifies a supervisor, and I did not review it as PII.
  - A lead file with a header that matches no schema fields rejects every row, with no warning.

## Testing
- **Tested**: 50 tests covering tests covering phone formats, dates (day-first, impossible), decimals, headers, enums, timestamps across the IST date boundary, effective disposition, bucket logic, rejection and warning counts, merge order, event dedupe across drops, append-only triggers, orphans resolving when a lead arrives, report content, PII absence and the CLI.
- `check_idempotency.py` compares report files byte for byte for: (A) re-ingesting everything, (B) events ingested before leads, (C) baseline. Result: Result: A (re-ingest everything) == baseline: True; B (events before leads) == baseline: True; CLI reports/ == baseline: True.
- **Not tested**: the large data set, concurrent runs, and a crash in the middle of a drop.

## Results
- Small data set (seed 42): 2057 lead rows, 108 rejected, 57 duplicates merged, 1892 leads, 8745 event lines (8 malformed, 237 duplicates), 462 orphans, 18 unknown dispositions.
- Report totals agree: 1892 leads in both `lead_report` and `batch_summary`, 2536 calls in both `lead_report` and `daily_overview`.
- Performance: not attempted (large data set not run).
- Seed 7 (small): ran cleanly with a fresh database. 1886 leads, 2544 calls, report totals consistent across files, re-ingest skipped every file.
## If I had another day
1. Compare sha256 to detect changed files.
2. Run on a second seed and on the large set, then move aggregation into SQL.
3. Incremental per-lead summaries, so a drop only touches the affected leads.
4. Review event payloads for PII and a key rotation plan.
5. Production: PostgreSQL, a scheduled job per drop, raw files in object storage so backfills are safe re-runs, and alerts on rising orphan or rejection rates.