import csv
import hashlib
import json
from pathlib import Path

from .normalize import norm_header, norm_phone, norm_date, norm_decimal, norm_enum


def _clean(field, raw):
    """Validate one non-empty value. Returns the clean value, or None if invalid."""
    t = field["type"]
    if t == "string":
        return raw
    if t == "phone":
        return norm_phone(raw)
    if t == "date":
        return norm_date(raw)
    if t == "decimal":
        d = norm_decimal(raw)
        return None if d is None else str(d)   # stored as text, e.g. "27554.00"
    if t == "enum":
        return norm_enum(raw, [v.lower() for v in field["values"]])
    raise ValueError(f"unknown field type: {t}")


def build_col_map(schema, header):
    """Map schema field name -> column index. Unmatched columns are ignored."""
    col_map = {}
    for idx, h in enumerate(header):
        key = norm_header(h)
        for field in schema["fields"]:
            if key in field["_header_keys"] and field["name"] not in col_map:
                col_map[field["name"]] = idx
                break
    return col_map


def parse_row(schema, col_map, cells):
    """Walk fields in schema order.
    Returns (values, reject_reason, warnings). Only one of values/reject_reason is set."""
    values, warnings = {}, 0
    for field in schema["fields"]:
        name = field["name"]
        idx = col_map.get(name)
        raw = cells[idx].strip() if idx is not None and idx < len(cells) else ""
        if raw == "":
            if field.get("required"):
                return None, f"missing_required:{name}", 0
            values[name] = None
            continue
        value = _clean(field, raw)
        if value is None:
            if field["type"] == "phone":
                return None, "invalid_phone", 0
            values[name] = None      # optional field, present but invalid
            warnings += 1
        else:
            values[name] = value
    return values, None, warnings


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _upsert_lead(conn, protector, schema, workflow_id, batch_id, values):
    """Create the lead, or merge into it. Returns True if it was a duplicate."""
    phone_name = next(f["name"] for f in schema["fields"] if f["type"] == "phone")
    ref_name = next((f["name"] for f in schema["fields"] if f.get("reference")), None)
    pii_names = [f["name"] for f in schema["fields"]
                 if f.get("pii") and f["type"] != "phone"]
    plain_names = [f["name"] for f in schema["fields"]
                   if not f.get("pii") and f["type"] != "phone"]

    phone = values[phone_name]
    phone_hash = protector.phone_hash(phone)
    new_plain = {n: values[n] for n in plain_names}
    new_pii = {n: values[n] for n in pii_names}
    new_ref = values.get(ref_name) if ref_name else None

    row = conn.execute(
        "SELECT id, external_ref, fields_json, pii_enc FROM leads "
        "WHERE workflow_id = ? AND phone_hash = ?", (workflow_id, phone_hash)
    ).fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO leads (workflow_id, batch_id, phone_hash, phone_last4, "
            "external_ref, fields_json, pii_enc) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (workflow_id, batch_id, phone_hash, phone[-4:], new_ref or "",
             json.dumps(new_plain), protector.encrypt_json(new_pii)))
        return False

    # Duplicate: later non-null values overwrite, nulls never erase.
    old_plain = json.loads(row["fields_json"])
    old_pii = protector.decrypt_json(row["pii_enc"])
    merged_plain = {k: (v if v is not None else old_plain.get(k))
                    for k, v in new_plain.items()}
    merged_pii = {k: (v if v is not None else old_pii.get(k))
                  for k, v in new_pii.items()}
    conn.execute(
        "UPDATE leads SET external_ref = ?, fields_json = ?, pii_enc = ? WHERE id = ?",
        (new_ref or row["external_ref"], json.dumps(merged_plain),
         protector.encrypt_json(merged_pii), row["id"]))
    return True


def ingest_lead_file(conn, protector, schema, drop_name, workflow_id, path):
    """Ingest one CSV. Returns a counters dict, or {'skipped': True} if already done."""
    path = Path(path)
    batch_id = path.stem
    rel_path = f"leads/{workflow_id}/{path.name}"

    if conn.execute("SELECT 1 FROM ingested_files WHERE drop_name = ? AND rel_path = ?",
                    (drop_name, rel_path)).fetchone():
        return {"file": rel_path, "skipped": True}

    file_id = conn.execute(
        "INSERT INTO ingested_files (drop_name, rel_path, kind, workflow_id, batch_id, sha256) "
        "VALUES (?, ?, 'leads', ?, ?, ?)",
        (drop_name, rel_path, workflow_id, batch_id, _sha256(path))).lastrowid

    rows_total = rejected = merged = warnings = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        col_map = build_col_map(schema, header)
        for cells in reader:
            if all(c.strip() == "" for c in cells):
                continue                         # blank row: skipped, not counted
            rows_total += 1                      # this is the row number
            values, reason, row_warnings = parse_row(schema, col_map, cells)
            if reason:
                rejected += 1
                conn.execute(
                    "INSERT INTO lead_rejections (file_id, workflow_id, batch_id, "
                    "row_number, reason) VALUES (?, ?, ?, ?, ?)",
                    (file_id, workflow_id, batch_id, rows_total, reason))
                continue
            warnings += row_warnings             # only counted for kept rows
            if _upsert_lead(conn, protector, schema, workflow_id, batch_id, values):
                merged += 1

    conn.execute(
        "UPDATE ingested_files SET rows_total = ?, rows_rejected = ?, "
        "duplicates_merged = ?, field_warnings = ? WHERE id = ?",
        (rows_total, rejected, merged, warnings, file_id))
    return {"file": rel_path, "skipped": False, "rows_total": rows_total,
            "rows_rejected": rejected, "duplicates_merged": merged,
            "field_warnings": warnings}


def ingest_lead_drop(conn, protector, schemas, drop_dir):
    """Ingest every lead CSV in a drop, in a single transaction."""
    drop_dir = Path(drop_dir)
    results = []
    with conn:   # commits at the end, rolls back everything if any error happens
        for wf_dir in sorted((drop_dir / "leads").glob("*")):
            if not wf_dir.is_dir():
                continue
            if wf_dir.name not in schemas:
                raise ValueError(f"No schema for workflow folder '{wf_dir.name}'")
            for csv_path in sorted(wf_dir.glob("*.csv")):
                results.append(ingest_lead_file(
                    conn, protector, schemas[wf_dir.name],
                    drop_dir.name, wf_dir.name, csv_path))
    return results