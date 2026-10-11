use std::collections::HashSet;

use serde::Deserialize;

pub const SCHEMA_VERSION: u8 = 1;
pub const MAX_PLAN_BYTES: usize = 256 * 1024;
pub const MAX_OPERATIONS: usize = 32;
pub const MAX_TEXT_BYTES: usize = 64 * 1024;
pub const MAX_ID_LENGTH: usize = 128;

#[derive(Debug, PartialEq, Eq)]
pub enum PlanError {
    PlanTooLarge,
    InvalidJson,
    UnsupportedSchema,
    InvalidOperations,
    TooManyOperations,
    InvalidOperationId,
    DuplicateOperationId,
    UnsupportedOperation,
    UnsupportedLocation,
    UnsupportedMatchMode,
    UnsupportedFormat,
    UnsupportedOperationCombination,
    InvalidText,
    TextTooLarge,
}

impl PlanError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::PlanTooLarge => "plan_too_large",
            Self::InvalidJson => "invalid_json",
            Self::UnsupportedSchema => "unsupported_schema",
            Self::InvalidOperations => "invalid_operations",
            Self::TooManyOperations => "too_many_operations",
            Self::InvalidOperationId => "invalid_operation_id",
            Self::DuplicateOperationId => "duplicate_operation_id",
            Self::UnsupportedOperation => "unsupported_operation",
            Self::UnsupportedLocation => "unsupported_location",
            Self::UnsupportedMatchMode => "unsupported_match_mode",
            Self::UnsupportedFormat => "unsupported_format",
            Self::UnsupportedOperationCombination => "unsupported_operation_combination",
            Self::InvalidText => "invalid_text",
            Self::TextTooLarge => "text_too_large",
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawPlan {
    schema_version: u8,
    operations: Vec<RawOperation>,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
enum RawOperation {
    #[serde(rename = "replace_text")]
    ReplaceText {
        id: String,
        locations: Vec<String>,
        search: String,
        replacement: String,
        match_case: bool,
    },
    #[serde(rename = "format_b_tags")]
    FormatBTags {
        id: String,
        locations: Vec<String>,
        open_tag: String,
        close_tag: String,
        bold: bool,
    },
}

#[derive(Debug, PartialEq, Eq)]
pub struct ReplaceTextOperation {
    pub id: String,
    pub search: String,
    pub replacement: String,
}

#[derive(Debug, PartialEq, Eq)]
pub struct FormatBTagsOperation {
    pub id: String,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Operation {
    ReplaceText(ReplaceTextOperation),
    FormatBTags(FormatBTagsOperation),
}

#[derive(Debug, PartialEq, Eq)]
pub struct EditPlan {
    pub operations: Vec<Operation>,
}

pub fn validate_plan_json(bytes: &[u8]) -> Result<EditPlan, PlanError> {
    if bytes.len() > MAX_PLAN_BYTES {
        return Err(PlanError::PlanTooLarge);
    }
    let raw = serde_json::from_slice(bytes).map_err(|_| unsupported_operation(bytes).unwrap_or(PlanError::InvalidJson))?;
    validate_plan(raw)
}

fn validate_plan(plan: RawPlan) -> Result<EditPlan, PlanError> {
    if plan.schema_version != SCHEMA_VERSION {
        return Err(PlanError::UnsupportedSchema);
    }
    if plan.operations.is_empty() {
        return Err(PlanError::InvalidOperations);
    }
    if plan.operations.len() > MAX_OPERATIONS {
        return Err(PlanError::TooManyOperations);
    }

    let mut ids = HashSet::with_capacity(plan.operations.len());
    let mut operations = Vec::with_capacity(plan.operations.len());
    for operation in plan.operations {
        let id = match &operation {
            RawOperation::ReplaceText { id, .. } | RawOperation::FormatBTags { id, .. } => id,
        };
        if !valid_id(id) {
            return Err(PlanError::InvalidOperationId);
        }
        if !ids.insert(id.clone()) {
            return Err(PlanError::DuplicateOperationId);
        }
        match operation {
            RawOperation::ReplaceText { id, locations, search, replacement, match_case } => {
                if locations != ["body"] { return Err(PlanError::UnsupportedLocation); }
                if !match_case { return Err(PlanError::UnsupportedMatchMode); }
                validate_text(&search, false)?;
                validate_text(&replacement, true)?;
                operations.push(Operation::ReplaceText(ReplaceTextOperation { id, search, replacement }));
            }
            RawOperation::FormatBTags { id, locations, open_tag, close_tag, bold } => {
                if locations != ["body"] { return Err(PlanError::UnsupportedLocation); }
                if open_tag != "<B>" || close_tag != "<D>" || !bold { return Err(PlanError::UnsupportedFormat); }
                operations.push(Operation::FormatBTags(FormatBTagsOperation { id }));
            }
        }
    }
    if operations.iter().any(|operation| matches!(operation, Operation::FormatBTags(_))) && operations.len() != 1 {
        return Err(PlanError::UnsupportedOperationCombination);
    }
    Ok(EditPlan { operations })
}

fn unsupported_operation(bytes: &[u8]) -> Option<PlanError> {
    let value: serde_json::Value = serde_json::from_slice(bytes).ok()?;
    let operations = value.get("operations")?.as_array()?;
    operations.iter().any(|operation| matches!(operation.get("type").and_then(serde_json::Value::as_str), Some(kind) if kind != "replace_text" && kind != "format_b_tags"))
        .then_some(PlanError::UnsupportedOperation)
}

fn valid_id(id: &str) -> bool {
    if id.is_empty() || id.len() > MAX_ID_LENGTH {
        return false;
    }
    let mut bytes = id.bytes();
    match bytes.next() {
        Some(first) if first.is_ascii_alphabetic() => {}
        _ => return false,
    }
    bytes.all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
}

fn validate_text(text: &str, empty_allowed: bool) -> Result<(), PlanError> {
    if text.is_empty() && !empty_allowed {
        return Err(PlanError::InvalidText);
    }
    if text.len() > MAX_TEXT_BYTES {
        return Err(PlanError::TextTooLarge);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const VALID: &[u8] = br#"{
      "schema_version": 1,
      "operations": [{
        "id": "replace_customer",
        "type": "replace_text",
        "locations": ["body"],
        "search": "{{customer_name}}",
        "replacement": "Alice",
        "match_case": true
      }]
    }"#;

    #[test]
    fn accepts_the_prototype_operation() {
        let plan = validate_plan_json(VALID).unwrap();
        assert_eq!(plan.operations[0], Operation::ReplaceText(ReplaceTextOperation { id: "replace_customer".into(), search: "{{customer_name}}".into(), replacement: "Alice".into() }));
    }

    #[test]
    fn rejects_unsupported_contract_features() {
        for (input, expected) in [
            (br#"{"schema_version":2,"operations":[]}"#.as_slice(), PlanError::UnsupportedSchema),
            (br#"{"schema_version":1,"operations":[]}"#.as_slice(), PlanError::InvalidOperations),
            (br#"{"schema_version":1,"operations":[{"id":"a","type":"regex_replace","locations":["body"],"search":"a","replacement":"b","match_case":true}]}"#.as_slice(), PlanError::UnsupportedOperation),
            (br#"{"schema_version":1,"operations":[{"id":"a","type":"replace_text","locations":["tables"],"search":"a","replacement":"b","match_case":true}]}"#.as_slice(), PlanError::UnsupportedLocation),
        ] {
            assert_eq!(validate_plan_json(input).unwrap_err(), expected);
        }
    }

    #[test]
    fn enforces_text_and_plan_limits() {
        let replacement = "x".repeat(MAX_TEXT_BYTES + 1);
        let input = format!("{{\"schema_version\":1,\"operations\":[{{\"id\":\"a\",\"type\":\"replace_text\",\"locations\":[\"body\"],\"search\":\"a\",\"replacement\":\"{replacement}\",\"match_case\":true}}]}}");
        assert_eq!(validate_plan_json(input.as_bytes()).unwrap_err(), PlanError::TextTooLarge);
        assert_eq!(validate_plan_json(&vec![b' '; MAX_PLAN_BYTES + 1]).unwrap_err(), PlanError::PlanTooLarge);
    }

    #[test]
    fn accepts_only_the_exact_b_tag_format() {
        let valid = br#"{"schema_version":1,"operations":[{"id":"format","type":"format_b_tags","locations":["body"],"open_tag":"<B>","close_tag":"<D>","bold":true}]}"#;
        assert!(matches!(validate_plan_json(valid).unwrap().operations[0], Operation::FormatBTags(_)));
        let invalid = br#"{"schema_version":1,"operations":[{"id":"format","type":"format_b_tags","locations":["body"],"open_tag":"<strong>","close_tag":"</strong>","bold":true}]}"#;
        assert_eq!(validate_plan_json(invalid).unwrap_err(), PlanError::UnsupportedFormat);
    }
}
