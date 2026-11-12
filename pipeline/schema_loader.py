import csv
import json
from pathlib import Path

from .normalize import norm_header

# Folder that holds motor_renewal.json, policy_feedback.json, dispositions.csv
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "assignment-a-data" / "schemas"


def load_workflow_schemas(schema_dir=SCHEMA_DIR):
    """Return {workflow_id: schema_dict}. Fields stay in file order."""
    schemas = {}
    for path in sorted(Path(schema_dir).glob("*.json")):
        with open(path, encoding="utf-8") as f:
            schema = json.load(f)
        for field in schema["fields"]:
            # every accepted header spelling, normalised the same way as CSV headers
            names = [field["name"]] + field.get("aliases", [])
            field["_header_keys"] = {norm_header(n) for n in names}
        schemas[schema["workflow_id"]] = schema
    return schemas


def load_dispositions(schema_dir=SCHEMA_DIR):
    """Return {(workflow_id, code): {"is_terminal": bool, "is_success": bool}}."""
    result = {}
    with open(Path(schema_dir) / "dispositions.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            result[(row["workflow_id"], row["code"])] = {
                "is_terminal": row["is_terminal"].strip().lower() == "true",
                "is_success": row["is_success"].strip().lower() == "true",
            }
    return result