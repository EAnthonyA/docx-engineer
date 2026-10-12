"""Strict validation for the versioned, non-executable edit-plan contract.

This module deliberately does not select an engine or execute an operation. It
is the Python reference validator used while the Rust worker is introduced.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any


SCHEMA_VERSION = 1
MAX_PLAN_BYTES = 256 * 1024
MAX_OPERATIONS = 32
MAX_TEXT_BYTES = 64 * 1024
MAX_ID_LENGTH = 128
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_ROOT_FIELDS = frozenset({"schema_version", "operations"})
_REPLACE_TEXT_FIELDS = frozenset({"id", "type", "locations", "search", "replacement", "match_case"})
_FORMAT_B_TAGS_FIELDS = frozenset({"id", "type", "locations", "open_tag", "close_tag", "bold"})
_FORMAT_TEXT_FIELDS = frozenset({"id", "type", "locations", "search", "match_case", "format"})
_TEXT_FORMAT_FIELDS = frozenset({"bold", "italic", "underline", "strike", "color", "highlight", "font_name", "size_pt"})
_HIGHLIGHTS = frozenset({
    "black", "blue", "cyan", "darkBlue", "darkCyan", "darkGray", "darkGreen", "darkMagenta",
    "darkRed", "darkYellow", "green", "lightGray", "magenta", "none", "red", "white", "yellow",
})
_DELETE_PARAGRAPHS_FIELDS = frozenset({"id", "type", "locations", "match"})
_PARAGRAPH_MATCH_FIELDS = frozenset({"mode", "text"})
_REGEX_REPLACE_FIELDS = frozenset({"id", "type", "locations", "pattern", "replacement", "case_insensitive"})
_FORMAT_TAGGED_FIELDS = frozenset({"id", "type", "locations", "open_tag", "close_tag", "format"})
_SET_PARAGRAPH_STYLE_FIELDS = frozenset({"id", "type", "locations", "match", "style_id"})
_FORMAT_PARAGRAPHS_FIELDS = frozenset({"id", "type", "locations", "match", "format"})
_SET_PARAGRAPH_LAYOUT_FIELDS = frozenset({"id", "type", "locations", "match", "layout"})
_PARAGRAPH_LAYOUT_FIELDS = frozenset({"alignment", "space_before_pt", "space_after_pt", "left_indent_pt", "right_indent_pt"})
_SET_PARAGRAPH_NUMBERING_FIELDS = frozenset({"id", "type", "locations", "match", "num_id", "level"})
_SET_PARAGRAPH_PAGINATION_FIELDS = frozenset({"id", "type", "locations", "match", "pagination"})
_PARAGRAPH_PAGINATION_FIELDS = frozenset({"keep_with_next", "keep_together", "page_break_before"})
_DELETE_TABLE_ROWS_FIELDS = frozenset({"id", "type", "locations", "match"})
_SET_TABLE_CELL_FORMAT_FIELDS = frozenset({"id", "type", "locations", "match", "format"})
_TABLE_CELL_FORMAT_FIELDS = frozenset({"fill_color", "vertical_alignment", "border_color", "border_size_pt"})
_INSERT_TABLE_ROWS_FIELDS = frozenset({"id", "type", "locations", "anchor", "position", "rows"})
_SET_TABLE_ROW_HEIGHT_FIELDS = frozenset({"id", "type", "locations", "match", "height_pt", "rule"})
_MERGE_TABLE_CELLS_FIELDS = frozenset({"id", "type", "locations", "match", "direction", "span"})
_SET_TABLE_COLUMN_WIDTH_FIELDS = frozenset({"id", "type", "locations", "match", "column_index", "width_pt"})
_INSERT_PARAGRAPHS_FIELDS = frozenset({"id", "type", "locations", "anchor", "position", "paragraphs"})
_INSERTED_PARAGRAPH_FIELDS = frozenset({"text", "style_id", "format", "page_break_before"})
_LOCATIONS = frozenset({"body", "tables", "headers_footers", "all"})


class PlanValidationError(ValueError):
    """A stable, bounded rejection suitable for routing and repair feedback."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ReplaceTextOperation:
    id: str
    location: str
    search: str
    replacement: str


@dataclass(frozen=True)
class FormatBTagsOperation:
    id: str
    location: str


@dataclass(frozen=True)
class TextFormat:
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    strike: bool | None = None
    color: str | None = None
    highlight: str | None = None
    font_name: str | None = None
    size_half_points: int | None = None


@dataclass(frozen=True)
class FormatTextOperation:
    id: str
    location: str
    search: str
    format: TextFormat


@dataclass(frozen=True)
class DeleteParagraphsOperation:
    id: str
    location: str
    mode: str
    text: str


@dataclass(frozen=True)
class RegexReplaceOperation:
    id: str
    location: str
    pattern: str
    replacement: str
    case_insensitive: bool


@dataclass(frozen=True)
class FormatTaggedOperation:
    id: str
    location: str
    open_tag: str
    close_tag: str
    format: TextFormat


@dataclass(frozen=True)
class SetParagraphStyleOperation:
    id: str
    location: str
    mode: str
    text: str
    style_id: str


