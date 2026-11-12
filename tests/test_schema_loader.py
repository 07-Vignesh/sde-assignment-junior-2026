from pipeline.schema_loader import load_workflow_schemas, load_dispositions


def test_schemas_loaded():
    schemas = load_workflow_schemas()
    assert set(schemas) == {"motor_renewal", "policy_feedback"}
    names = [f["name"] for f in schemas["motor_renewal"]["fields"]]
    assert names[:3] == ["customer_name", "phone", "policy_number"]


def test_header_keys():
    schemas = load_workflow_schemas()
    phone = next(f for f in schemas["motor_renewal"]["fields"] if f["name"] == "phone")
    assert "phone" in phone["_header_keys"]
    assert "mobile no" in phone["_header_keys"]


def test_dispositions():
    d = load_dispositions()
    assert d[("motor_renewal", "renewed")] == {"is_terminal": True, "is_success": True}
    assert d[("motor_renewal", "callback_requested")]["is_terminal"] is False
    assert ("motor_renewal", "feedback_captured") not in d