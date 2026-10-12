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


@pytest.mark.parametrize("location", ["body", "tables", "headers_footers", "all"])
def test_each_rust_document_location_is_accepted(location):
    plan = _valid_plan()
    plan["operations"][0]["locations"] = [location]
    assert validate_plan(plan).operations[0].location == location


def test_literal_text_format_is_accepted_with_bounded_properties():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "style_total", "type": "format_text", "locations": ["all"],
            "search": "Total", "match_case": True,
            "format": {"bold": True, "strike": True, "color": "FF0000", "highlight": "yellow", "font_name": "Aptos", "size_pt": 13.5},
        }],
    }
    result = validate_plan(plan).operations[0]
    assert result.format.size_half_points == 27
    assert result.format.color == "FF0000"
    assert result.format.strike is True
    assert result.format.highlight == "yellow"
    assert result.format.font_name == "Aptos"


@pytest.mark.parametrize("format", [
    {"highlight": "orange"},
    {"font_name": ""},
    {"font_name": "A\nptos"},
])
def test_extended_text_format_properties_are_bounded(format):
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "style_total", "type": "format_text", "locations": ["body"],
            "search": "Total", "match_case": True, "format": format,
        }],
    }
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(plan)
    assert exc.value.code == "unsupported_format"


def test_body_paragraph_deletion_is_accepted():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "delete_todos", "type": "delete_paragraphs", "locations": ["body"],
            "match": {"mode": "starts_with", "text": "TODO:"},
        }],
    }
    result = validate_plan(plan).operations[0]
    assert result.mode == "starts_with"


def test_regex_replace_is_accepted_with_explicit_case_mode():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "date", "type": "regex_replace", "locations": ["all"],
            "pattern": r"(\d{2})\.(\d{2})\.(\d{4})", "replacement": "$3-$2-$1",
            "case_insensitive": False,
        }],
    }
    result = validate_plan(plan).operations[0]
    assert result.replacement == "$3-$2-$1"


def test_tagged_formatting_is_accepted():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "strong", "type": "format_tagged", "locations": ["all"],
            "open_tag": "<strong>", "close_tag": "</strong>", "format": {"bold": True},
        }],
    }
    result = validate_plan(plan).operations[0]
    assert result.open_tag == "<strong>"


def test_existing_paragraph_style_assignment_is_accepted():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "heading", "type": "set_paragraph_style", "locations": ["body"],
            "match": {"mode": "exact", "text": "Introduction"}, "style_id": "Heading1",
        }],
    }
    assert validate_plan(plan).operations[0].style_id == "Heading1"


def test_paragraph_wide_formatting_is_accepted():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "important", "type": "format_paragraphs", "locations": ["all"],
            "match": {"mode": "starts_with", "text": "IMPORTANT:"}, "format": {"bold": True},
        }],
    }
    assert validate_plan(plan).operations[0].format.bold is True


def test_paragraph_layout_is_accepted_with_bounded_measurements():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "layout", "type": "set_paragraph_layout", "locations": ["all"],
            "match": {"mode": "exact", "text": "Title"},
            "layout": {"alignment": "center", "space_after_pt": 12.5, "left_indent_pt": 18},
        }],
    }
    result = validate_plan(plan).operations[0]
    assert result.layout.alignment == "center"
    assert result.layout.space_after_twips == 250
    assert result.layout.left_indent_twips == 360


def test_paragraph_numbering_and_pagination_are_accepted():
    numbering = validate_plan({
        "schema_version": 1,
        "operations": [{
            "id": "numbers", "type": "set_paragraph_numbering", "locations": ["all"],
            "match": {"mode": "starts_with", "text": "Step"}, "num_id": 5, "level": 2,
        }],
    }).operations[0]
    assert (numbering.num_id, numbering.level) == (5, 2)
    pagination = validate_plan({
        "schema_version": 1,
        "operations": [{
            "id": "keep", "type": "set_paragraph_pagination", "locations": ["body"],
            "match": {"mode": "exact", "text": "Title"},
            "pagination": {"keep_with_next": True, "page_break_before": False},
        }],
    }).operations[0]
    assert pagination.pagination.keep_with_next is True
    assert pagination.pagination.page_break_before is False


def test_table_row_deletion_is_tables_only():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "delete_row", "type": "delete_table_rows", "locations": ["tables"],
            "match": {"mode": "contains", "text": "DISCONTINUED"},
        }],
    }
    assert validate_plan(plan).operations[0].text == "DISCONTINUED"
    plan["operations"][0]["locations"] = ["body"]
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(plan)
    assert exc.value.code == "unsupported_location"


def test_table_cell_format_is_accepted_and_tables_only():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "format_cell", "type": "set_table_cell_format", "locations": ["tables"],
            "match": {"mode": "exact", "text": "Total"},
            "format": {"fill_color": "FFF2CC", "vertical_alignment": "center", "border_color": "7F6000", "border_size_pt": 0.5},
        }],
    }
    result = validate_plan(plan).operations[0]
    assert result.format.fill_color == "FFF2CC"
    assert result.format.vertical_alignment == "center"
    assert result.format.border_eighth_points == 4


def test_table_row_insertion_height_and_horizontal_merge_are_accepted():
    insert = validate_plan({
        "schema_version": 1,
        "operations": [{
            "id": "insert", "type": "insert_table_rows", "locations": ["tables"],
            "anchor": {"mode": "exact", "text": "Template"}, "position": "after",
            "rows": [{"cells": ["Widget", "2"]}],
        }],
    }).operations[0]
    assert insert.rows == (("Widget", "2"),)

    height = validate_plan({
        "schema_version": 1,
        "operations": [{
            "id": "height", "type": "set_table_row_height", "locations": ["tables"],
            "match": {"mode": "contains", "text": "Total"}, "height_pt": 24, "rule": "exact",
        }],
    }).operations[0]
    assert height.height_twips == 480
    assert height.rule == "exact"

    merge = validate_plan({
        "schema_version": 1,
        "operations": [{
            "id": "merge", "type": "merge_table_cells", "locations": ["tables"],
            "match": {"mode": "exact", "text": "Summary"}, "direction": "right", "span": 2,
        }],
    }).operations[0]
    assert merge.span == 2


def test_body_paragraph_insertion_is_accepted():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "insert", "type": "insert_paragraphs", "locations": ["body"],
            "anchor": {"mode": "exact", "text": "Introduction"}, "position": "after",
            "paragraphs": [{"text": "New section", "style_id": "Heading1", "page_break_before": True, "format": {"bold": True}}, {"text": "Body"}],
        }],
    }
    result = validate_plan(plan).operations[0]
    assert len(result.paragraphs) == 2
    assert result.paragraphs[0].page_break_before is True
    assert result.paragraphs[0].format.bold is True


def test_header_footer_paragraph_insertion_is_accepted():
    plan = {
        "schema_version": 1,
        "operations": [{
            "id": "insert_header", "type": "insert_paragraphs", "locations": ["headers_footers"],
            "anchor": {"mode": "exact", "text": "Company"}, "position": "after",
            "paragraphs": [{"text": "Confidential"}],
        }],
    }
    assert validate_plan(plan).operations[0].location == "headers_footers"


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
    ("type", "regex_replace", "unknown_field"),
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