@dataclass(frozen=True)
class FormatParagraphsOperation:
    id: str
    location: str
    mode: str
    text: str
    format: TextFormat


@dataclass(frozen=True)
class ParagraphLayout:
    alignment: str | None = None
    space_before_twips: int | None = None
    space_after_twips: int | None = None
    left_indent_twips: int | None = None
    right_indent_twips: int | None = None


@dataclass(frozen=True)
class SetParagraphLayoutOperation:
    id: str
    location: str
    mode: str
    text: str
    layout: ParagraphLayout


@dataclass(frozen=True)
class SetParagraphNumberingOperation:
    id: str
    location: str
    mode: str
    text: str
    num_id: int
    level: int


@dataclass(frozen=True)
class ParagraphPagination:
    keep_with_next: bool | None = None
    keep_together: bool | None = None
    page_break_before: bool | None = None


@dataclass(frozen=True)
class SetParagraphPaginationOperation:
    id: str
    location: str
    mode: str
    text: str
    pagination: ParagraphPagination


@dataclass(frozen=True)
class DeleteTableRowsOperation:
    id: str
    location: str
    mode: str
    text: str


@dataclass(frozen=True)
class TableCellFormat:
    fill_color: str | None = None
    vertical_alignment: str | None = None
    border_color: str | None = None
    border_eighth_points: int | None = None


@dataclass(frozen=True)
class SetTableCellFormatOperation:
    id: str
    location: str
    mode: str
    text: str
    format: TableCellFormat


@dataclass(frozen=True)
class InsertTableRowsOperation:
    id: str
    location: str
    anchor_mode: str
    anchor_text: str
    position: str
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class SetTableRowHeightOperation:
    id: str
    location: str
    mode: str
    text: str
    height_twips: int
    rule: str


@dataclass(frozen=True)
class MergeTableCellsOperation:
    id: str
    location: str
    mode: str
    text: str
    span: int
    direction: str

@dataclass(frozen=True)
class SetTableColumnWidthOperation:
    id: str
    location: str
    mode: str
    text: str
    column_index: int
    width_twips: int


@dataclass(frozen=True)
class InsertedParagraph:
    text: str
    style_id: str | None
    format: TextFormat | None
    page_break_before: bool


@dataclass(frozen=True)
class InsertParagraphsOperation:
    id: str
    location: str
    anchor_mode: str
    anchor_text: str
    position: str
    paragraphs: tuple[InsertedParagraph, ...]


@dataclass(frozen=True)
class EditPlan:
    schema_version: int
    operations: tuple[ReplaceTextOperation | FormatBTagsOperation | FormatTextOperation | DeleteParagraphsOperation | RegexReplaceOperation | FormatTaggedOperation | SetParagraphStyleOperation | FormatParagraphsOperation | SetParagraphLayoutOperation | SetParagraphNumberingOperation | SetParagraphPaginationOperation | DeleteTableRowsOperation | SetTableCellFormatOperation | InsertTableRowsOperation | SetTableRowHeightOperation | MergeTableCellsOperation | InsertParagraphsOperation, ...]


def validate_plan_json(raw: bytes | str) -> EditPlan:
    """Validate raw UTF-8 JSON, including its actual wire-size limit."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not isinstance(raw, bytes):
        raise PlanValidationError("invalid_json", "Edit plan must be UTF-8 JSON")
    if len(raw) > MAX_PLAN_BYTES:
        raise PlanValidationError("plan_too_large", "Edit plan exceeds the 256 KiB limit")
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_json_fields)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanValidationError("invalid_json", "Edit plan is not valid UTF-8 JSON") from exc
    return validate_plan(payload)


def validate_plan(payload: Any) -> EditPlan:
    """Validate an already-decoded plan without accepting unknown fields."""
    if not isinstance(payload, dict):
        raise PlanValidationError("invalid_root", "Edit plan must be an object")
    try:
        encoded_size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, UnicodeEncodeError) as exc:
        raise PlanValidationError("invalid_json", "Edit plan contains non-JSON values") from exc
    if encoded_size > MAX_PLAN_BYTES:
        raise PlanValidationError("plan_too_large", "Edit plan exceeds the 256 KiB limit")
    _reject_unknown_fields(payload, _ROOT_FIELDS, "plan")
    _require_fields(payload, _ROOT_FIELDS, "plan")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise PlanValidationError("unsupported_schema", "Only edit-plan schema version 1 is supported")

    operations = payload["operations"]
    if not isinstance(operations, list) or not operations:
        raise PlanValidationError("invalid_operations", "Plan must contain between 1 and 32 operations")
    if len(operations) > MAX_OPERATIONS:
        raise PlanValidationError("too_many_operations", "Plan exceeds the 32-operation limit")

    ids: set[str] = set()
    validated: list[ReplaceTextOperation | FormatBTagsOperation | FormatTextOperation | DeleteParagraphsOperation | RegexReplaceOperation | FormatTaggedOperation | SetParagraphStyleOperation | FormatParagraphsOperation | SetParagraphLayoutOperation | SetParagraphNumberingOperation | SetParagraphPaginationOperation | DeleteTableRowsOperation | SetTableCellFormatOperation | InsertTableRowsOperation | SetTableRowHeightOperation | MergeTableCellsOperation | SetTableColumnWidthOperation | InsertParagraphsOperation] = []
    for index, operation in enumerate(operations):
        validated.append(_validate_operation(operation, index, ids))
    if any(isinstance(operation, (FormatBTagsOperation, FormatTextOperation, FormatTaggedOperation, DeleteParagraphsOperation, SetParagraphStyleOperation, FormatParagraphsOperation, SetParagraphLayoutOperation, SetParagraphNumberingOperation, SetParagraphPaginationOperation, DeleteTableRowsOperation, SetTableCellFormatOperation, InsertTableRowsOperation, SetTableRowHeightOperation, MergeTableCellsOperation, SetTableColumnWidthOperation, InsertParagraphsOperation)) for operation in validated) and len(validated) != 1:
        raise PlanValidationError("unsupported_operation_combination", "format and paragraph-delete operations must be the only operation in a plan")
    return EditPlan(schema_version=SCHEMA_VERSION, operations=tuple(validated))


def _validate_operation(operation: Any, index: int, ids: set[str]) -> ReplaceTextOperation | FormatBTagsOperation | FormatTextOperation | DeleteParagraphsOperation | RegexReplaceOperation | FormatTaggedOperation | SetParagraphStyleOperation | FormatParagraphsOperation | SetParagraphLayoutOperation | SetParagraphNumberingOperation | SetParagraphPaginationOperation | DeleteTableRowsOperation | SetTableCellFormatOperation | InsertTableRowsOperation | SetTableRowHeightOperation | MergeTableCellsOperation | InsertParagraphsOperation:
    context = f"operation {index + 1}"
    if not isinstance(operation, dict):
        raise PlanValidationError("invalid_operation", f"{context} must be an object")
    if operation.get("type") == "replace_text":
        return _validate_replace_text(operation, context, ids)
    if operation.get("type") == "format_b_tags":
        return _validate_format_b_tags(operation, context, ids)
    if operation.get("type") == "format_text":
        return _validate_format_text(operation, context, ids)
    if operation.get("type") == "delete_paragraphs":
        return _validate_delete_paragraphs(operation, context, ids)
    if operation.get("type") == "regex_replace":
        return _validate_regex_replace(operation, context, ids)
    if operation.get("type") == "format_tagged":
        return _validate_format_tagged(operation, context, ids)
    if operation.get("type") == "set_paragraph_style":
        return _validate_set_paragraph_style(operation, context, ids)
    if operation.get("type") == "format_paragraphs":
        return _validate_format_paragraphs(operation, context, ids)
    if operation.get("type") == "set_paragraph_layout":
        return _validate_set_paragraph_layout(operation, context, ids)
    if operation.get("type") == "set_paragraph_numbering":
        return _validate_set_paragraph_numbering(operation, context, ids)
    if operation.get("type") == "set_paragraph_pagination":
        return _validate_set_paragraph_pagination(operation, context, ids)
    if operation.get("type") == "delete_table_rows":
        return _validate_delete_table_rows(operation, context, ids)
    if operation.get("type") == "set_table_cell_format":
        return _validate_set_table_cell_format(operation, context, ids)
    if operation.get("type") == "insert_table_rows":
        return _validate_insert_table_rows(operation, context, ids)
    if operation.get("type") == "set_table_row_height":
        return _validate_set_table_row_height(operation, context, ids)
    if operation.get("type") == "merge_table_cells":
        return _validate_merge_table_cells(operation, context, ids)
    if operation.get("type") == "set_table_column_width":
        return _validate_set_table_column_width(operation, context, ids)
    if operation.get("type") == "insert_paragraphs":
        return _validate_insert_paragraphs(operation, context, ids)
    raise PlanValidationError("unsupported_operation", f"{context} is not a supported operation")


def _validate_replace_text(operation: dict[str, Any], context: str, ids: set[str]) -> ReplaceTextOperation:
    _reject_unknown_fields(operation, _REPLACE_TEXT_FIELDS, context)
    _require_fields(operation, _REPLACE_TEXT_FIELDS, context)

    operation_id = operation["id"]
    if not isinstance(operation_id, str) or not _ID_RE.fullmatch(operation_id) or len(operation_id) > MAX_ID_LENGTH:
        raise PlanValidationError("invalid_operation_id", f"{context} has an invalid id")
    if operation_id in ids:
        raise PlanValidationError("duplicate_operation_id", f"{context} repeats an operation id")
    ids.add(operation_id)

    location = _validate_location(operation["locations"], context)
    if operation["match_case"] is not True:
        raise PlanValidationError("unsupported_match_mode", f"{context} must use case-sensitive matching")

    search = _validate_text(operation["search"], "search", context, empty=False)
    replacement = _validate_text(operation["replacement"], "replacement", context, empty=True)
    return ReplaceTextOperation(id=operation_id, location=location, search=search, replacement=replacement)


def _validate_format_b_tags(operation: dict[str, Any], context: str, ids: set[str]) -> FormatBTagsOperation:
    _reject_unknown_fields(operation, _FORMAT_B_TAGS_FIELDS, context)
    _require_fields(operation, _FORMAT_B_TAGS_FIELDS, context)
    operation_id = operation["id"]
    if not isinstance(operation_id, str) or not _ID_RE.fullmatch(operation_id) or len(operation_id) > MAX_ID_LENGTH:
        raise PlanValidationError("invalid_operation_id", f"{context} has an invalid id")
    if operation_id in ids:
        raise PlanValidationError("duplicate_operation_id", f"{context} repeats an operation id")
    ids.add(operation_id)
    location = _validate_location(operation["locations"], context)
    if operation["open_tag"] != "<B>" or operation["close_tag"] != "<D>" or operation["bold"] is not True:
        raise PlanValidationError("unsupported_format", f"{context} must use the exact <B>…<D> bold format")
    return FormatBTagsOperation(id=operation_id, location=location)


def _validate_format_text(operation: dict[str, Any], context: str, ids: set[str]) -> FormatTextOperation:
    _reject_unknown_fields(operation, _FORMAT_TEXT_FIELDS, context)
    _require_fields(operation, _FORMAT_TEXT_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    location = _validate_location(operation["locations"], context)
    if operation["match_case"] is not True:
        raise PlanValidationError("unsupported_match_mode", f"{context} must use case-sensitive matching")
    return FormatTextOperation(
        id=operation_id, location=location,
        search=_validate_text(operation["search"], "search", context, empty=False),
        format=_validate_text_format(operation["format"], context),
    )


def _validate_text_format(value: Any, context: str) -> TextFormat:
    if not isinstance(value, dict):
        raise PlanValidationError("unsupported_format", f"{context} format must be an object")
    _reject_unknown_fields(value, _TEXT_FORMAT_FIELDS, f"{context} format")
    if not value:
        raise PlanValidationError("unsupported_format", f"{context} format must set at least one property")
    toggles = {name: value.get(name) for name in ("bold", "italic", "underline", "strike")}
    if any(item is not None and type(item) is not bool for item in toggles.values()):
        raise PlanValidationError("unsupported_format", f"{context} format toggles must be booleans")
    color = value.get("color")
    if color is not None and (not isinstance(color, str) or len(color) != 6 or not all(char in "0123456789abcdefABCDEF" for char in color)):
        raise PlanValidationError("unsupported_format", f"{context} format color must be a six-digit hex value")
    highlight = value.get("highlight")
    if highlight is not None and (not isinstance(highlight, str) or highlight not in _HIGHLIGHTS):
        raise PlanValidationError("unsupported_format", f"{context} format highlight must be a supported Word highlight color")
    font_name = value.get("font_name")
    if font_name is not None and (not isinstance(font_name, str) or not font_name or len(font_name.encode("utf-8")) > MAX_ID_LENGTH or any(ord(char) < 32 or ord(char) == 127 for char in font_name)):
        raise PlanValidationError("unsupported_format", f"{context} format font_name must be a non-control string up to 128 bytes")
    size = value.get("size_pt")
    if size is not None and (type(size) not in (int, float) or not math.isfinite(size) or size < 0.5 or size > 1638 or size * 2 != round(size * 2)):
        raise PlanValidationError("unsupported_format", f"{context} format size_pt must be a half-point value from 0.5 to 1638")
    return TextFormat(**toggles, color=color, highlight=highlight, font_name=font_name, size_half_points=round(size * 2) if size is not None else None)


def _validate_delete_paragraphs(operation: dict[str, Any], context: str, ids: set[str]) -> DeleteParagraphsOperation:
    _reject_unknown_fields(operation, _DELETE_PARAGRAPHS_FIELDS, context)
    _require_fields(operation, _DELETE_PARAGRAPHS_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    location = _validate_location(operation["locations"], context)
    if location != "body":
        raise PlanValidationError("unsupported_location", f"{context} paragraph deletion supports body only")
    match = operation["match"]
    if not isinstance(match, dict):
        raise PlanValidationError("unsupported_match_mode", f"{context} match must be an object")
    _reject_unknown_fields(match, _PARAGRAPH_MATCH_FIELDS, f"{context} match")
    _require_fields(match, _PARAGRAPH_MATCH_FIELDS, f"{context} match")
    if match["mode"] not in {"exact", "starts_with", "contains"}:
        raise PlanValidationError("unsupported_match_mode", f"{context} has an unsupported paragraph match mode")
    return DeleteParagraphsOperation(
        id=operation_id, location=location, mode=match["mode"],
        text=_validate_text(match["text"], "match text", context, empty=False),
    )


def _validate_regex_replace(operation: dict[str, Any], context: str, ids: set[str]) -> RegexReplaceOperation:
    _reject_unknown_fields(operation, _REGEX_REPLACE_FIELDS, context)
    _require_fields(operation, _REGEX_REPLACE_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    location = _validate_location(operation["locations"], context)
    if type(operation["case_insensitive"]) is not bool:
        raise PlanValidationError("unsupported_match_mode", f"{context} case_insensitive must be a boolean")
    return RegexReplaceOperation(
        id=operation_id, location=location,
        pattern=_validate_text(operation["pattern"], "pattern", context, empty=False),
        replacement=_validate_text(operation["replacement"], "replacement", context, empty=True),
        case_insensitive=operation["case_insensitive"],
    )


def _validate_format_tagged(operation: dict[str, Any], context: str, ids: set[str]) -> FormatTaggedOperation:
    _reject_unknown_fields(operation, _FORMAT_TAGGED_FIELDS, context)
    _require_fields(operation, _FORMAT_TAGGED_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    open_tag = _validate_text(operation["open_tag"], "open_tag", context, empty=False)
    close_tag = _validate_text(operation["close_tag"], "close_tag", context, empty=False)
    if open_tag == close_tag:
        raise PlanValidationError("unsupported_format", f"{context} opening and closing markers must differ")
    return FormatTaggedOperation(
        id=operation_id, location=_validate_location(operation["locations"], context),
        open_tag=open_tag, close_tag=close_tag, format=_validate_text_format(operation["format"], context),
    )


def _validate_set_paragraph_style(operation: dict[str, Any], context: str, ids: set[str]) -> SetParagraphStyleOperation:
    _reject_unknown_fields(operation, _SET_PARAGRAPH_STYLE_FIELDS, context)
    _require_fields(operation, _SET_PARAGRAPH_STYLE_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    match = operation["match"]
    if not isinstance(match, dict):
        raise PlanValidationError("unsupported_match_mode", f"{context} match must be an object")
    _reject_unknown_fields(match, _PARAGRAPH_MATCH_FIELDS, f"{context} match")
    _require_fields(match, _PARAGRAPH_MATCH_FIELDS, f"{context} match")
    if match["mode"] not in {"exact", "starts_with", "contains"}:
        raise PlanValidationError("unsupported_match_mode", f"{context} has an unsupported paragraph match mode")
    style_id = operation["style_id"]
    if not isinstance(style_id, str) or not _ID_RE.fullmatch(style_id) or len(style_id) > MAX_ID_LENGTH:
        raise PlanValidationError("unsupported_format", f"{context} style_id must be a supported Word style ID")
    return SetParagraphStyleOperation(
        id=operation_id, location=_validate_location(operation["locations"], context),
        mode=match["mode"], text=_validate_text(match["text"], "match text", context, empty=False), style_id=style_id,
    )


def _validate_format_paragraphs(operation: dict[str, Any], context: str, ids: set[str]) -> FormatParagraphsOperation:
    _reject_unknown_fields(operation, _FORMAT_PARAGRAPHS_FIELDS, context)
    _require_fields(operation, _FORMAT_PARAGRAPHS_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    match = operation["match"]
    if not isinstance(match, dict):
        raise PlanValidationError("unsupported_match_mode", f"{context} match must be an object")
    _reject_unknown_fields(match, _PARAGRAPH_MATCH_FIELDS, f"{context} match")
    _require_fields(match, _PARAGRAPH_MATCH_FIELDS, f"{context} match")
    if match["mode"] not in {"exact", "starts_with", "contains"}:
        raise PlanValidationError("unsupported_match_mode", f"{context} has an unsupported paragraph match mode")
    return FormatParagraphsOperation(
        id=operation_id, location=_validate_location(operation["locations"], context),
        mode=match["mode"], text=_validate_text(match["text"], "match text", context, empty=False),
        format=_validate_text_format(operation["format"], context),
    )


def _validate_set_paragraph_layout(operation: dict[str, Any], context: str, ids: set[str]) -> SetParagraphLayoutOperation:
    _reject_unknown_fields(operation, _SET_PARAGRAPH_LAYOUT_FIELDS, context)
    _require_fields(operation, _SET_PARAGRAPH_LAYOUT_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    match = operation["match"]
    if not isinstance(match, dict):
        raise PlanValidationError("unsupported_match_mode", f"{context} match must be an object")
    _reject_unknown_fields(match, _PARAGRAPH_MATCH_FIELDS, f"{context} match")
    _require_fields(match, _PARAGRAPH_MATCH_FIELDS, f"{context} match")
    if match["mode"] not in {"exact", "starts_with", "contains"}:
        raise PlanValidationError("unsupported_match_mode", f"{context} has an unsupported paragraph match mode")
    layout = operation["layout"]
    if not isinstance(layout, dict):
        raise PlanValidationError("unsupported_format", f"{context} layout must be an object")
    _reject_unknown_fields(layout, _PARAGRAPH_LAYOUT_FIELDS, f"{context} layout")
    if not layout:
        raise PlanValidationError("unsupported_format", f"{context} layout must set at least one property")
    alignment = layout.get("alignment")
    if alignment is not None and alignment not in {"left", "center", "right", "justify"}:
        raise PlanValidationError("unsupported_format", f"{context} alignment must be left, center, right, or justify")
    measurements: dict[str, int | None] = {}
    for field in ("space_before_pt", "space_after_pt", "left_indent_pt", "right_indent_pt"):
        value = layout.get(field)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0 or value > 1584 or value * 2 != round(value * 2)):
            raise PlanValidationError("unsupported_format", f"{context} {field} must be a half-point value from 0 to 1584")
        measurements[field] = round(value * 20) if value is not None else None
    return SetParagraphLayoutOperation(
        id=operation_id, location=_validate_location(operation["locations"], context),
        mode=match["mode"], text=_validate_text(match["text"], "match text", context, empty=False),
        layout=ParagraphLayout(
            alignment=alignment, space_before_twips=measurements["space_before_pt"],
            space_after_twips=measurements["space_after_pt"], left_indent_twips=measurements["left_indent_pt"],
            right_indent_twips=measurements["right_indent_pt"],
        ),
    )


def _validate_paragraph_match(value: Any, context: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise PlanValidationError("unsupported_match_mode", f"{context} match must be an object")
    _reject_unknown_fields(value, _PARAGRAPH_MATCH_FIELDS, f"{context} match")
    _require_fields(value, _PARAGRAPH_MATCH_FIELDS, f"{context} match")
    if value["mode"] not in {"exact", "starts_with", "contains"}:
        raise PlanValidationError("unsupported_match_mode", f"{context} has an unsupported paragraph match mode")
    return {"mode": value["mode"], "text": _validate_text(value["text"], "match text", context, empty=False)}


def _validate_set_paragraph_numbering(operation: dict[str, Any], context: str, ids: set[str]) -> SetParagraphNumberingOperation:
    _reject_unknown_fields(operation, _SET_PARAGRAPH_NUMBERING_FIELDS, context)
    _require_fields(operation, _SET_PARAGRAPH_NUMBERING_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    match = _validate_paragraph_match(operation["match"], context)
    num_id = operation["num_id"]
    level = operation["level"]
    if type(num_id) is not int or not 0 <= num_id <= 4_294_967_295:
        raise PlanValidationError("unsupported_format", f"{context} num_id must be an unsigned 32-bit existing Word numbering ID")
    if type(level) is not int or not 0 <= level <= 8:
        raise PlanValidationError("unsupported_format", f"{context} level must be from 0 to 8")
    return SetParagraphNumberingOperation(
        id=operation_id, location=_validate_location(operation["locations"], context),
        mode=match["mode"], text=_validate_text(match["text"], "match text", context, empty=False),
        num_id=num_id, level=level,
    )


def _validate_set_paragraph_pagination(operation: dict[str, Any], context: str, ids: set[str]) -> SetParagraphPaginationOperation:
    _reject_unknown_fields(operation, _SET_PARAGRAPH_PAGINATION_FIELDS, context)
    _require_fields(operation, _SET_PARAGRAPH_PAGINATION_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    match = _validate_paragraph_match(operation["match"], context)
    pagination = operation["pagination"]
    if not isinstance(pagination, dict):
        raise PlanValidationError("unsupported_format", f"{context} pagination must be an object")
    _reject_unknown_fields(pagination, _PARAGRAPH_PAGINATION_FIELDS, f"{context} pagination")
    if not pagination:
        raise PlanValidationError("unsupported_format", f"{context} pagination must set at least one property")
    if any(value is not None and type(value) is not bool for value in pagination.values()):
        raise PlanValidationError("unsupported_format", f"{context} pagination properties must be booleans")
    return SetParagraphPaginationOperation(
        id=operation_id, location=_validate_location(operation["locations"], context),
        mode=match["mode"], text=_validate_text(match["text"], "match text", context, empty=False),
        pagination=ParagraphPagination(**pagination),
    )


def _validate_delete_table_rows(operation: dict[str, Any], context: str, ids: set[str]) -> DeleteTableRowsOperation:
    _reject_unknown_fields(operation, _DELETE_TABLE_ROWS_FIELDS, context)
    _require_fields(operation, _DELETE_TABLE_ROWS_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    if _validate_location(operation["locations"], context) != "tables":
        raise PlanValidationError("unsupported_location", f"{context} table-row deletion supports tables only")
    match = _validate_paragraph_match(operation["match"], context)
    return DeleteTableRowsOperation(
        id=operation_id, location="tables", mode=match["mode"], text=match["text"],
    )


def _validate_set_table_cell_format(operation: dict[str, Any], context: str, ids: set[str]) -> SetTableCellFormatOperation:
    _reject_unknown_fields(operation, _SET_TABLE_CELL_FORMAT_FIELDS, context)
    _require_fields(operation, _SET_TABLE_CELL_FORMAT_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    if _validate_location(operation["locations"], context) != "tables":
        raise PlanValidationError("unsupported_location", f"{context} table-cell formatting supports tables only")
    match = _validate_paragraph_match(operation["match"], context)
    format = operation["format"]
    if not isinstance(format, dict):
        raise PlanValidationError("unsupported_format", f"{context} format must be an object")
    _reject_unknown_fields(format, _TABLE_CELL_FORMAT_FIELDS, f"{context} format")
    if not format:
        raise PlanValidationError("unsupported_format", f"{context} format must set at least one property")
    fill_color = format.get("fill_color")
    if fill_color is not None and (not isinstance(fill_color, str) or len(fill_color) != 6 or not all(char in "0123456789abcdefABCDEF" for char in fill_color)):
        raise PlanValidationError("unsupported_format", f"{context} format fill_color must be a six-digit hex value")
    vertical_alignment = format.get("vertical_alignment")
    if vertical_alignment is not None and vertical_alignment not in {"top", "center", "bottom"}:
        raise PlanValidationError("unsupported_format", f"{context} format vertical_alignment must be top, center, or bottom")
    border_color = format.get("border_color")
    border_size = format.get("border_size_pt")
    if border_color is not None and (not isinstance(border_color, str) or len(border_color) != 6 or not all(char in "0123456789abcdefABCDEF" for char in border_color)):
        raise PlanValidationError("unsupported_format", f"{context} format border_color must be a six-digit hex value")
    if border_size is not None and (type(border_size) not in (int, float) or not math.isfinite(border_size) or border_size < 0.125 or border_size > 31.75 or border_size * 8 != round(border_size * 8)):
        raise PlanValidationError("unsupported_format", f"{context} format border_size_pt must be an eighth-point value from 0.125 to 31.75")
    if (border_color is None) != (border_size is None):
        raise PlanValidationError("unsupported_format", f"{context} border_color and border_size_pt must be set together")
    return SetTableCellFormatOperation(
        id=operation_id, location="tables", mode=match["mode"], text=match["text"],
        format=TableCellFormat(fill_color=fill_color, vertical_alignment=vertical_alignment, border_color=border_color, border_eighth_points=round(border_size * 8) if border_size is not None else None),
    )


def _validate_insert_table_rows(operation: dict[str, Any], context: str, ids: set[str]) -> InsertTableRowsOperation:
    _reject_unknown_fields(operation, _INSERT_TABLE_ROWS_FIELDS, context)
    _require_fields(operation, _INSERT_TABLE_ROWS_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    if _validate_location(operation["locations"], context) != "tables":
        raise PlanValidationError("unsupported_location", f"{context} table-row insertion supports tables only")
    anchor = _validate_paragraph_match(operation["anchor"], context)
    if operation["position"] not in {"before", "after"}:
        raise PlanValidationError("unsupported_format", f"{context} position must be before or after")
    rows = operation["rows"]
    if not isinstance(rows, list) or not rows or len(rows) > MAX_OPERATIONS:
        raise PlanValidationError("invalid_operations", f"{context} must insert between 1 and 32 rows")
    validated = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"cells"} or not isinstance(row["cells"], list) or not row["cells"] or len(row["cells"]) > 64:
            raise PlanValidationError("invalid_operation", f"{context} row must contain 1 to 64 cells")
        cells = tuple(_validate_text(cell, "cell text", context, empty=True) for cell in row["cells"])
        if any("\r" in cell or "\n" in cell for cell in cells):
            raise PlanValidationError("unsupported_format", f"{context} cell text cannot contain line breaks")
        validated.append(cells)
    return InsertTableRowsOperation(id=operation_id, location="tables", anchor_mode=anchor["mode"], anchor_text=anchor["text"], position=operation["position"], rows=tuple(validated))


def _validate_set_table_row_height(operation: dict[str, Any], context: str, ids: set[str]) -> SetTableRowHeightOperation:
    _reject_unknown_fields(operation, _SET_TABLE_ROW_HEIGHT_FIELDS, context)
    _require_fields(operation, _SET_TABLE_ROW_HEIGHT_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    if _validate_location(operation["locations"], context) != "tables":
        raise PlanValidationError("unsupported_location", f"{context} table-row height supports tables only")
    match = _validate_paragraph_match(operation["match"], context)
    height = operation["height_pt"]
    if type(height) not in (int, float) or not math.isfinite(height) or height < 0.5 or height > 1584 or height * 2 != round(height * 2):
        raise PlanValidationError("unsupported_format", f"{context} height_pt must be a half-point value from 0.5 to 1584")
    if operation["rule"] not in {"at_least", "exact"}:
        raise PlanValidationError("unsupported_format", f"{context} rule must be at_least or exact")
    return SetTableRowHeightOperation(
        id=operation_id, location="tables", mode=match["mode"], text=match["text"],
        height_twips=round(height * 20), rule=operation["rule"],
    )


def _validate_merge_table_cells(operation: dict[str, Any], context: str, ids: set[str]) -> MergeTableCellsOperation:
    _reject_unknown_fields(operation, _MERGE_TABLE_CELLS_FIELDS, context)
    _require_fields(operation, _MERGE_TABLE_CELLS_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    if _validate_location(operation["locations"], context) != "tables":
        raise PlanValidationError("unsupported_location", f"{context} table-cell merging supports tables only")
    match = _validate_paragraph_match(operation["match"], context)
    if operation["direction"] not in {"right", "down"}:
        raise PlanValidationError("unsupported_format", f"{context} direction must be right or down")
    span = operation["span"]
    if type(span) is not int or not 2 <= span <= 64:
        raise PlanValidationError("unsupported_format", f"{context} span must be an integer from 2 to 64")
    return MergeTableCellsOperation(id=operation_id, location="tables", mode=match["mode"], text=match["text"], span=span, direction=operation["direction"])


def _validate_set_table_column_width(operation: dict[str, Any], context: str, ids: set[str]) -> SetTableColumnWidthOperation:
    _reject_unknown_fields(operation, _SET_TABLE_COLUMN_WIDTH_FIELDS, context)
    _require_fields(operation, _SET_TABLE_COLUMN_WIDTH_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    if _validate_location(operation["locations"], context) != "tables":
        raise PlanValidationError("unsupported_location", f"{context} table-column width supports tables only")
    match = _validate_paragraph_match(operation["match"], context)
    index, width = operation["column_index"], operation["width_pt"]
    if type(index) is not int or not 0 <= index <= 63:
        raise PlanValidationError("unsupported_format", f"{context} column_index must be an integer from 0 to 63")
    if type(width) not in (int, float) or not math.isfinite(width) or width < 0.5 or width > 1584 or width * 2 != round(width * 2):
        raise PlanValidationError("unsupported_format", f"{context} width_pt must be a half-point value from 0.5 to 1584")
    return SetTableColumnWidthOperation(id=operation_id, location="tables", mode=match["mode"], text=match["text"], column_index=index, width_twips=round(width * 20))


def _validate_insert_paragraphs(operation: dict[str, Any], context: str, ids: set[str]) -> InsertParagraphsOperation:
    _reject_unknown_fields(operation, _INSERT_PARAGRAPHS_FIELDS, context)
    _require_fields(operation, _INSERT_PARAGRAPHS_FIELDS, context)
    operation_id = _validate_operation_id(operation["id"], context, ids)
    location = _validate_location(operation["locations"], context)
    if location not in {"body", "headers_footers"}:
        raise PlanValidationError("unsupported_location", f"{context} paragraph insertion supports body or headers/footers only")
    anchor = operation["anchor"]
    if not isinstance(anchor, dict):
        raise PlanValidationError("unsupported_match_mode", f"{context} anchor must be an object")
    _reject_unknown_fields(anchor, _PARAGRAPH_MATCH_FIELDS, f"{context} anchor")
    _require_fields(anchor, _PARAGRAPH_MATCH_FIELDS, f"{context} anchor")
    if anchor["mode"] not in {"exact", "starts_with", "contains"}:
        raise PlanValidationError("unsupported_match_mode", f"{context} has an unsupported anchor match mode")
    if operation["position"] not in {"before", "after"}:
        raise PlanValidationError("unsupported_format", f"{context} position must be before or after")
    paragraphs = operation["paragraphs"]
    if not isinstance(paragraphs, list) or not paragraphs or len(paragraphs) > MAX_OPERATIONS:
        raise PlanValidationError("invalid_operations", f"{context} must insert between 1 and 32 paragraphs")
    validated = []
    for paragraph in paragraphs:
        if not isinstance(paragraph, dict):
            raise PlanValidationError("invalid_operation", f"{context} paragraph must be an object")
        _reject_unknown_fields(paragraph, _INSERTED_PARAGRAPH_FIELDS, f"{context} paragraph")
        if "text" not in paragraph:
            raise PlanValidationError("missing_field", f"{context} paragraph is missing text")
        text = _validate_text(paragraph["text"], "paragraph text", context, empty=True)
        if "\r" in text or "\n" in text:
            raise PlanValidationError("unsupported_format", f"{context} paragraph text cannot contain line breaks")
        style_id = paragraph.get("style_id")
        if style_id is not None and (not isinstance(style_id, str) or not _ID_RE.fullmatch(style_id) or len(style_id) > MAX_ID_LENGTH):
            raise PlanValidationError("unsupported_format", f"{context} paragraph style_id must be a supported Word style ID")
        page_break_before = paragraph.get("page_break_before", False)
        if type(page_break_before) is not bool:
            raise PlanValidationError("unsupported_format", f"{context} paragraph page_break_before must be a boolean")
        format = paragraph.get("format")
        validated.append(InsertedParagraph(
            text=text, style_id=style_id,
            format=_validate_text_format(format, context) if format is not None else None,
            page_break_before=page_break_before,
        ))
    return InsertParagraphsOperation(
        id=operation_id, location=location, anchor_mode=anchor["mode"],
        anchor_text=_validate_text(anchor["text"], "anchor text", context, empty=False),
        position=operation["position"], paragraphs=tuple(validated),
    )


def _validate_location(value: Any, context: str) -> str:
    if not isinstance(value, list) or len(value) != 1 or value[0] not in _LOCATIONS:
        raise PlanValidationError(
            "unsupported_location",
            f"{context} must target one of body, tables, headers_footers, or all",
        )
    return value[0]


def _validate_operation_id(value: Any, context: str, ids: set[str]) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value) or len(value) > MAX_ID_LENGTH:
        raise PlanValidationError("invalid_operation_id", f"{context} has an invalid id")
    if value in ids:
        raise PlanValidationError("duplicate_operation_id", f"{context} repeats an operation id")
    ids.add(value)
    return value


def _validate_text(value: Any, name: str, context: str, *, empty: bool) -> str:
    if not isinstance(value, str) or (not empty and not value):
        raise PlanValidationError("invalid_text", f"{context} has an invalid {name}")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise PlanValidationError("text_too_large", f"{context} {name} exceeds the 64 KiB limit")
    return value


def _reject_unknown_fields(value: dict[str, Any], allowed: frozenset[str], context: str) -> None:
    if set(value) - allowed:
        raise PlanValidationError("unknown_field", f"{context} contains an unknown field")


def _require_fields(value: dict[str, Any], required: frozenset[str], context: str) -> None:
    if required - set(value):
        raise PlanValidationError("missing_field", f"{context} is missing a required field")


def _reject_duplicate_json_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanValidationError("duplicate_field", "Edit plan contains a duplicate field")
        result[key] = value
    return result
