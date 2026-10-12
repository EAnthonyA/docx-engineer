use std::collections::HashSet;

use regex::{Regex, RegexBuilder};
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
    #[serde(rename = "format_text")]
    FormatText {
        id: String,
        locations: Vec<String>,
        search: String,
        match_case: bool,
        format: RawTextFormat,
    },
    #[serde(rename = "delete_paragraphs")]
    DeleteParagraphs {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
    },
    #[serde(rename = "regex_replace")]
    RegexReplace {
        id: String,
        locations: Vec<String>,
        pattern: String,
        replacement: String,
        case_insensitive: bool,
    },
    #[serde(rename = "format_tagged")]
    FormatTagged {
        id: String,
        locations: Vec<String>,
        open_tag: String,
        close_tag: String,
        format: RawTextFormat,
    },
    #[serde(rename = "set_paragraph_style")]
    SetParagraphStyle {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
        style_id: String,
    },
    #[serde(rename = "format_paragraphs")]
    FormatParagraphs {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
        format: RawTextFormat,
    },
    #[serde(rename = "set_paragraph_layout")]
    SetParagraphLayout {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
        layout: RawParagraphLayout,
    },
    #[serde(rename = "set_paragraph_numbering")]
    SetParagraphNumbering {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
        num_id: u32,
        level: u8,
    },
    #[serde(rename = "set_paragraph_pagination")]
    SetParagraphPagination {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
        pagination: RawParagraphPagination,
    },
    #[serde(rename = "delete_table_rows")]
    DeleteTableRows {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
    },
    #[serde(rename = "set_table_cell_format")]
    SetTableCellFormat {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
        format: RawTableCellFormat,
    },
    #[serde(rename = "insert_table_rows")]
    InsertTableRows {
        id: String,
        locations: Vec<String>,
        anchor: RawParagraphMatch,
        position: String,
        rows: Vec<RawInsertedTableRow>,
    },
    #[serde(rename = "set_table_row_height")]
    SetTableRowHeight {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
        height_pt: f64,
        rule: String,
    },
    #[serde(rename = "merge_table_cells")]
    MergeTableCells {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
        direction: String,
        span: u8,
    },
    #[serde(rename = "set_table_column_width")]
    SetTableColumnWidth {
        id: String,
        locations: Vec<String>,
        r#match: RawParagraphMatch,
        column_index: u8,
        width_pt: f64,
    },
    #[serde(rename = "insert_paragraphs")]
    InsertParagraphs {
        id: String,
        locations: Vec<String>,
        anchor: RawParagraphMatch,
        position: String,
        paragraphs: Vec<RawInsertedParagraph>,
    },
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawTextFormat {
    bold: Option<bool>,
    italic: Option<bool>,
    underline: Option<bool>,
    strike: Option<bool>,
    color: Option<String>,
    highlight: Option<String>,
    font_name: Option<String>,
    size_pt: Option<f64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawParagraphMatch {
    mode: String,
    text: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawInsertedParagraph {
    text: String,
    style_id: Option<String>,
    format: Option<RawTextFormat>,
    page_break_before: Option<bool>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawParagraphLayout {
    alignment: Option<String>,
    space_before_pt: Option<f64>,
    space_after_pt: Option<f64>,
    left_indent_pt: Option<f64>,
    right_indent_pt: Option<f64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawParagraphPagination {
    keep_with_next: Option<bool>,
    keep_together: Option<bool>,
    page_break_before: Option<bool>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawTableCellFormat {
    fill_color: Option<String>,
    vertical_alignment: Option<String>,
    border_color: Option<String>,
    border_size_pt: Option<f64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawInsertedTableRow { cells: Vec<String> }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Location {
    Body,
    Tables,
    HeadersFooters,
    All,
}

#[derive(Debug, PartialEq, Eq)]
pub struct ReplaceTextOperation {
    pub id: String,
    pub location: Location,
    pub search: String,
    pub replacement: String,
}

#[derive(Debug, PartialEq, Eq)]
pub struct FormatBTagsOperation {
    pub id: String,
    pub location: Location,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TextFormat {
    pub bold: Option<bool>,
    pub italic: Option<bool>,
    pub underline: Option<bool>,
    pub strike: Option<bool>,
    pub color: Option<String>,
    pub highlight: Option<String>,
    pub font_name: Option<String>,
    pub size_half_points: Option<u16>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct FormatTextOperation {
    pub id: String,
    pub location: Location,
    pub search: String,
    pub format: TextFormat,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ParagraphMatch {
    Exact(String),
    StartsWith(String),
    Contains(String),
}

#[derive(Debug, PartialEq, Eq)]
pub struct DeleteParagraphsOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
}

#[derive(Debug)]
pub struct RegexReplaceOperation {
    pub id: String,
    pub location: Location,
    pub pattern: String,
    pub replacement: String,
    pub regex: Regex,
}

#[derive(Debug, PartialEq, Eq)]
pub struct FormatTaggedOperation {
    pub id: String,
    pub location: Location,
    pub open_tag: String,
    pub close_tag: String,
    pub format: TextFormat,
}

#[derive(Debug, PartialEq, Eq)]
pub struct SetParagraphStyleOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
    pub style_id: String,
}

#[derive(Debug, PartialEq, Eq)]
pub struct FormatParagraphsOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
    pub format: TextFormat,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParagraphLayout {
    pub alignment: Option<String>,
    pub space_before_twips: Option<u16>,
    pub space_after_twips: Option<u16>,
    pub left_indent_twips: Option<u16>,
    pub right_indent_twips: Option<u16>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct SetParagraphLayoutOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
    pub layout: ParagraphLayout,
}

#[derive(Debug, PartialEq, Eq)]
pub struct SetParagraphNumberingOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
    pub num_id: u32,
    pub level: u8,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParagraphPagination {
    pub keep_with_next: Option<bool>,
    pub keep_together: Option<bool>,
    pub page_break_before: Option<bool>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct SetParagraphPaginationOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
    pub pagination: ParagraphPagination,
}

#[derive(Debug, PartialEq, Eq)]
pub struct DeleteTableRowsOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TableCellFormat {
    pub fill_color: Option<String>,
    pub vertical_alignment: Option<String>,
    pub border_color: Option<String>,
    pub border_eighth_points: Option<u16>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct SetTableCellFormatOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
    pub format: TableCellFormat,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TableRowInsertPosition { Before, After }

#[derive(Debug, PartialEq, Eq)]
pub struct InsertTableRowsOperation {
    pub id: String,
    pub location: Location,
    pub anchor: ParagraphMatch,
    pub position: TableRowInsertPosition,
    pub rows: Vec<Vec<String>>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TableRowHeightRule { AtLeast, Exact }

#[derive(Debug, PartialEq, Eq)]
pub struct SetTableRowHeightOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
    pub height_twips: u16,
    pub rule: TableRowHeightRule,
}

#[derive(Debug, PartialEq, Eq)]
pub struct MergeTableCellsOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
    pub span: u8,
    pub direction: TableCellMergeDirection,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TableCellMergeDirection { Right, Down }

#[derive(Debug, PartialEq, Eq)]
pub struct SetTableColumnWidthOperation {
    pub id: String,
    pub location: Location,
    pub matcher: ParagraphMatch,
    pub column_index: u8,
    pub width_twips: u16,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InsertedParagraph {
    pub text: String,
    pub style_id: Option<String>,
    pub format: Option<TextFormat>,
    pub page_break_before: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InsertPosition { Before, After }

#[derive(Debug, PartialEq, Eq)]
pub struct InsertParagraphsOperation {
    pub id: String,
    pub location: Location,
    pub anchor: ParagraphMatch,
    pub position: InsertPosition,
    pub paragraphs: Vec<InsertedParagraph>,
}

impl PartialEq for RegexReplaceOperation {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id && self.location == other.location && self.pattern == other.pattern && self.replacement == other.replacement
    }
}

impl Eq for RegexReplaceOperation {}

#[derive(Debug, PartialEq, Eq)]
pub enum Operation {
    ReplaceText(ReplaceTextOperation),
    FormatBTags(FormatBTagsOperation),
    FormatText(FormatTextOperation),
    DeleteParagraphs(DeleteParagraphsOperation),
    RegexReplace(RegexReplaceOperation),
    FormatTagged(FormatTaggedOperation),
    SetParagraphStyle(SetParagraphStyleOperation),
    FormatParagraphs(FormatParagraphsOperation),
    SetParagraphLayout(SetParagraphLayoutOperation),
    SetParagraphNumbering(SetParagraphNumberingOperation),
    SetParagraphPagination(SetParagraphPaginationOperation),
    DeleteTableRows(DeleteTableRowsOperation),
    SetTableCellFormat(SetTableCellFormatOperation),
    InsertTableRows(InsertTableRowsOperation),
    SetTableRowHeight(SetTableRowHeightOperation),
    MergeTableCells(MergeTableCellsOperation),
    SetTableColumnWidth(SetTableColumnWidthOperation),
    InsertParagraphs(InsertParagraphsOperation),
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
            RawOperation::ReplaceText { id, .. } | RawOperation::FormatBTags { id, .. } | RawOperation::FormatText { id, .. } | RawOperation::DeleteParagraphs { id, .. } | RawOperation::RegexReplace { id, .. } | RawOperation::FormatTagged { id, .. } | RawOperation::SetParagraphStyle { id, .. } | RawOperation::FormatParagraphs { id, .. } | RawOperation::SetParagraphLayout { id, .. } | RawOperation::SetParagraphNumbering { id, .. } | RawOperation::SetParagraphPagination { id, .. } | RawOperation::DeleteTableRows { id, .. } | RawOperation::SetTableCellFormat { id, .. } | RawOperation::InsertTableRows { id, .. } | RawOperation::SetTableRowHeight { id, .. } | RawOperation::MergeTableCells { id, .. } | RawOperation::SetTableColumnWidth { id, .. } | RawOperation::InsertParagraphs { id, .. } => id,
        };
        if !valid_id(id) {
            return Err(PlanError::InvalidOperationId);
        }
        if !ids.insert(id.clone()) {
            return Err(PlanError::DuplicateOperationId);
        }
        match operation {
            RawOperation::ReplaceText { id, locations, search, replacement, match_case } => {
                let location = one_location(&locations)?;
                if !match_case { return Err(PlanError::UnsupportedMatchMode); }
                validate_text(&search, false)?;
                validate_text(&replacement, true)?;
                operations.push(Operation::ReplaceText(ReplaceTextOperation { id, location, search, replacement }));
            }
            RawOperation::FormatBTags { id, locations, open_tag, close_tag, bold } => {
                let location = one_location(&locations)?;
                if open_tag != "<B>" || close_tag != "<D>" || !bold { return Err(PlanError::UnsupportedFormat); }
                operations.push(Operation::FormatBTags(FormatBTagsOperation { id, location }));
            }
            RawOperation::FormatText { id, locations, search, match_case, format } => {
                let location = one_location(&locations)?;
                if !match_case { return Err(PlanError::UnsupportedMatchMode); }
                validate_text(&search, false)?;
                operations.push(Operation::FormatText(FormatTextOperation {
                    id, location, search, format: validate_text_format(format)?,
                }));
            }
            RawOperation::DeleteParagraphs { id, locations, r#match } => {
                let location = one_location(&locations)?;
                if location != Location::Body { return Err(PlanError::UnsupportedLocation); }
                operations.push(Operation::DeleteParagraphs(DeleteParagraphsOperation {
                    id, location, matcher: validate_paragraph_match(r#match)?,
                }));
            }
            RawOperation::RegexReplace { id, locations, pattern, replacement, case_insensitive } => {
                let location = one_location(&locations)?;
                validate_text(&pattern, false)?;
                validate_text(&replacement, true)?;
                let regex = RegexBuilder::new(&pattern)
                    .case_insensitive(case_insensitive)
                    .size_limit(1 << 20)
                    .dfa_size_limit(1 << 20)
                    .build()
                    .map_err(|_| PlanError::UnsupportedMatchMode)?;
                operations.push(Operation::RegexReplace(RegexReplaceOperation { id, location, pattern, replacement, regex }));
            }
            RawOperation::FormatTagged { id, locations, open_tag, close_tag, format } => {
                let location = one_location(&locations)?;
                validate_text(&open_tag, false)?;
                validate_text(&close_tag, false)?;
                if open_tag == close_tag { return Err(PlanError::UnsupportedFormat); }
                operations.push(Operation::FormatTagged(FormatTaggedOperation {
                    id, location, open_tag, close_tag, format: validate_text_format(format)?,
                }));
            }
            RawOperation::SetParagraphStyle { id, locations, r#match, style_id } => {
                let location = one_location(&locations)?;
                if !valid_id(&style_id) { return Err(PlanError::UnsupportedFormat); }
                operations.push(Operation::SetParagraphStyle(SetParagraphStyleOperation {
                    id, location, matcher: validate_paragraph_match(r#match)?, style_id,
                }));
            }
            RawOperation::FormatParagraphs { id, locations, r#match, format } => {
                let location = one_location(&locations)?;
                operations.push(Operation::FormatParagraphs(FormatParagraphsOperation {
                    id, location, matcher: validate_paragraph_match(r#match)?, format: validate_text_format(format)?,
                }));
            }
            RawOperation::SetParagraphLayout { id, locations, r#match, layout } => {
                let location = one_location(&locations)?;
                operations.push(Operation::SetParagraphLayout(SetParagraphLayoutOperation {
                    id, location, matcher: validate_paragraph_match(r#match)?, layout: validate_paragraph_layout(layout)?,
                }));
            }
            RawOperation::SetParagraphNumbering { id, locations, r#match, num_id, level } => {
                let location = one_location(&locations)?;
                if level > 8 { return Err(PlanError::UnsupportedFormat); }
                operations.push(Operation::SetParagraphNumbering(SetParagraphNumberingOperation {
                    id, location, matcher: validate_paragraph_match(r#match)?, num_id, level,
                }));
            }
            RawOperation::SetParagraphPagination { id, locations, r#match, pagination } => {
                let location = one_location(&locations)?;
                operations.push(Operation::SetParagraphPagination(SetParagraphPaginationOperation {
                    id, location, matcher: validate_paragraph_match(r#match)?, pagination: validate_paragraph_pagination(pagination)?,
                }));
            }
            RawOperation::DeleteTableRows { id, locations, r#match } => {
                let location = one_location(&locations)?;
                if location != Location::Tables { return Err(PlanError::UnsupportedLocation); }
                operations.push(Operation::DeleteTableRows(DeleteTableRowsOperation {
                    id, location, matcher: validate_paragraph_match(r#match)?,
                }));
            }
            RawOperation::SetTableCellFormat { id, locations, r#match, format } => {
                let location = one_location(&locations)?;
                if location != Location::Tables { return Err(PlanError::UnsupportedLocation); }
                operations.push(Operation::SetTableCellFormat(SetTableCellFormatOperation {
                    id, location, matcher: validate_paragraph_match(r#match)?, format: validate_table_cell_format(format)?,
                }));
            }
            RawOperation::InsertTableRows { id, locations, anchor, position, rows } => {
                let location = one_location(&locations)?;
                if location != Location::Tables { return Err(PlanError::UnsupportedLocation); }
                let position = match position.as_str() { "before" => TableRowInsertPosition::Before, "after" => TableRowInsertPosition::After, _ => return Err(PlanError::UnsupportedFormat) };
                if rows.is_empty() || rows.len() > MAX_OPERATIONS { return Err(PlanError::InvalidOperations); }
                let mut validated_rows = Vec::with_capacity(rows.len());
                for row in rows {
                    if row.cells.is_empty() || row.cells.len() > 64 { return Err(PlanError::InvalidOperations); }
                    for cell in &row.cells { validate_text(cell, true)?; if cell.contains(['\r', '\n']) { return Err(PlanError::UnsupportedFormat); } }
                    validated_rows.push(row.cells);
                }
                operations.push(Operation::InsertTableRows(InsertTableRowsOperation { id, location, anchor: validate_paragraph_match(anchor)?, position, rows: validated_rows }));
            }
            RawOperation::SetTableRowHeight { id, locations, r#match, height_pt, rule } => {
                let location = one_location(&locations)?;
                if location != Location::Tables { return Err(PlanError::UnsupportedLocation); }
                let height_twips = match height_pt {
                    value if value.is_finite() && value >= 0.5 && value <= 1584.0 && (value * 2.0).fract() == 0.0 => (value * 20.0) as u16,
                    _ => return Err(PlanError::UnsupportedFormat),
                };
                let rule = match rule.as_str() {
                    "at_least" => TableRowHeightRule::AtLeast,
                    "exact" => TableRowHeightRule::Exact,
                    _ => return Err(PlanError::UnsupportedFormat),
                };
                operations.push(Operation::SetTableRowHeight(SetTableRowHeightOperation { id, location, matcher: validate_paragraph_match(r#match)?, height_twips, rule }));
            }
            RawOperation::MergeTableCells { id, locations, r#match, direction, span } => {
                let location = one_location(&locations)?;
                if location != Location::Tables { return Err(PlanError::UnsupportedLocation); }
                let direction = match direction.as_str() { "right" => TableCellMergeDirection::Right, "down" => TableCellMergeDirection::Down, _ => return Err(PlanError::UnsupportedFormat) };
                if !(2..=64).contains(&span) { return Err(PlanError::UnsupportedFormat); }
                operations.push(Operation::MergeTableCells(MergeTableCellsOperation { id, location, matcher: validate_paragraph_match(r#match)?, span, direction }));
            }
            RawOperation::SetTableColumnWidth { id, locations, r#match, column_index, width_pt } => {
                let location = one_location(&locations)?;
                if location != Location::Tables { return Err(PlanError::UnsupportedLocation); }
                let width_twips = match width_pt { value if value.is_finite() && value >= 0.5 && value <= 1584.0 && (value * 2.0).fract() == 0.0 => (value * 20.0) as u16, _ => return Err(PlanError::UnsupportedFormat) };
                operations.push(Operation::SetTableColumnWidth(SetTableColumnWidthOperation { id, location, matcher: validate_paragraph_match(r#match)?, column_index, width_twips }));
            }
            RawOperation::InsertParagraphs { id, locations, anchor, position, paragraphs } => {
                let location = one_location(&locations)?;
                if !matches!(location, Location::Body | Location::HeadersFooters) { return Err(PlanError::UnsupportedLocation); }
                let position = match position.as_str() {
                    "before" => InsertPosition::Before,
                    "after" => InsertPosition::After,
                    _ => return Err(PlanError::UnsupportedFormat),
                };
                if paragraphs.is_empty() || paragraphs.len() > MAX_OPERATIONS {
                    return Err(PlanError::InvalidOperations);
                }
                let mut inserted = Vec::with_capacity(paragraphs.len());
                for paragraph in paragraphs {
                    validate_text(&paragraph.text, true)?;
                    if paragraph.text.contains(['\r', '\n']) { return Err(PlanError::UnsupportedFormat); }
                    if let Some(style_id) = &paragraph.style_id {
                        if !valid_id(style_id) { return Err(PlanError::UnsupportedFormat); }
                    }
                    let format = paragraph.format.map(validate_text_format).transpose()?;
                    inserted.push(InsertedParagraph {
                        text: paragraph.text, style_id: paragraph.style_id, format,
                        page_break_before: paragraph.page_break_before.unwrap_or(false),
                    });
                }
                operations.push(Operation::InsertParagraphs(InsertParagraphsOperation {
                    id, location, anchor: validate_paragraph_match(anchor)?, position, paragraphs: inserted,
                }));
            }
        }
    }
    if operations.iter().any(|operation| matches!(operation, Operation::FormatBTags(_) | Operation::FormatText(_) | Operation::FormatTagged(_) | Operation::DeleteParagraphs(_) | Operation::SetParagraphStyle(_) | Operation::FormatParagraphs(_) | Operation::SetParagraphLayout(_) | Operation::SetParagraphNumbering(_) | Operation::SetParagraphPagination(_) | Operation::DeleteTableRows(_) | Operation::SetTableCellFormat(_) | Operation::InsertTableRows(_) | Operation::SetTableRowHeight(_) | Operation::MergeTableCells(_) | Operation::SetTableColumnWidth(_) | Operation::InsertParagraphs(_))) && operations.len() != 1 {
        return Err(PlanError::UnsupportedOperationCombination);
    }
    Ok(EditPlan { operations })
}

fn validate_paragraph_match(raw: RawParagraphMatch) -> Result<ParagraphMatch, PlanError> {
    validate_text(&raw.text, false)?;
    match raw.mode.as_str() {
        "exact" => Ok(ParagraphMatch::Exact(raw.text)),
        "starts_with" => Ok(ParagraphMatch::StartsWith(raw.text)),
        "contains" => Ok(ParagraphMatch::Contains(raw.text)),
        _ => Err(PlanError::UnsupportedMatchMode),
    }
}

fn validate_text_format(format: RawTextFormat) -> Result<TextFormat, PlanError> {
    let size_half_points = match format.size_pt {
        Some(size) if size.is_finite() && size >= 0.5 && size <= 1638.0 && (size * 2.0).fract() == 0.0 => Some((size * 2.0) as u16),
        Some(_) => return Err(PlanError::UnsupportedFormat),
        None => None,
    };
    if let Some(color) = &format.color {
        if color.len() != 6 || !color.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(PlanError::UnsupportedFormat);
        }
    }
    if let Some(highlight) = &format.highlight {
        if !matches!(highlight.as_str(),
            "black" | "blue" | "cyan" | "darkBlue" | "darkCyan" | "darkGray" | "darkGreen"
            | "darkMagenta" | "darkRed" | "darkYellow" | "green" | "lightGray" | "magenta"
            | "none" | "red" | "white" | "yellow"
        ) {
            return Err(PlanError::UnsupportedFormat);
        }
    }
    if let Some(font_name) = &format.font_name {
        if font_name.is_empty() || font_name.len() > MAX_ID_LENGTH || font_name.chars().any(|character| character <= '\u{1f}' || character == '\u{7f}') {
            return Err(PlanError::UnsupportedFormat);
        }
    }
    if format.bold.is_none() && format.italic.is_none() && format.underline.is_none() && format.strike.is_none()
        && format.color.is_none() && format.highlight.is_none() && format.font_name.is_none() && size_half_points.is_none() {
        return Err(PlanError::UnsupportedFormat);
    }
    Ok(TextFormat {
        bold: format.bold, italic: format.italic, underline: format.underline, strike: format.strike,
        color: format.color, highlight: format.highlight, font_name: format.font_name, size_half_points,
    })
}

fn validate_paragraph_layout(layout: RawParagraphLayout) -> Result<ParagraphLayout, PlanError> {
    let alignment = match layout.alignment {
        Some(value) => match value.as_str() {
            "left" => Some("left".to_string()),
            "center" => Some("center".to_string()),
            "right" => Some("right".to_string()),
            "justify" => Some("both".to_string()),
            _ => return Err(PlanError::UnsupportedFormat),
        },
        None => None,
    };
    let to_twips = |value: Option<f64>| match value {
        Some(value) if value.is_finite() && value >= 0.0 && value <= 1584.0 && (value * 2.0).fract() == 0.0 => Ok(Some((value * 20.0) as u16)),
        Some(_) => Err(PlanError::UnsupportedFormat),
        None => Ok(None),
    };
    let space_before_twips = to_twips(layout.space_before_pt)?;
    let space_after_twips = to_twips(layout.space_after_pt)?;
    let left_indent_twips = to_twips(layout.left_indent_pt)?;
    let right_indent_twips = to_twips(layout.right_indent_pt)?;
    if alignment.is_none() && space_before_twips.is_none() && space_after_twips.is_none()
        && left_indent_twips.is_none() && right_indent_twips.is_none() {
        return Err(PlanError::UnsupportedFormat);
    }
    Ok(ParagraphLayout {
        alignment, space_before_twips, space_after_twips, left_indent_twips, right_indent_twips,
    })
}

fn validate_paragraph_pagination(pagination: RawParagraphPagination) -> Result<ParagraphPagination, PlanError> {
    if pagination.keep_with_next.is_none() && pagination.keep_together.is_none() && pagination.page_break_before.is_none() {
        return Err(PlanError::UnsupportedFormat);
    }
    Ok(ParagraphPagination {
        keep_with_next: pagination.keep_with_next,
        keep_together: pagination.keep_together,
        page_break_before: pagination.page_break_before,
    })
}

fn validate_table_cell_format(format: RawTableCellFormat) -> Result<TableCellFormat, PlanError> {
    if let Some(fill_color) = &format.fill_color {
        if fill_color.len() != 6 || !fill_color.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(PlanError::UnsupportedFormat);
        }
    }
    if let Some(vertical_alignment) = &format.vertical_alignment {
        if !matches!(vertical_alignment.as_str(), "top" | "center" | "bottom") {
            return Err(PlanError::UnsupportedFormat);
        }
    }
    let border_eighth_points = match format.border_size_pt {
        Some(size) if size.is_finite() && size >= 0.125 && size <= 31.75 && (size * 8.0).fract() == 0.0 => Some((size * 8.0) as u16),
        Some(_) => return Err(PlanError::UnsupportedFormat), None => None,
    };
    if format.border_color.is_some() != border_eighth_points.is_some() { return Err(PlanError::UnsupportedFormat); }
    if let Some(color) = &format.border_color {
        if color.len() != 6 || !color.bytes().all(|byte| byte.is_ascii_hexdigit()) { return Err(PlanError::UnsupportedFormat); }
    }
    if format.fill_color.is_none() && format.vertical_alignment.is_none() && format.border_color.is_none() {
        return Err(PlanError::UnsupportedFormat);
    }
    Ok(TableCellFormat { fill_color: format.fill_color, vertical_alignment: format.vertical_alignment, border_color: format.border_color, border_eighth_points })
}

fn one_location(locations: &[String]) -> Result<Location, PlanError> {
    match locations {
        [location] => match location.as_str() {
            "body" => Ok(Location::Body),
            "tables" => Ok(Location::Tables),
            "headers_footers" => Ok(Location::HeadersFooters),
            "all" => Ok(Location::All),
            _ => Err(PlanError::UnsupportedLocation),
        },
        _ => Err(PlanError::UnsupportedLocation),
    }
}

fn unsupported_operation(bytes: &[u8]) -> Option<PlanError> {
    let value: serde_json::Value = serde_json::from_slice(bytes).ok()?;
    let operations = value.get("operations")?.as_array()?;
    operations.iter().any(|operation| matches!(operation.get("type").and_then(serde_json::Value::as_str), Some(kind) if kind != "replace_text" && kind != "format_b_tags" && kind != "format_text" && kind != "delete_paragraphs" && kind != "regex_replace" && kind != "format_tagged" && kind != "set_paragraph_style" && kind != "format_paragraphs" && kind != "set_paragraph_layout" && kind != "set_paragraph_numbering" && kind != "set_paragraph_pagination" && kind != "delete_table_rows" && kind != "set_table_cell_format" && kind != "insert_table_rows" && kind != "set_table_row_height" && kind != "merge_table_cells" && kind != "set_table_column_width" && kind != "insert_paragraphs"))
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
        assert_eq!(plan.operations[0], Operation::ReplaceText(ReplaceTextOperation { id: "replace_customer".into(), location: Location::Body, search: "{{customer_name}}".into(), replacement: "Alice".into() }));
    }

    #[test]
    fn rejects_unsupported_contract_features() {
        for (input, expected) in [
            (br#"{"schema_version":2,"operations":[]}"#.as_slice(), PlanError::UnsupportedSchema),
            (br#"{"schema_version":1,"operations":[]}"#.as_slice(), PlanError::InvalidOperations),
            (br#"{"schema_version":1,"operations":[{"id":"a","type":"regex_replace","locations":["body"],"search":"a","replacement":"b","match_case":true}]}"#.as_slice(), PlanError::InvalidJson),
            (br#"{"schema_version":1,"operations":[{"id":"a","type":"replace_text","locations":[],"search":"a","replacement":"b","match_case":true}]}"#.as_slice(), PlanError::UnsupportedLocation),
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

    #[test]
    fn accepts_each_supported_location() {
        for location in ["body", "tables", "headers_footers", "all"] {
            let plan = format!("{{\"schema_version\":1,\"operations\":[{{\"id\":\"a\",\"type\":\"replace_text\",\"locations\":[\"{location}\"],\"search\":\"a\",\"replacement\":\"b\",\"match_case\":true}}]}}");
            assert!(validate_plan_json(plan.as_bytes()).is_ok(), "{location}");
        }
    }

    #[test]
    fn accepts_bounded_extended_text_formatting() {
        let plan = br#"{"schema_version":1,"operations":[{"id":"format","type":"format_text","locations":["body"],"search":"Total","match_case":true,"format":{"strike":true,"highlight":"yellow","font_name":"Aptos"}}]}"#;
        let plan = validate_plan_json(plan).unwrap();
        let Operation::FormatText(operation) = &plan.operations[0] else { panic!("unexpected operation"); };
        assert_eq!(operation.format.strike, Some(true));
        assert_eq!(operation.format.highlight.as_deref(), Some("yellow"));
        assert_eq!(operation.format.font_name.as_deref(), Some("Aptos"));

        let invalid_highlight = br#"{"schema_version":1,"operations":[{"id":"format","type":"format_text","locations":["body"],"search":"Total","match_case":true,"format":{"highlight":"orange"}}]}"#;
        assert_eq!(validate_plan_json(invalid_highlight).unwrap_err(), PlanError::UnsupportedFormat);
    }

    #[test]
    fn accepts_paragraph_layout_and_rich_insertions() {
        let layout = br#"{"schema_version":1,"operations":[{"id":"layout","type":"set_paragraph_layout","locations":["all"],"match":{"mode":"exact","text":"Title"},"layout":{"alignment":"justify","space_after_pt":12.5,"left_indent_pt":18}}]}"#;
        let plan = validate_plan_json(layout).unwrap();
        let Operation::SetParagraphLayout(operation) = &plan.operations[0] else { panic!("unexpected operation"); };
        assert_eq!(operation.layout.alignment.as_deref(), Some("both"));
        assert_eq!(operation.layout.space_after_twips, Some(250));
        assert_eq!(operation.layout.left_indent_twips, Some(360));

        let insert = br#"{"schema_version":1,"operations":[{"id":"insert","type":"insert_paragraphs","locations":["body"],"anchor":{"mode":"exact","text":"Title"},"position":"after","paragraphs":[{"text":"New page","page_break_before":true,"format":{"bold":true}}]}]}"#;
        let plan = validate_plan_json(insert).unwrap();
        let Operation::InsertParagraphs(operation) = &plan.operations[0] else { panic!("unexpected operation"); };
        assert!(operation.paragraphs[0].page_break_before);
        assert_eq!(operation.paragraphs[0].format.as_ref().unwrap().bold, Some(true));
    }

    #[test]
    fn accepts_existing_numbering_and_pagination_settings() {
        let numbering = br#"{"schema_version":1,"operations":[{"id":"numbers","type":"set_paragraph_numbering","locations":["all"],"match":{"mode":"starts_with","text":"Step"},"num_id":5,"level":2}]}"#;
        let plan = validate_plan_json(numbering).unwrap();
        let Operation::SetParagraphNumbering(operation) = &plan.operations[0] else { panic!("unexpected operation"); };
        assert_eq!((operation.num_id, operation.level), (5, 2));

        let pagination = br#"{"schema_version":1,"operations":[{"id":"keep","type":"set_paragraph_pagination","locations":["body"],"match":{"mode":"exact","text":"Title"},"pagination":{"keep_with_next":true,"page_break_before":false}}]}"#;
        let plan = validate_plan_json(pagination).unwrap();
        let Operation::SetParagraphPagination(operation) = &plan.operations[0] else { panic!("unexpected operation"); };
        assert_eq!(operation.pagination.keep_with_next, Some(true));
        assert_eq!(operation.pagination.page_break_before, Some(false));
    }

    #[test]
    fn accepts_table_row_deletion_only_for_table_locations() {
        let valid = br#"{"schema_version":1,"operations":[{"id":"delete_row","type":"delete_table_rows","locations":["tables"],"match":{"mode":"contains","text":"DISCONTINUED"}}]}"#;
        assert!(matches!(validate_plan_json(valid).unwrap().operations[0], Operation::DeleteTableRows(_)));
        let invalid = br#"{"schema_version":1,"operations":[{"id":"delete_row","type":"delete_table_rows","locations":["body"],"match":{"mode":"contains","text":"DISCONTINUED"}}]}"#;
        assert_eq!(validate_plan_json(invalid).unwrap_err(), PlanError::UnsupportedLocation);
    }

    #[test]
    fn accepts_bounded_table_cell_formatting() {
        let valid = br#"{"schema_version":1,"operations":[{"id":"format_cell","type":"set_table_cell_format","locations":["tables"],"match":{"mode":"exact","text":"Total"},"format":{"fill_color":"FFF2CC","vertical_alignment":"center","border_color":"7F6000","border_size_pt":0.5}}]}"#;
        let plan = validate_plan_json(valid).unwrap();
        let Operation::SetTableCellFormat(operation) = &plan.operations[0] else { panic!("unexpected operation"); };
        assert_eq!(operation.format.fill_color.as_deref(), Some("FFF2CC"));
        assert_eq!(operation.format.vertical_alignment.as_deref(), Some("center"));
        assert_eq!(operation.format.border_eighth_points, Some(4));
    }

    #[test]
    fn accepts_table_row_insertion_height_and_horizontal_merging() {
        let insert = br#"{"schema_version":1,"operations":[{"id":"insert","type":"insert_table_rows","locations":["tables"],"anchor":{"mode":"exact","text":"Template"},"position":"after","rows":[{"cells":["A","B"]}]}]}"#;
        let plan = validate_plan_json(insert).unwrap();
        let Operation::InsertTableRows(operation) = &plan.operations[0] else { panic!("unexpected operation"); };
        assert_eq!(operation.rows, vec![vec!["A".to_string(), "B".to_string()]]);

        let height = br#"{"schema_version":1,"operations":[{"id":"height","type":"set_table_row_height","locations":["tables"],"match":{"mode":"contains","text":"Total"},"height_pt":24,"rule":"exact"}]}"#;
        let plan = validate_plan_json(height).unwrap();
        let Operation::SetTableRowHeight(operation) = &plan.operations[0] else { panic!("unexpected operation"); };
        assert_eq!(operation.height_twips, 480);
        assert_eq!(operation.rule, TableRowHeightRule::Exact);

        let merge = br#"{"schema_version":1,"operations":[{"id":"merge","type":"merge_table_cells","locations":["tables"],"match":{"mode":"exact","text":"Summary"},"direction":"right","span":2}]}"#;
        assert!(matches!(validate_plan_json(merge).unwrap().operations[0], Operation::MergeTableCells(_)));
    }

    #[test]
    fn accepts_header_footer_paragraph_insertion() {
        let plan = br#"{"schema_version":1,"operations":[{"id":"insert_header","type":"insert_paragraphs","locations":["headers_footers"],"anchor":{"mode":"exact","text":"Company"},"position":"after","paragraphs":[{"text":"Confidential"}]}]}"#;
        let plan = validate_plan_json(plan).unwrap();
        let Operation::InsertParagraphs(operation) = &plan.operations[0] else { panic!("unexpected operation"); };
        assert_eq!(operation.location, Location::HeadersFooters);
    }
}
