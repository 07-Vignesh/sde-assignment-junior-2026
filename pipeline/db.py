import os
import sqlite3

DEFAULT_DB = os.environ.get("PIPELINE_DB", "pipeline.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingested_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drop_name TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('leads', 'events')),
    workflow_id TEXT,
    batch_id TEXT,
    sha256 TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    rows_total INTEGER NOT NULL DEFAULT 0,
    rows_rejected INTEGER NOT NULL DEFAULT 0,
    duplicates_merged INTEGER NOT NULL DEFAULT 0,
    field_warnings INTEGER NOT NULL DEFAULT 0,
    events_total INTEGER NOT NULL DEFAULT 0,
    malformed_events INTEGER NOT NULL DEFAULT 0,
    duplicate_events INTEGER NOT NULL DEFAULT 0,
    UNIQUE (drop_name, rel_path)
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    phone_hash TEXT NOT NULL,
    phone_last4 TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    fields_json TEXT NOT NULL,   -- non-PII fields, merged, defaults not yet applied
    pii_enc TEXT NOT NULL,       -- encrypted JSON of PII fields (e.g. name)
    UNIQUE (workflow_id, phone_hash)
);

CREATE TABLE IF NOT EXISTS lead_rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES ingested_files(id),
    workflow_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    reason TEXT NOT NULL,
    UNIQUE (file_id, row_number)
);

CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,   -- arrival order
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    workflow_id TEXT,
    call_id TEXT,
    occurred_at_utc TEXT,
    phone_hash TEXT,             -- NULL for overrides or invalid phones
    payload_json TEXT NOT NULL,
    file_id INTEGER NOT NULL REFERENCES ingested_files(id)
);

CREATE INDEX IF NOT EXISTS idx_events_lead ON events (workflow_id, phone_hash);
CREATE INDEX IF NOT EXISTS idx_events_call ON events (workflow_id, call_id);

-- The ledger is append-only: block any change or removal.
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events ledger is append-only'); END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events ledger is append-only'); END;
"""


def connect(path=DEFAULT_DB):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn