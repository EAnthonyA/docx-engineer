"""Strict validation for the versioned, non-executable edit-plan contract.

This module deliberately does not select an engine or execute an operation. It
is the Python reference validator used while the Rust worker is introduced.
"""

from __future__ import annotations

import json
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


class PlanValidationError(ValueError):
    """A stable, bounded rejection suitable for routing and repair feedback."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ReplaceTextOperation:
    id: str
    search: str
    replacement: str


@dataclass(frozen=True)
class FormatBTagsOperation:
    id: str


@dataclass(frozen=True)
class EditPlan:
    schema_version: int
    operations: tuple[ReplaceTextOperation | FormatBTagsOperation, ...]


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
    validated: list[ReplaceTextOperation | FormatBTagsOperation] = []
    for index, operation in enumerate(operations):
        validated.append(_validate_operation(operation, index, ids))
    if any(isinstance(operation, FormatBTagsOperation) for operation in validated) and len(validated) != 1:
        raise PlanValidationError("unsupported_operation_combination", "format_b_tags must be the only operation in a plan")
    return EditPlan(schema_version=SCHEMA_VERSION, operations=tuple(validated))


def _validate_operation(operation: Any, index: int, ids: set[str]) -> ReplaceTextOperation | FormatBTagsOperation:
    context = f"operation {index + 1}"
    if not isinstance(operation, dict):
        raise PlanValidationError("invalid_operation", f"{context} must be an object")
    if operation.get("type") == "replace_text":
        return _validate_replace_text(operation, context, ids)
    if operation.get("type") == "format_b_tags":
        return _validate_format_b_tags(operation, context, ids)
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

    if operation["locations"] != ["body"]:
        raise PlanValidationError("unsupported_location", f"{context} must target ordinary body paragraphs")
    if operation["match_case"] is not True:
        raise PlanValidationError("unsupported_match_mode", f"{context} must use case-sensitive matching")

    search = _validate_text(operation["search"], "search", context, empty=False)
    replacement = _validate_text(operation["replacement"], "replacement", context, empty=True)
    return ReplaceTextOperation(id=operation_id, search=search, replacement=replacement)


def _validate_format_b_tags(operation: dict[str, Any], context: str, ids: set[str]) -> FormatBTagsOperation:
    _reject_unknown_fields(operation, _FORMAT_B_TAGS_FIELDS, context)
    _require_fields(operation, _FORMAT_B_TAGS_FIELDS, context)
    operation_id = operation["id"]
    if not isinstance(operation_id, str) or not _ID_RE.fullmatch(operation_id) or len(operation_id) > MAX_ID_LENGTH:
        raise PlanValidationError("invalid_operation_id", f"{context} has an invalid id")
    if operation_id in ids:
        raise PlanValidationError("duplicate_operation_id", f"{context} repeats an operation id")
    ids.add(operation_id)
    if operation["locations"] != ["body"]:
        raise PlanValidationError("unsupported_location", f"{context} must target ordinary body paragraphs")
    if operation["open_tag"] != "<B>" or operation["close_tag"] != "<D>" or operation["bold"] is not True:
        raise PlanValidationError("unsupported_format", f"{context} must use the exact <B>…<D> bold format")
    return FormatBTagsOperation(id=operation_id)


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
