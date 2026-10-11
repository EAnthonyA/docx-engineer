import json
from pathlib import Path

import pytest

from app.edit_plan import MAX_PLAN_BYTES, MAX_TEXT_BYTES, PlanValidationError, validate_plan, validate_plan_json


EXAMPLES = Path(__file__).resolve().parents[2] / "schemas" / "examples"


def _valid_plan():
    return json.loads((EXAMPLES / "edit-plan-v1.valid.json").read_text())


def test_valid_example_is_accepted_and_keeps_operation_order():
    plan = _valid_plan()
    plan["operations"].append({
        "id": "replace_account", "type": "replace_text", "locations": ["body"],
        "search": "{{account_id}}", "replacement": "42", "match_case": True,
    })
    result = validate_plan(plan)
    assert [operation.id for operation in result.operations] == ["replace_customer", "replace_account"]


def test_exact_b_tag_format_operation_is_accepted_and_cannot_be_combined():
    plan = json.loads((EXAMPLES / "edit-plan-v1.format-b-tags.json").read_text())
    assert validate_plan(plan).operations[0].id == "format_b_tags"
    plan["operations"].append(_valid_plan()["operations"][0])
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(plan)
    assert exc.value.code == "unsupported_operation_combination"


@pytest.mark.parametrize("name,code", [
    ("edit-plan-v1.invalid-unknown-field.json", "unknown_field"),
    ("edit-plan-v1.invalid-unsupported-location.json", "unsupported_location"),
])
def test_invalid_examples_are_rejected(name, code):
    with pytest.raises(PlanValidationError) as exc:
        validate_plan_json((EXAMPLES / name).read_bytes())
    assert exc.value.code == code


@pytest.mark.parametrize("field,value,code", [
    ("schema_version", 2, "unsupported_schema"),
    ("type", "regex_replace", "unsupported_operation"),
    ("match_case", False, "unsupported_match_mode"),
    ("search", "", "invalid_text"),
    ("locations", ["body", "tables"], "unsupported_location"),
])
def test_unsupported_contract_features_are_never_silently_accepted(field, value, code):
    plan = _valid_plan()
    target = plan if field == "schema_version" else plan["operations"][0]
    target[field] = value
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(plan)
    assert exc.value.code == code


def test_duplicate_operation_ids_and_utf8_text_limits_are_rejected():
    plan = _valid_plan()
    duplicate = dict(plan["operations"][0])
    duplicate["search"] = "second"
    plan["operations"].append(duplicate)
    with pytest.raises(PlanValidationError, match="repeats"):
        validate_plan(plan)

    plan = _valid_plan()
    plan["operations"][0]["replacement"] = "é" * (MAX_TEXT_BYTES // 2 + 1)
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(plan)
    assert exc.value.code == "text_too_large"


def test_raw_json_size_limit_is_checked_before_decoding():
    raw = b"{" + b" " * MAX_PLAN_BYTES + b"}"
    with pytest.raises(PlanValidationError) as exc:
        validate_plan_json(raw)
    assert exc.value.code == "plan_too_large"


def test_duplicate_json_fields_are_rejected_instead_of_last_value_winning():
    raw = b'{"schema_version":1,"schema_version":1,"operations":[]}'
    with pytest.raises(PlanValidationError) as exc:
        validate_plan_json(raw)
    assert exc.value.code == "duplicate_field"
