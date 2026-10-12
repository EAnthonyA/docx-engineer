use std::{error::Error, io::{BufRead, Write}};

use quick_xml::{events::{BytesText, Event}, escape::unescape, Reader, Writer};

use crate::plan::{EditPlan, InsertParagraphsOperation, InsertPosition, Location, Operation, ParagraphLayout, ParagraphMatch, ParagraphPagination, TextFormat};

const PARAGRAPH: &[u8] = b"w:p";
const TABLE: &[u8] = b"w:tbl";
const TABLE_ROW: &[u8] = b"w:tr";
const TABLE_ROW_PROPERTIES: &[u8] = b"w:trPr";
const TABLE_CELL: &[u8] = b"w:tc";
const TABLE_CELL_PROPERTIES: &[u8] = b"w:tcPr";
const TEXT: &[u8] = b"w:t";
const PARAGRAPH_PROPERTIES: &[u8] = b"w:pPr";
const PARAGRAPH_STYLE: &[u8] = b"w:pStyle";
const UNSUPPORTED: &[&[u8]] = &[
    b"w:hyperlink", b"w:fldChar", b"w:instrText", b"w:tab", b"w:br", b"w:cr", b"w:drawing",
    b"w:commentRangeStart", b"w:commentRangeEnd", b"w:ins", b"w:del",
];
const BOOKMARKS: &[&[u8]] = &[b"w:bookmarkStart", b"w:bookmarkEnd"];
const MAX_BUFFERED_TABLE_ROW_BYTES: usize = 8 * 1024 * 1024;
const MAX_BUFFERED_TABLE_BYTES: usize = 32 * 1024 * 1024;

#[derive(Default)]
pub struct TransformStats {
    pub matches: usize,
    pub modifications: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PartKind {
    MainDocument,
    HeaderFooter,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ParagraphLocation {
    Body,
    Tables,
    HeadersFooters,
}

struct Segment {
    event_index: usize,
    text: String,
    run_index: Option<usize>,
}

struct Run {
    start: usize,
    end: usize,
    text_start: Option<usize>,
    text_event: Option<usize>,
    text_end: Option<usize>,
    segment_index: Option<usize>,
}

struct Piece {
    text: String,
    format: Option<TextFormat>,
}

#[derive(Clone, Debug)]
struct TableCellRange {
    start: usize,
    end: usize,
    text: String,
}

pub fn transform_document<R: BufRead, W: Write>(input: R, mut output: W, plan: &EditPlan, part: PartKind) -> Result<TransformStats, Box<dyn Error>> {
    if plan.operations.iter().any(|operation| matches!(operation, Operation::SetTableColumnWidth(_)) || matches!(operation, Operation::MergeTableCells(operation) if operation.direction == crate::plan::TableCellMergeDirection::Down)) {
        return transform_document_table_wide(input, output, plan, part);
    }
    let mut reader = Reader::from_reader(input);
    reader.config_mut().trim_text(false);
    let mut writer = Writer::new(&mut output);
    let mut buffer = Vec::new();
    let mut paragraph = Vec::new();
    let mut paragraph_depth = 0usize;
    let mut table_depth = 0usize;
    let mut paragraph_location = ParagraphLocation::Body;
    let mut stats = TransformStats::default();
    let mut row = Vec::new();
    let mut buffering_table_row = false;

    loop {
        let event = reader.read_event_into(&mut buffer)?.into_owned();
        match &event {
            Event::Eof => break,
            Event::Start(start) if start.name().as_ref() == TABLE => {
                if paragraph_depth > 0 {
                    write_paragraph_event(&mut paragraph, event)?;
                    paragraph_depth += 1;
                } else {
                    table_depth += 1;
                    if buffering_table_row { write_paragraph_event(&mut row, event)?; } else { writer.write_event(event)?; }
                }
            }
            Event::End(end) if end.name().as_ref() == TABLE && paragraph_depth == 0 => {
                table_depth = table_depth.saturating_sub(1);
                if buffering_table_row { write_paragraph_event(&mut row, event)?; } else { writer.write_event(event)?; }
            }
            Event::Start(start) if start.name().as_ref() == TABLE_ROW && paragraph_depth == 0 => {
                if buffering_table_row { return Err("nested_table_rows_are_not_supported".into()); }
                row.clear();
                write_paragraph_event(&mut row, event)?;
                buffering_table_row = true;
            }
            Event::End(end) if end.name().as_ref() == TABLE_ROW && paragraph_depth == 0 && buffering_table_row => {
                write_paragraph_event(&mut row, event)?;
                buffering_table_row = false;
                if row.len() > MAX_BUFFERED_TABLE_ROW_BYTES { return Err("table_row_exceeds_buffer_limit".into()); }
                let formatted_cells = format_table_cells(&mut row, plan)?;
                stats.matches += formatted_cells;
                stats.modifications += formatted_cells;
                let resized_rows = set_table_row_height(&mut row, plan)?;
                stats.matches += resized_rows;
                stats.modifications += resized_rows;
                let merged_cells = merge_table_cells(&mut row, plan)?;
                stats.matches += merged_cells;
                stats.modifications += merged_cells;
                let insertion = table_row_insertion(&row, plan)?;
                if let Some((position, rows)) = &insertion {
                    let inserted = render_template_rows(&row, rows)?;
                    stats.matches += 1;
                    stats.modifications += rows.len();
                    if *position == crate::plan::TableRowInsertPosition::Before { writer.get_mut().write_all(&inserted)?; }
                }
                if table_row_matches(&row, plan)? {
                    stats.matches += 1;
                    stats.modifications += 1;
                } else {
                    writer.get_mut().write_all(&row)?;
                }
                if let Some((position, rows)) = insertion {
                    if position == crate::plan::TableRowInsertPosition::After { writer.get_mut().write_all(&render_template_rows(&row, &rows)?)?; }
                }
            }
            Event::Start(start) if start.name().as_ref() == PARAGRAPH && paragraph_depth == 0 => {
                paragraph.clear();
                write_paragraph_event(&mut paragraph, event)?;
                paragraph_depth = 1;
                paragraph_location = match part {
                    PartKind::HeaderFooter => ParagraphLocation::HeadersFooters,
                    PartKind::MainDocument if table_depth > 0 => ParagraphLocation::Tables,
                    PartKind::MainDocument => ParagraphLocation::Body,
                };
            }
            Event::Start(_) if paragraph_depth > 0 => {
                write_paragraph_event(&mut paragraph, event)?;
                paragraph_depth += 1;
            }
            Event::End(_) if paragraph_depth > 0 => {
                write_paragraph_event(&mut paragraph, event)?;
                paragraph_depth -= 1;
                if paragraph_depth == 0 {
                    let insertion = insertion_for_paragraph(&paragraph, plan, paragraph_location)?;
                    let (updated, paragraph_stats) = transform_paragraph(&paragraph, plan, paragraph_location)?;
                    stats.matches += paragraph_stats.matches;
                    stats.modifications += paragraph_stats.modifications;
                    if let Some(operation) = insertion {
                        let inserted = render_inserted_paragraphs(operation)?;
                        stats.matches += 1;
                        stats.modifications += operation.paragraphs.len();
                        if operation.position == InsertPosition::Before {
                            if buffering_table_row { row.write_all(&inserted)?; } else { writer.get_mut().write_all(&inserted)?; }
                        }
                    }
                    if !updated.is_empty() {
                        if buffering_table_row { row.write_all(&updated)?; } else { writer.get_mut().write_all(&updated)?; }
                    }
                    if let Some(operation) = insertion {
                        if operation.position == InsertPosition::After {
                            let inserted = render_inserted_paragraphs(operation)?;
                            if buffering_table_row { row.write_all(&inserted)?; } else { writer.get_mut().write_all(&inserted)?; }
                        }
                    }
                }
            }
            _ if paragraph_depth > 0 => write_paragraph_event(&mut paragraph, event)?,
            _ => if buffering_table_row { write_paragraph_event(&mut row, event)?; } else { writer.write_event(event)?; },
        }
        buffer.clear();
    }
    Ok(stats)
}

fn transform_document_table_wide<R: BufRead, W: Write>(input: R, mut output: W, plan: &EditPlan, _part: PartKind) -> Result<TransformStats, Box<dyn Error>> {
    let mut reader = Reader::from_reader(input); reader.config_mut().trim_text(false);
    let mut writer = Writer::new(&mut output); let mut buffer = Vec::new(); let mut table = Vec::new(); let mut depth = 0usize; let mut stats = TransformStats::default();
    loop {
        let event = reader.read_event_into(&mut buffer)?.into_owned();
        match &event {
            Event::Eof => break,
            Event::Start(start) if start.name().as_ref() == TABLE => { depth += 1; write_paragraph_event(&mut table, event)?; }
            Event::End(end) if end.name().as_ref() == TABLE && depth > 0 => {
                write_paragraph_event(&mut table, event)?; depth -= 1;
                if depth == 0 { if table.len() > MAX_BUFFERED_TABLE_BYTES { return Err("table_exceeds_buffer_limit".into()); } let (updated, changed) = set_table_grid_width(&table, plan)?; writer.get_mut().write_all(&updated)?; stats.matches += changed; stats.modifications += changed; table.clear(); }
            }
            _ if depth > 0 => { write_paragraph_event(&mut table, event)?; if table.len() > MAX_BUFFERED_TABLE_BYTES { return Err("table_exceeds_buffer_limit".into()); } }
            _ => writer.write_event(event)?,
        }
        buffer.clear();
    }
    Ok(stats)
}

fn set_table_grid_width(table: &[u8], plan: &EditPlan) -> Result<(Vec<u8>, usize), Box<dyn Error>> {
    if let Some(operation) = plan.operations.iter().find_map(|operation| match operation { Operation::MergeTableCells(operation) if operation.direction == crate::plan::TableCellMergeDirection::Down => Some(operation), _ => None }) {
        return merge_table_cells_down(table, operation);
    }
    let Some(operation) = plan.operations.iter().find_map(|operation| match operation { Operation::SetTableColumnWidth(operation) => Some(operation), _ => None }) else { return Ok((table.to_vec(), 0)); };
    let mut events = parse_xml_events(table)?;
    if !table_cell_ranges(&events)?.iter().any(|cell| paragraph_matches(&cell.text, &operation.matcher)) { return Ok((table.to_vec(), 0)); }
    let mut in_grid = false; let mut columns = 0usize;
    for event in &mut events {
        match event {
            Event::Start(start) if start.name().as_ref() == b"w:tblGrid" => in_grid = true,
            Event::End(end) if end.name().as_ref() == b"w:tblGrid" => in_grid = false,
            Event::Empty(column) if in_grid && column.name().as_ref() == b"w:gridCol" => {
                if columns == operation.column_index as usize { *event = merged_empty_element("w:gridCol", column, &[("w:w".to_string(), operation.width_twips.to_string())])?; return Ok((serialize_events(&events, table.len())?, 1)); }
                columns += 1;
            }
            _ => {}
        }
    }
    Err("table_column_index_exceeds_grid".into())
}

fn merge_table_cells_down(table: &[u8], operation: &crate::plan::MergeTableCellsOperation) -> Result<(Vec<u8>, usize), Box<dyn Error>> {
    let mut events = parse_xml_events(table)?;
    let rows = table_row_ranges(&events)?;
    let cells = table_cell_ranges(&events)?;
    let mut target = None;
    for (row_index, (row_start, row_end)) in rows.iter().enumerate() {
        let row_cells: Vec<_> = cells.iter().filter(|cell| cell.start > *row_start && cell.end < *row_end).collect();
        for (column, cell) in row_cells.iter().enumerate() {
            if paragraph_matches(&cell.text, &operation.matcher) {
                if target.is_some() { return Err("table_cell_merge_anchor_is_ambiguous".into()); }
                target = Some((row_index, column));
            }
        }
    }
    let Some((row_index, column)) = target else { return Ok((table.to_vec(), 0)); };
    let last = row_index + operation.span as usize;
    if last > rows.len() { return Err("table_cell_merge_span_exceeds_table".into()); }
    let mut targets = Vec::new();
    for (offset, (row_start, row_end)) in rows[row_index..last].iter().enumerate() {
        let row_cells: Vec<_> = cells.iter().filter(|cell| cell.start > *row_start && cell.end < *row_end).collect();
        let cell = row_cells.get(column).ok_or("table_cell_merge_column_missing")?;
        targets.push((cell.start, cell.end, offset == 0));
    }
    for (start, end, restart) in targets.into_iter().rev() {
        ensure_table_cell_properties(&mut events, start, end)?;
        let attributes = if restart { vec![("w:val".to_string(), "restart".to_string())] } else { Vec::new() };
        set_table_cell_property(&mut events, start, b"w:vMerge", &attributes)?;
    }
    Ok((serialize_events(&events, table.len())?, operation.span as usize))
}

fn table_row_ranges(events: &[Event<'static>]) -> Result<Vec<(usize, usize)>, Box<dyn Error>> {
    let mut rows = Vec::new(); let mut start = None;
    for (index, event) in events.iter().enumerate() { match event {
        Event::Start(element) if element.name().as_ref() == TABLE_ROW => { if start.is_some() { return Err("nested_table_rows_are_not_supported".into()); } start = Some(index); }
        Event::End(element) if element.name().as_ref() == TABLE_ROW => rows.push((start.take().ok_or("table_row_end_without_start")?, index)), _ => {}
    }}
    Ok(rows)
}

fn table_row_insertion(row: &[u8], plan: &EditPlan) -> Result<Option<(crate::plan::TableRowInsertPosition, Vec<Vec<String>>)>, Box<dyn Error>> {
    let Some(operation) = plan.operations.iter().find_map(|operation| match operation { Operation::InsertTableRows(operation) => Some(operation), _ => None }) else { return Ok(None); };
    let text = table_row_text(row)?;
    Ok(paragraph_matches(&text, &operation.anchor).then(|| (operation.position, operation.rows.clone())))
}

fn table_row_text(row: &[u8]) -> Result<String, Box<dyn Error>> {
    let mut reader = Reader::from_reader(row);
    reader.config_mut().trim_text(false);
    let mut buffer = Vec::new(); let mut depth = 0usize; let mut text = String::new();
    loop { let event = reader.read_event_into(&mut buffer)?; match event {
        Event::Eof => break, Event::Start(start) if start.name().as_ref() == TEXT => depth += 1,
        Event::End(end) if end.name().as_ref() == TEXT => depth = depth.saturating_sub(1),
        Event::Text(value) if depth > 0 => text.push_str(&unescape(std::str::from_utf8(value.as_ref())?)?), _ => {}
    } buffer.clear(); }
    Ok(text)
}

fn render_template_rows(template: &[u8], rows: &[Vec<String>]) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut reader = Reader::from_reader(template);
    reader.config_mut().trim_text(false);
    let mut buffer = Vec::new(); let mut events = Vec::new(); let mut cell_texts = Vec::new(); let mut in_cell = false;
    loop { let event = reader.read_event_into(&mut buffer)?.into_owned(); match &event {
        Event::Eof => break,
        Event::Start(start) if start.name().as_ref() == TABLE_CELL => { if in_cell { return Err("nested_table_cells_are_not_supported".into()); } in_cell = true; },
        Event::End(end) if end.name().as_ref() == TABLE_CELL => in_cell = false,
        Event::Text(_) if in_cell => cell_texts.push(events.len()), _ => {}
    } events.push(event); buffer.clear(); }
    if cell_texts.is_empty() { return Err("table_row_template_has_no_text_cells".into()); }
    let mut output = Vec::new();
    for values in rows {
        if values.len() != cell_texts.len() { return Err("table_row_values_do_not_match_template_cells".into()); }
        let mut copy = events.clone();
        for (index, value) in cell_texts.iter().zip(values) { copy[*index] = Event::Text(BytesText::new(value).into_owned()); }
        output.extend(serialize_events(&copy, template.len())?);
    }
    Ok(output)
}

fn format_table_cells(row: &mut Vec<u8>, plan: &EditPlan) -> Result<usize, Box<dyn Error>> {
    let Some(operation) = plan.operations.iter().find_map(|operation| match operation {
        Operation::SetTableCellFormat(operation) => Some(operation),
        _ => None,
    }) else { return Ok(0); };
    let mut reader = Reader::from_reader(row.as_slice());
    reader.config_mut().trim_text(false);
    let mut buffer = Vec::new();
    let mut events = Vec::new();
    let mut cell_start = None;
    let mut text_depth = 0usize;
    let mut cell_text = String::new();
    let mut cells = Vec::new();
    loop {
        let event = reader.read_event_into(&mut buffer)?.into_owned();
        match &event {
            Event::Eof => break,
            Event::Start(start) if start.name().as_ref() == TABLE_CELL => {
                if cell_start.is_some() { return Err("nested_table_cells_are_not_supported".into()); }
                cell_start = Some(events.len());
                cell_text.clear();
            }
            Event::Start(start) if start.name().as_ref() == TEXT => text_depth += 1,
            Event::End(end) if end.name().as_ref() == TEXT => text_depth = text_depth.saturating_sub(1),
            Event::Text(value) if text_depth > 0 && cell_start.is_some() => {
                cell_text.push_str(&unescape(std::str::from_utf8(value.as_ref())?)?);
            }
            Event::End(end) if end.name().as_ref() == TABLE_CELL => {
                let start = cell_start.take().ok_or("table_cell_end_without_start")?;
                cells.push((start, events.len(), cell_text.clone()));
            }
            _ => {}
        }
        events.push(event);
        buffer.clear();
    }
    let mut modifications = 0usize;
    for (start, end, text) in cells.into_iter().rev() {
        if !paragraph_matches(&text, &operation.matcher) { continue; }
        set_table_cell_format(&mut events, start, end, &operation.format)?;
        modifications += 1;
    }
    if modifications > 0 {
        *row = serialize_events(&events, row.len())?;
    }
    Ok(modifications)
}

fn set_table_row_height(row: &mut Vec<u8>, plan: &EditPlan) -> Result<usize, Box<dyn Error>> {
    let Some(operation) = plan.operations.iter().find_map(|operation| match operation {
        Operation::SetTableRowHeight(operation) => Some(operation), _ => None,
    }) else { return Ok(0); };
    if !paragraph_matches(&table_row_text(row)?, &operation.matcher) { return Ok(0); }
    let mut reader = Reader::from_reader(row.as_slice());
    reader.config_mut().trim_text(false);
    let mut buffer = Vec::new();
    let mut events = Vec::new();
    loop { let event = reader.read_event_into(&mut buffer)?.into_owned(); if matches!(event, Event::Eof) { break; } events.push(event); buffer.clear(); }
    let row_start = events.iter().position(|event| matches!(event, Event::Start(start) if start.name().as_ref() == TABLE_ROW)).ok_or("table_row_start_not_found")?;
    let row_end = events.iter().enumerate().skip(row_start + 1).find_map(|(index, event)| matches!(event, Event::End(end) if end.name().as_ref() == TABLE_ROW).then_some(index)).ok_or("table_row_end_not_found")?;
    ensure_table_row_properties(&mut events, row_start, row_end)?;
    let rule = match operation.rule { crate::plan::TableRowHeightRule::AtLeast => "atLeast", crate::plan::TableRowHeightRule::Exact => "exact" };
    set_table_row_property(&mut events, row_start, b"w:trHeight", &[
        ("w:val".to_string(), operation.height_twips.to_string()),
        ("w:hRule".to_string(), rule.to_string()),
    ])?;
    *row = serialize_events(&events, row.len())?;
    Ok(1)
}

fn ensure_table_row_properties(events: &mut Vec<Event<'static>>, row_start: usize, row_end: usize) -> Result<(), Box<dyn Error>> {
    if events[row_start + 1..row_end].iter().any(|event| matches!(event, Event::Start(start) if start.name().as_ref() == TABLE_ROW_PROPERTIES)) { return Ok(()); }
    if let Some(offset) = events[row_start + 1..row_end].iter().position(|event| matches!(event, Event::Empty(empty) if empty.name().as_ref() == TABLE_ROW_PROPERTIES)) {
        let index = row_start + 1 + offset;
        events.splice(index..=index, [Event::Start(quick_xml::events::BytesStart::new("w:trPr")), Event::End(quick_xml::events::BytesEnd::new("w:trPr"))]);
    } else {
        events.splice(row_start + 1..row_start + 1, [Event::Start(quick_xml::events::BytesStart::new("w:trPr")), Event::End(quick_xml::events::BytesEnd::new("w:trPr"))]);
    }
    Ok(())
}

fn set_table_row_property(events: &mut Vec<Event<'static>>, row_start: usize, name: &[u8], attributes: &[(String, String)]) -> Result<(), Box<dyn Error>> {
    let row_end = events.iter().enumerate().skip(row_start + 1).find_map(|(index, event)| matches!(event, Event::End(end) if end.name().as_ref() == TABLE_ROW).then_some(index)).ok_or("table_row_end_not_found")?;
    let properties_start = (row_start + 1..row_end).find(|index| matches!(&events[*index], Event::Start(start) if start.name().as_ref() == TABLE_ROW_PROPERTIES)).ok_or("table_row_properties_start_not_found")?;
    let properties_end = events.iter().enumerate().skip(properties_start + 1).find_map(|(index, event)| matches!(event, Event::End(end) if end.name().as_ref() == TABLE_ROW_PROPERTIES).then_some(index)).ok_or("table_row_properties_end_not_found")?;
    if let Some(index) = (properties_start + 1..properties_end).find(|index| matches!(&events[*index], Event::Empty(element) if element.name().as_ref() == name)) {
        let Event::Empty(existing) = &events[index] else { unreachable!() };
        events[index] = merged_empty_element(std::str::from_utf8(name)?, existing, attributes)?;
    } else if (properties_start + 1..properties_end).any(|index| matches!(&events[index], Event::Start(element) if element.name().as_ref() == name)) {
        return Err("nonempty_table_row_property_is_not_supported".into());
    } else {
        events.insert(properties_end, empty_element(std::str::from_utf8(name)?, attributes));
    }
    Ok(())
}

fn merge_table_cells(row: &mut Vec<u8>, plan: &EditPlan) -> Result<usize, Box<dyn Error>> {
    let Some(operation) = plan.operations.iter().find_map(|operation| match operation {
        Operation::MergeTableCells(operation) if operation.direction == crate::plan::TableCellMergeDirection::Right => Some(operation), _ => None,
    }) else { return Ok(0); };
    let events = parse_xml_events(row)?;
    let cells = table_cell_ranges(&events)?;
    let matching: Vec<_> = cells.iter().enumerate().filter_map(|(index, cell)| paragraph_matches(&cell.text, &operation.matcher).then_some(index)).collect();
    if matching.is_empty() { return Ok(0); }
    if matching.len() != 1 { return Err("table_cell_merge_anchor_is_ambiguous".into()); }
    let first = matching[0];
    let last = first.checked_add(operation.span as usize).and_then(|end| end.checked_sub(1)).ok_or("table_cell_merge_span_overflow")?;
    if last >= cells.len() { return Err("table_cell_merge_span_exceeds_row".into()); }

    let first_start = cells[first].start;
    let first_end = cells[first].end;
    let mut primary = events[first_start..=first_end].to_vec();
    let primary_end = primary.len().checked_sub(1).ok_or("table_cell_end_not_found")?;
    ensure_table_cell_properties(&mut primary, 0, primary_end)?;
    set_table_cell_property(&mut primary, 0, b"w:gridSpan", &[("w:val".to_string(), operation.span.to_string())])?;
    let closing = primary.pop().ok_or("table_cell_end_not_found")?;
    let mut merged = Vec::with_capacity(events.len());
    let mut cursor = 0usize;
    while cursor < events.len() {
        if cursor == first_start {
            merged.extend(primary.iter().cloned());
            for cell in &cells[first + 1..=last] { merged.extend(cell_contents_without_properties(&events, cell.start, cell.end)); }
            merged.push(closing.clone());
            cursor = cells[last].end + 1;
        } else { merged.push(events[cursor].clone()); cursor += 1; }
    }
    *row = serialize_events(&merged, row.len())?;
    Ok(1)
}

fn parse_xml_events(xml: &[u8]) -> Result<Vec<Event<'static>>, Box<dyn Error>> {
    let mut reader = Reader::from_reader(xml);
    reader.config_mut().trim_text(false);
    let mut buffer = Vec::new();
    let mut events = Vec::new();
    loop {
        let event = reader.read_event_into(&mut buffer)?.into_owned();
        if matches!(event, Event::Eof) { break; }
        events.push(event);
        buffer.clear();
    }
    Ok(events)
}

fn table_cell_ranges(events: &[Event<'static>]) -> Result<Vec<TableCellRange>, Box<dyn Error>> {
    let mut ranges = Vec::new();
    let mut cell_start = None;
    let mut text_depth = 0usize;
    let mut text = String::new();
    for (index, event) in events.iter().enumerate() {
        match event {
            Event::Start(start) if start.name().as_ref() == TABLE_CELL => {
                if cell_start.is_some() { return Err("nested_table_cells_are_not_supported".into()); }
                cell_start = Some(index); text.clear();
            }
            Event::Start(start) if start.name().as_ref() == TEXT => text_depth += 1,
            Event::End(end) if end.name().as_ref() == TEXT => text_depth = text_depth.saturating_sub(1),
            Event::Text(value) if text_depth > 0 && cell_start.is_some() => text.push_str(&unescape(std::str::from_utf8(value.as_ref())?)?),
            Event::End(end) if end.name().as_ref() == TABLE_CELL => ranges.push(TableCellRange { start: cell_start.take().ok_or("table_cell_end_without_start")?, end: index, text: text.clone() }),
            _ => {}
        }
    }
    Ok(ranges)
}

fn cell_contents_without_properties(events: &[Event<'static>], cell_start: usize, cell_end: usize) -> Vec<Event<'static>> {
    let mut content = Vec::new();
    let mut properties_depth = 0usize;
    for event in &events[cell_start + 1..cell_end] {
        match event {
            Event::Empty(empty) if empty.name().as_ref() == TABLE_CELL_PROPERTIES => {}
            Event::Start(start) if start.name().as_ref() == TABLE_CELL_PROPERTIES => { properties_depth += 1; }
            Event::End(end) if end.name().as_ref() == TABLE_CELL_PROPERTIES && properties_depth > 0 => { properties_depth -= 1; }
            _ if properties_depth == 0 => content.push(event.clone()),
            _ => {}
        }
    }
    content
}

fn set_table_cell_format(events: &mut Vec<Event<'static>>, cell_start: usize, cell_end: usize, format: &crate::plan::TableCellFormat) -> Result<(), Box<dyn Error>> {
    ensure_table_cell_properties(events, cell_start, cell_end)?;
    if let Some(fill_color) = &format.fill_color {
        set_table_cell_property(events, cell_start, b"w:shd", &[
            ("w:val".to_string(), "clear".to_string()),
            ("w:color".to_string(), "auto".to_string()),
            ("w:fill".to_string(), fill_color.clone()),
        ])?;
    }
    if let Some(vertical_alignment) = &format.vertical_alignment {
        set_table_cell_property(events, cell_start, b"w:vAlign", &[("w:val".to_string(), vertical_alignment.clone())])?;
    }
    if let (Some(color), Some(size)) = (&format.border_color, format.border_eighth_points) {
        set_table_cell_borders(events, cell_start, color, size)?;
    }
    Ok(())
}

fn set_table_cell_borders(events: &mut Vec<Event<'static>>, cell_start: usize, color: &str, size: u16) -> Result<(), Box<dyn Error>> {
    let cell_end = events.iter().enumerate().skip(cell_start + 1).find_map(|(index, event)| matches!(event, Event::End(end) if end.name().as_ref() == TABLE_CELL).then_some(index)).ok_or("table_cell_end_not_found")?;
    let properties_start = (cell_start + 1..cell_end).find(|index| matches!(&events[*index], Event::Start(start) if start.name().as_ref() == TABLE_CELL_PROPERTIES)).ok_or("table_cell_properties_start_not_found")?;
    let properties_end = events.iter().enumerate().skip(properties_start + 1).find_map(|(index, event)| matches!(event, Event::End(end) if end.name().as_ref() == TABLE_CELL_PROPERTIES).then_some(index)).ok_or("table_cell_properties_end_not_found")?;
    if (properties_start + 1..properties_end).any(|index| matches!(&events[index], Event::Start(element) | Event::Empty(element) if element.name().as_ref() == b"w:tcBorders")) { return Err("existing_table_cell_borders_are_not_supported".into()); }
    let size = size.to_string();
    let mut border_events = vec![Event::Start(quick_xml::events::BytesStart::new("w:tcBorders"))];
    for name in ["w:top", "w:left", "w:bottom", "w:right"] {
        let mut border = quick_xml::events::BytesStart::new(name);
        border.push_attribute(("w:val", "single")); border.push_attribute(("w:sz", size.as_str())); border.push_attribute(("w:color", color));
        border_events.push(Event::Empty(border.into_owned()));
    }
    border_events.push(Event::End(quick_xml::events::BytesEnd::new("w:tcBorders")));
    events.splice(properties_end..properties_end, border_events);
    Ok(())
}

fn ensure_table_cell_properties(events: &mut Vec<Event<'static>>, cell_start: usize, cell_end: usize) -> Result<(), Box<dyn Error>> {
    if events[cell_start + 1..cell_end].iter().any(|event| matches!(event, Event::Start(start) if start.name().as_ref() == TABLE_CELL_PROPERTIES)) {
        return Ok(());
    }
    if let Some(offset) = events[cell_start + 1..cell_end].iter().position(|event| matches!(event, Event::Empty(empty) if empty.name().as_ref() == TABLE_CELL_PROPERTIES)) {
        let index = cell_start + 1 + offset;
        events.splice(index..=index, [
            Event::Start(quick_xml::events::BytesStart::new("w:tcPr")),
            Event::End(quick_xml::events::BytesEnd::new("w:tcPr")),
        ]);
        return Ok(());
    }
    events.splice(cell_start + 1..cell_start + 1, [
        Event::Start(quick_xml::events::BytesStart::new("w:tcPr")),
        Event::End(quick_xml::events::BytesEnd::new("w:tcPr")),
    ]);
    Ok(())
}

fn set_table_cell_property(events: &mut Vec<Event<'static>>, cell_start: usize, name: &[u8], attributes: &[(String, String)]) -> Result<(), Box<dyn Error>> {
    let cell_end = events.iter().enumerate().skip(cell_start + 1).find_map(|(index, event)| {
        matches!(event, Event::End(end) if end.name().as_ref() == TABLE_CELL).then_some(index)
    }).ok_or("table_cell_end_not_found")?;
    let properties_start = (cell_start + 1..cell_end).find(|index| matches!(&events[*index], Event::Start(start) if start.name().as_ref() == TABLE_CELL_PROPERTIES))
        .ok_or("table_cell_properties_start_not_found")?;
    let properties_end = events.iter().enumerate().skip(properties_start + 1).find_map(|(index, event)| {
        matches!(event, Event::End(end) if end.name().as_ref() == TABLE_CELL_PROPERTIES).then_some(index)
    }).ok_or("table_cell_properties_end_not_found")?;
    if let Some(index) = (properties_start + 1..properties_end).find(|index| matches!(&events[*index], Event::Empty(element) if element.name().as_ref() == name)) {
        let Event::Empty(existing) = &events[index] else { unreachable!() };
        events[index] = merged_empty_element(std::str::from_utf8(name)?, existing, attributes)?;
        return Ok(());
    }
    if (properties_start + 1..properties_end).any(|index| matches!(&events[index], Event::Start(element) if element.name().as_ref() == name)) {
        return Err("nonempty_table_cell_property_is_not_supported".into());
    }
    events.insert(properties_end, empty_element(std::str::from_utf8(name)?, attributes));
    Ok(())
}

fn table_row_matches(row: &[u8], plan: &EditPlan) -> Result<bool, Box<dyn Error>> {
    let Some(operation) = plan.operations.iter().find_map(|operation| match operation {
        Operation::DeleteTableRows(operation) => Some(operation),
        _ => None,
    }) else { return Ok(false); };
    let mut reader = Reader::from_reader(row);
    reader.config_mut().trim_text(false);
    let mut buffer = Vec::new();
    let mut text_depth = 0usize;
    let mut text = String::new();
    loop {
        let event = reader.read_event_into(&mut buffer)?;
        match event {
            Event::Eof => break,
            Event::Start(start) if start.name().as_ref() == TEXT => text_depth += 1,
            Event::End(end) if end.name().as_ref() == TEXT => text_depth = text_depth.saturating_sub(1),
            Event::Text(value) if text_depth > 0 => text.push_str(&unescape(std::str::from_utf8(value.as_ref())?)?),
            _ => {}
        }
        buffer.clear();
    }
    Ok(paragraph_matches(&text, &operation.matcher))
}

fn insertion_for_paragraph<'a>(paragraph: &[u8], plan: &'a EditPlan, location: ParagraphLocation) -> Result<Option<&'a InsertParagraphsOperation>, Box<dyn Error>> {
    let operation = plan.operations.iter().find_map(|operation| match operation {
        Operation::InsertParagraphs(operation) if applies_to_location(operation, location) => Some(operation),
        _ => None,
    });
    let Some(operation) = operation else { return Ok(None); };
    let mut reader = Reader::from_reader(paragraph);
    reader.config_mut().trim_text(false);
    let mut buffer = Vec::new();
    let mut text_depth = 0usize;
    let mut text = String::new();
    loop {
        let event = reader.read_event_into(&mut buffer)?;
        match event {
            Event::Eof => break,
            Event::Start(start) if start.name().as_ref() == TEXT => text_depth += 1,
            Event::End(end) if end.name().as_ref() == TEXT => text_depth = text_depth.saturating_sub(1),
            Event::Text(value) if text_depth > 0 => text.push_str(&unescape(std::str::from_utf8(value.as_ref())?)?),
            _ => {}
        }
        buffer.clear();
    }
    Ok(paragraph_matches(&text, &operation.anchor).then_some(operation))
}

fn render_inserted_paragraphs(operation: &InsertParagraphsOperation) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut result = Vec::new();
    let mut writer = Writer::new(&mut result);
    for paragraph in &operation.paragraphs {
        writer.write_event(Event::Start(quick_xml::events::BytesStart::new("w:p")))?;
        if let Some(style_id) = &paragraph.style_id {
            writer.write_event(Event::Start(quick_xml::events::BytesStart::new("w:pPr")))?;
            let mut style = quick_xml::events::BytesStart::new("w:pStyle");
            style.push_attribute(("w:val", style_id.as_str()));
            writer.write_event(Event::Empty(style))?;
            if paragraph.page_break_before {
                writer.write_event(Event::Empty(quick_xml::events::BytesStart::new("w:pageBreakBefore")))?;
            }
            writer.write_event(Event::End(quick_xml::events::BytesEnd::new("w:pPr")))?;
        } else if paragraph.page_break_before {
            writer.write_event(Event::Start(quick_xml::events::BytesStart::new("w:pPr")))?;
            writer.write_event(Event::Empty(quick_xml::events::BytesStart::new("w:pageBreakBefore")))?;
            writer.write_event(Event::End(quick_xml::events::BytesEnd::new("w:pPr")))?;
        }
        writer.write_event(Event::Start(quick_xml::events::BytesStart::new("w:r")))?;
        if let Some(format) = &paragraph.format {
            writer.write_event(Event::Start(quick_xml::events::BytesStart::new("w:rPr")))?;
            write_format_elements(&mut writer, format)?;
            writer.write_event(Event::End(quick_xml::events::BytesEnd::new("w:rPr")))?;
        }
        let mut text = quick_xml::events::BytesStart::new("w:t");
        if paragraph.text.starts_with(char::is_whitespace) || paragraph.text.ends_with(char::is_whitespace) {
            text.push_attribute(("xml:space", "preserve"));
        }
        writer.write_event(Event::Start(text))?;
        writer.write_event(Event::Text(BytesText::new(&paragraph.text)))?;
        writer.write_event(Event::End(quick_xml::events::BytesEnd::new("w:t")))?;
        writer.write_event(Event::End(quick_xml::events::BytesEnd::new("w:r")))?;
        writer.write_event(Event::End(quick_xml::events::BytesEnd::new("w:p")))?;
    }
    Ok(result)
}

fn write_paragraph_event(paragraph: &mut Vec<u8>, event: Event<'static>) -> Result<(), Box<dyn Error>> {
    Writer::new(paragraph).write_event(event)?;
    Ok(())
}

fn transform_paragraph(paragraph: &[u8], plan: &EditPlan, location: ParagraphLocation) -> Result<(Vec<u8>, TransformStats), Box<dyn Error>> {
    if !plan.operations.iter().any(|operation| applies_to_location(operation, location)) {
        return Ok((paragraph.to_vec(), TransformStats::default()));
    }
    let mut reader = Reader::from_reader(paragraph);
    reader.config_mut().trim_text(false);
    let mut events = Vec::new();
    let mut segments = Vec::new();
    let mut runs: Vec<Run> = Vec::new();
    let mut boundary_events = Vec::new();
    let mut buffer = Vec::new();
    let mut text_depth = 0usize;
    let mut active_run: Option<usize> = None;

    loop {
        let event = reader.read_event_into(&mut buffer)?.into_owned();
        match &event {
            Event::Eof => break,
            Event::Start(start) => {
                if UNSUPPORTED.iter().any(|name| *name == start.name().as_ref()) {
                    return Err("unsupported_content_in_body_paragraph".into());
                }
                if BOOKMARKS.iter().any(|name| *name == start.name().as_ref()) {
                    boundary_events.push(events.len());
                }
                if start.name().as_ref() == TEXT {
                    text_depth += 1;
                    if let Some(run_index) = active_run {
                        let run = &mut runs[run_index];
                        if run.text_start.replace(events.len()).is_some() {
                            return Err("formatting_requires_one_text_node_per_run".into());
                        }
                    }
                }
                if start.name().as_ref() == b"w:r" {
                    if active_run.is_some() {
                        return Err("nested_run_is_not_supported".into());
                    }
                    runs.push(Run { start: events.len(), end: 0, text_start: None, text_event: None, text_end: None, segment_index: None });
                    active_run = Some(runs.len() - 1);
                }
            }
            Event::Empty(empty) if UNSUPPORTED.iter().any(|name| *name == empty.name().as_ref()) => {
                return Err("unsupported_content_in_body_paragraph".into());
            }
            Event::Empty(empty) if BOOKMARKS.iter().any(|name| *name == empty.name().as_ref()) => {
                boundary_events.push(events.len());
            }
            Event::End(end) if end.name().as_ref() == TEXT => {
                text_depth = text_depth.saturating_sub(1);
                if let Some(run_index) = active_run {
                    runs[run_index].text_end = Some(events.len());
                }
            }
            Event::End(end) if end.name().as_ref() == b"w:r" => {
                let run_index = active_run.take().ok_or("run_end_without_start")?;
                runs[run_index].end = events.len();
            }
            Event::Text(text) if text_depth > 0 => {
                let raw = std::str::from_utf8(text.as_ref())?;
                let decoded = unescape(raw)?.into_owned();
                let run_index = active_run;
                if let Some(index) = run_index {
                    let run = &mut runs[index];
                    if run.text_event.replace(events.len()).is_some() {
                        return Err("formatting_requires_one_text_event_per_run".into());
                    }
                    run.segment_index = Some(segments.len());
                }
                segments.push(Segment { event_index: events.len(), text: decoded, run_index });
            }
            _ => {}
        }
        events.push(event);
        buffer.clear();
    }

    if let Some(operation) = plan.operations.iter().find_map(|operation| match operation {
        Operation::DeleteParagraphs(operation) if applies_to_location(operation, location) => Some(operation),
        _ => None,
    }) {
        let text = joined_text(&segments);
        if paragraph_matches(&text, &operation.matcher) {
            return Ok((Vec::new(), TransformStats { matches: 1, modifications: 1 }));
        }
    }

    if let Some(operation) = plan.operations.iter().find_map(|operation| match operation {
        Operation::FormatParagraphs(operation) if applies_to_location(operation, location) => Some(operation),
        _ => None,
    }) {
        if paragraph_matches(&joined_text(&segments), &operation.matcher) {
            if segments.iter().any(|segment| segment.run_index.is_none()) {
                return Err("formatting_requires_text_runs".into());
            }
            let pieces = segments.iter().map(|segment| vec![Piece {
                text: segment.text.clone(), format: Some(operation.format.clone()),
            }]).collect::<Vec<_>>();
            return render_formatted_paragraph(&events, &runs, &segments, &pieces, paragraph.len())
                .map(|output| (output, TransformStats { matches: 1, modifications: 1 }));
        }
    }

    if let Some(operation) = plan.operations.iter().find_map(|operation| match operation {
        Operation::SetParagraphStyle(operation) if applies_to_location(operation, location) => Some(operation),
        _ => None,
    }) {
        if paragraph_matches(&joined_text(&segments), &operation.matcher) {
            set_paragraph_style(&mut events, &operation.style_id)?;
            return Ok((serialize_events(&events, paragraph.len())?, TransformStats { matches: 1, modifications: 1 }));
        }
    }

    if let Some(operation) = plan.operations.iter().find_map(|operation| match operation {
        Operation::SetParagraphLayout(operation) if applies_to_location(operation, location) => Some(operation),
        _ => None,
    }) {
        if paragraph_matches(&joined_text(&segments), &operation.matcher) {
            set_paragraph_layout(&mut events, &operation.layout)?;
            return Ok((serialize_events(&events, paragraph.len())?, TransformStats { matches: 1, modifications: 1 }));
        }
    }

    if let Some(operation) = plan.operations.iter().find_map(|operation| match operation {
        Operation::SetParagraphNumbering(operation) if applies_to_location(operation, location) => Some(operation),
        _ => None,
    }) {
        if paragraph_matches(&joined_text(&segments), &operation.matcher) {
            set_paragraph_numbering(&mut events, operation.num_id, operation.level)?;
            return Ok((serialize_events(&events, paragraph.len())?, TransformStats { matches: 1, modifications: 1 }));
        }
    }

    if let Some(operation) = plan.operations.iter().find_map(|operation| match operation {
        Operation::SetParagraphPagination(operation) if applies_to_location(operation, location) => Some(operation),
        _ => None,
    }) {
        if paragraph_matches(&joined_text(&segments), &operation.matcher) {
            set_paragraph_pagination(&mut events, &operation.pagination)?;
            return Ok((serialize_events(&events, paragraph.len())?, TransformStats { matches: 1, modifications: 1 }));
        }
    }

    let mut stats = TransformStats::default();
    let mut has_format_b_tags = false;
    let mut text_format = None;
    let mut tagged_format = None;
    for operation in &plan.operations {
        match operation {
            Operation::ReplaceText(operation) => {
                if !applies_to_location(operation, location) { continue; }
                let original = joined_text(&segments);
                let matches: Vec<_> = original.match_indices(&operation.search).collect();
                stats.matches += matches.len();
                for (start, matched) in matches.into_iter().rev() {
                    let boundaries = boundary_offsets(&segments, &boundary_events);
                    if boundaries.iter().any(|boundary| start < *boundary && *boundary < start + matched.len()) {
                        return Err("replacement_crosses_bookmark_boundary".into());
                    }
                    if matched != operation.replacement {
                        replace_range(&mut segments, start, start + matched.len(), &operation.replacement)?;
                        stats.modifications += 1;
                    }
                }
            }
            Operation::RegexReplace(operation) if applies_to_location(operation, location) => {
                let original = joined_text(&segments);
                let matches: Vec<_> = operation.regex.captures_iter(&original).map(|captures| {
                    let matched = captures.get(0).expect("regex captures always include the full match");
                    let mut replacement = String::new();
                    captures.expand(&operation.replacement, &mut replacement);
                    (matched.start(), matched.end(), replacement)
                }).collect();
                stats.matches += matches.len();
                for (start, end, replacement) in matches.into_iter().rev() {
                    if start == end { return Err("zero_length_regex_match_is_not_supported".into()); }
                    let boundaries = boundary_offsets(&segments, &boundary_events);
                    if boundaries.iter().any(|boundary| start < *boundary && *boundary < end) {
                        return Err("replacement_crosses_bookmark_boundary".into());
                    }
                    if original[start..end] != replacement {
                        replace_range(&mut segments, start, end, &replacement)?;
                        stats.modifications += 1;
                    }
                }
            }
            Operation::RegexReplace(_) => {}
            Operation::FormatBTags(operation) if applies_to_location(operation, location) => has_format_b_tags = true,
            Operation::FormatBTags(_) => {}
            Operation::FormatText(operation) if applies_to_location(operation, location) => text_format = Some(operation),
            Operation::FormatText(_) => {}
            Operation::FormatTagged(operation) if applies_to_location(operation, location) => tagged_format = Some(operation),
            Operation::FormatTagged(_) => {}
            Operation::DeleteParagraphs(_) => {}
            Operation::SetParagraphStyle(_) => {}
            Operation::FormatParagraphs(_) => {}
            Operation::SetParagraphLayout(_) => {}
            Operation::SetParagraphNumbering(_) => {}
            Operation::SetParagraphPagination(_) => {}
            Operation::DeleteTableRows(_) => {}
            Operation::SetTableCellFormat(_) => {}
            Operation::InsertTableRows(_) => {}
            Operation::SetTableRowHeight(_) => {}
            Operation::MergeTableCells(_) => {}
            Operation::SetTableColumnWidth(_) => {}
            Operation::InsertParagraphs(_) => {}
        }
    }
    let pieces = if let Some(operation) = tagged_format {
        let boundaries = boundary_offsets(&segments, &boundary_events);
        let (pieces, format_stats) = format_tagged(&segments, &boundaries, &operation.open_tag, &operation.close_tag, &operation.format)?;
        stats.matches += format_stats.matches;
        stats.modifications += format_stats.modifications;
        Some(pieces)
    } else if let Some(operation) = text_format {
        let boundaries = boundary_offsets(&segments, &boundary_events);
        let (pieces, format_stats) = format_literal_text(&segments, &boundaries, &operation.search, &operation.format)?;
        stats.matches += format_stats.matches;
        stats.modifications += format_stats.modifications;
        Some(pieces)
    } else if has_format_b_tags {
        let boundaries = boundary_offsets(&segments, &boundary_events);
        let (pieces, format_stats) = format_tagged(&segments, &boundaries, "<B>", "<D>", &bold_format())?;
        stats.matches += format_stats.matches;
        stats.modifications += format_stats.modifications;
        Some(pieces)
    } else { None };
    if stats.modifications == 0 {
        return Ok((paragraph.to_vec(), stats));
    }
    if let Some(pieces) = pieces {
        return render_formatted_paragraph(&events, &runs, &segments, &pieces, paragraph.len()).map(|result| (result, stats));
    }
    write_replaced_text_events(&mut events, &segments)?;
    Ok((serialize_events(&events, paragraph.len())?, stats))
}

fn serialize_events(events: &[Event<'static>], capacity: usize) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut result = Vec::with_capacity(capacity);
    let mut writer = Writer::new(&mut result);
    for event in events {
        writer.write_event(event.clone())?;
    }
    Ok(result)
}

fn set_paragraph_style(events: &mut Vec<Event<'static>>, style_id: &str) -> Result<(), Box<dyn Error>> {
    let style = || {
        let mut element = quick_xml::events::BytesStart::new("w:pStyle");
        element.push_attribute(("w:val", style_id));
        Event::Empty(element)
    };
    let paragraph_start = events.iter().position(|event| matches!(event, Event::Start(start) if start.name().as_ref() == PARAGRAPH))
        .ok_or("paragraph_start_not_found")?;
    if let Some(index) = events.iter().position(|event| matches!(event, Event::Empty(empty) if empty.name().as_ref() == PARAGRAPH_STYLE)) {
        events[index] = style();
        return Ok(());
    }
    if events.iter().any(|event| matches!(event, Event::Start(start) if start.name().as_ref() == PARAGRAPH_STYLE)) {
        return Err("nonempty_paragraph_style_is_not_supported".into());
    }
    if let Some(index) = events.iter().position(|event| matches!(event, Event::Empty(empty) if empty.name().as_ref() == PARAGRAPH_PROPERTIES)) {
        events.splice(index..=index, [
            Event::Start(quick_xml::events::BytesStart::new("w:pPr")), style(),
            Event::End(quick_xml::events::BytesEnd::new("w:pPr")),
        ]);
        return Ok(());
    }
    if let Some(index) = events.iter().position(|event| matches!(event, Event::End(end) if end.name().as_ref() == PARAGRAPH_PROPERTIES)) {
        events.insert(index, style());
        return Ok(());
    }
    events.splice(paragraph_start + 1..paragraph_start + 1, [
        Event::Start(quick_xml::events::BytesStart::new("w:pPr")), style(),
        Event::End(quick_xml::events::BytesEnd::new("w:pPr")),
    ]);
    Ok(())
}

fn set_paragraph_layout(events: &mut Vec<Event<'static>>, layout: &ParagraphLayout) -> Result<(), Box<dyn Error>> {
    let mut properties = Vec::new();
    if let Some(alignment) = &layout.alignment {
        properties.push(("w:jc", vec![("w:val".to_string(), alignment.clone())]));
    }
    let mut spacing = Vec::new();
    if let Some(before) = layout.space_before_twips { spacing.push(("w:before".to_string(), before.to_string())); }
    if let Some(after) = layout.space_after_twips { spacing.push(("w:after".to_string(), after.to_string())); }
    if !spacing.is_empty() { properties.push(("w:spacing", spacing)); }
    let mut indentation = Vec::new();
    if let Some(left) = layout.left_indent_twips { indentation.push(("w:left".to_string(), left.to_string())); }
    if let Some(right) = layout.right_indent_twips { indentation.push(("w:right".to_string(), right.to_string())); }
    if !indentation.is_empty() { properties.push(("w:ind", indentation)); }

    let paragraph_start = events.iter().position(|event| matches!(event, Event::Start(start) if start.name().as_ref() == PARAGRAPH))
        .ok_or("paragraph_start_not_found")?;
    if let Some(index) = events.iter().position(|event| matches!(event, Event::Empty(empty) if empty.name().as_ref() == PARAGRAPH_PROPERTIES)) {
        let replacements = properties.into_iter().map(|(name, attributes)| empty_element(name, &attributes)).collect::<Vec<_>>();
        events.splice(index..=index, std::iter::once(Event::Start(quick_xml::events::BytesStart::new("w:pPr")))
            .chain(replacements).chain(std::iter::once(Event::End(quick_xml::events::BytesEnd::new("w:pPr")))));
        return Ok(());
    }
    if !events.iter().any(|event| matches!(event, Event::Start(start) if start.name().as_ref() == PARAGRAPH_PROPERTIES)) {
        let additions = properties.into_iter().map(|(name, attributes)| empty_element(name, &attributes)).collect::<Vec<_>>();
        events.splice(paragraph_start + 1..paragraph_start + 1, std::iter::once(Event::Start(quick_xml::events::BytesStart::new("w:pPr")))
            .chain(additions).chain(std::iter::once(Event::End(quick_xml::events::BytesEnd::new("w:pPr")))));
        return Ok(());
    }
    for (name, attributes) in properties {
        set_paragraph_property(events, name, &attributes)?;
    }
    Ok(())
}

fn set_paragraph_numbering(events: &mut Vec<Event<'static>>, num_id: u32, level: u8) -> Result<(), Box<dyn Error>> {
    ensure_paragraph_properties(events)?;
    let mut level_element = quick_xml::events::BytesStart::new("w:ilvl");
    let level_value = level.to_string();
    level_element.push_attribute(("w:val", level_value.as_str()));
    let mut number_element = quick_xml::events::BytesStart::new("w:numId");
    let number_value = num_id.to_string();
    number_element.push_attribute(("w:val", number_value.as_str()));
    set_paragraph_child(events, b"w:numPr", vec![
        Event::Start(quick_xml::events::BytesStart::new("w:numPr")),
        Event::Empty(level_element),
        Event::Empty(number_element),
        Event::End(quick_xml::events::BytesEnd::new("w:numPr")),
    ])
}

fn set_paragraph_pagination(events: &mut Vec<Event<'static>>, pagination: &ParagraphPagination) -> Result<(), Box<dyn Error>> {
    ensure_paragraph_properties(events)?;
    for (name, value) in [
        ("w:keepNext", pagination.keep_with_next),
        ("w:keepLines", pagination.keep_together),
        ("w:pageBreakBefore", pagination.page_break_before),
    ] {
        if let Some(value) = value {
            set_paragraph_property(events, name, &[("w:val".to_string(), if value { "1" } else { "0" }.to_string())])?;
        }
    }
    Ok(())
}

fn ensure_paragraph_properties(events: &mut Vec<Event<'static>>) -> Result<(), Box<dyn Error>> {
    if events.iter().any(|event| matches!(event, Event::Start(start) if start.name().as_ref() == PARAGRAPH_PROPERTIES)) {
        return Ok(());
    }
    if let Some(index) = events.iter().position(|event| matches!(event, Event::Empty(empty) if empty.name().as_ref() == PARAGRAPH_PROPERTIES)) {
        events.splice(index..=index, [
            Event::Start(quick_xml::events::BytesStart::new("w:pPr")),
            Event::End(quick_xml::events::BytesEnd::new("w:pPr")),
        ]);
        return Ok(());
    }
    let paragraph_start = events.iter().position(|event| matches!(event, Event::Start(start) if start.name().as_ref() == PARAGRAPH))
        .ok_or("paragraph_start_not_found")?;
    events.splice(paragraph_start + 1..paragraph_start + 1, [
        Event::Start(quick_xml::events::BytesStart::new("w:pPr")),
        Event::End(quick_xml::events::BytesEnd::new("w:pPr")),
    ]);
    Ok(())
}

fn set_paragraph_child(events: &mut Vec<Event<'static>>, name: &[u8], replacement: Vec<Event<'static>>) -> Result<(), Box<dyn Error>> {
    let ppr_start = events.iter().position(|event| matches!(event, Event::Start(start) if start.name().as_ref() == PARAGRAPH_PROPERTIES))
        .ok_or("paragraph_properties_start_not_found")?;
    let ppr_end = events.iter().enumerate().skip(ppr_start + 1).find_map(|(index, event)| {
        matches!(event, Event::End(end) if end.name().as_ref() == PARAGRAPH_PROPERTIES).then_some(index)
    }).ok_or("paragraph_properties_end_not_found")?;
    if let Some(index) = (ppr_start + 1..ppr_end).find(|index| matches!(&events[*index], Event::Empty(element) if element.name().as_ref() == name)) {
        events.splice(index..=index, replacement);
        return Ok(());
    }
    if let Some(start) = (ppr_start + 1..ppr_end).find(|index| matches!(&events[*index], Event::Start(element) if element.name().as_ref() == name)) {
        let mut depth = 0usize;
        let end = (start..ppr_end).find(|index| match &events[*index] {
            Event::Start(element) if element.name().as_ref() == name => { depth += 1; false }
            Event::End(element) if element.name().as_ref() == name => {
                depth -= 1;
                depth == 0
            }
            _ => false,
        }).ok_or("paragraph_property_end_not_found")?;
        events.splice(start..=end, replacement);
        return Ok(());
    }
    events.splice(ppr_end..ppr_end, replacement);
    Ok(())
}

fn set_paragraph_property(events: &mut Vec<Event<'static>>, name: &str, attributes: &[(String, String)]) -> Result<(), Box<dyn Error>> {
    let ppr_start = events.iter().position(|event| matches!(event, Event::Start(start) if start.name().as_ref() == PARAGRAPH_PROPERTIES))
        .ok_or("paragraph_properties_start_not_found")?;
    let ppr_end = events.iter().enumerate().skip(ppr_start + 1).find_map(|(index, event)| {
        matches!(event, Event::End(end) if end.name().as_ref() == PARAGRAPH_PROPERTIES).then_some(index)
    }).ok_or("paragraph_properties_end_not_found")?;
    if let Some(index) = (ppr_start + 1..ppr_end).find(|index| matches!(&events[*index], Event::Empty(element) if element.name().as_ref() == name.as_bytes())) {
        let Event::Empty(existing) = &events[index] else { unreachable!() };
        events[index] = merged_empty_element(name, existing, attributes)?;
        return Ok(());
    }
    if (ppr_start + 1..ppr_end).any(|index| matches!(&events[index], Event::Start(element) if element.name().as_ref() == name.as_bytes())) {
        return Err("nonempty_paragraph_property_is_not_supported".into());
    }
    events.insert(ppr_end, empty_element(name, attributes));
    Ok(())
}

fn empty_element(name: &str, attributes: &[(String, String)]) -> Event<'static> {
    let mut element = quick_xml::events::BytesStart::new(name);
    for (key, value) in attributes {
        element.push_attribute((key.as_str(), value.as_str()));
    }
    Event::Empty(element.into_owned())
}

fn merged_empty_element(name: &str, existing: &quick_xml::events::BytesStart<'_>, updates: &[(String, String)]) -> Result<Event<'static>, Box<dyn Error>> {
    let mut element = quick_xml::events::BytesStart::new(name);
    for attribute in existing.attributes().with_checks(false) {
        let attribute = attribute?;
        let key = std::str::from_utf8(attribute.key.as_ref())?;
        if updates.iter().any(|(update, _)| update == key) { continue; }
        let value = std::str::from_utf8(attribute.value.as_ref())?;
        element.push_attribute((key, value));
    }
    for (key, value) in updates {
        element.push_attribute((key.as_str(), value.as_str()));
    }
    Ok(Event::Empty(element.into_owned()))
}

fn paragraph_matches(text: &str, matcher: &ParagraphMatch) -> bool {
    match matcher {
        ParagraphMatch::Exact(value) => text == value,
        ParagraphMatch::StartsWith(value) => text.starts_with(value),
        ParagraphMatch::Contains(value) => text.contains(value),
    }
}

trait HasLocation {
    fn location(&self) -> Location;
}

impl HasLocation for Operation {
    fn location(&self) -> Location {
        match self {
            Operation::ReplaceText(operation) => operation.location,
            Operation::FormatBTags(operation) => operation.location,
            Operation::FormatText(operation) => operation.location,
            Operation::DeleteParagraphs(operation) => operation.location,
            Operation::RegexReplace(operation) => operation.location,
            Operation::FormatTagged(operation) => operation.location,
            Operation::SetParagraphStyle(operation) => operation.location,
            Operation::FormatParagraphs(operation) => operation.location,
            Operation::SetParagraphLayout(operation) => operation.location,
            Operation::SetParagraphNumbering(operation) => operation.location,
            Operation::SetParagraphPagination(operation) => operation.location,
            Operation::DeleteTableRows(operation) => operation.location,
            Operation::SetTableCellFormat(operation) => operation.location,
            Operation::InsertTableRows(operation) => operation.location,
            Operation::SetTableRowHeight(operation) => operation.location,
            Operation::MergeTableCells(operation) => operation.location,
            Operation::SetTableColumnWidth(operation) => operation.location,
            Operation::InsertParagraphs(operation) => operation.location,
        }
    }
}

impl HasLocation for crate::plan::ReplaceTextOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::FormatBTagsOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::FormatTextOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::DeleteParagraphsOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::RegexReplaceOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::FormatTaggedOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::SetParagraphStyleOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::FormatParagraphsOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::SetParagraphLayoutOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::SetParagraphNumberingOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::SetParagraphPaginationOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::DeleteTableRowsOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::SetTableCellFormatOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::InsertTableRowsOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::SetTableRowHeightOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::MergeTableCellsOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::SetTableColumnWidthOperation {
    fn location(&self) -> Location { self.location }
}

impl HasLocation for crate::plan::InsertParagraphsOperation {
    fn location(&self) -> Location { self.location }
}

fn applies_to_location(operation: &impl HasLocation, paragraph: ParagraphLocation) -> bool {
    matches!(
        (operation.location(), paragraph),
        (Location::All, _)
            | (Location::Body, ParagraphLocation::Body)
            | (Location::Tables, ParagraphLocation::Tables)
            | (Location::HeadersFooters, ParagraphLocation::HeadersFooters)
    )
}

fn boundary_offsets(segments: &[Segment], boundary_events: &[usize]) -> Vec<usize> {
    boundary_events.iter().map(|boundary| {
        segments.iter().filter(|segment| segment.event_index < *boundary).map(|segment| segment.text.len()).sum()
    }).collect()
}

fn write_replaced_text_events(events: &mut [Event<'static>], segments: &[Segment]) -> Result<(), Box<dyn Error>> {
    for segment in segments {
        events[segment.event_index] = Event::Text(BytesText::new(&segment.text).into_owned());
        let needs_preserve = segment.text.starts_with(char::is_whitespace) || segment.text.ends_with(char::is_whitespace);
        if !needs_preserve { continue; }
        let start_index = (0..segment.event_index).rev().find(|index| matches!(&events[*index], Event::Start(start) if start.name().as_ref() == TEXT))
            .ok_or("text_start_not_found")?;
        if let Event::Start(start) = &events[start_index] {
            let mut start = start.clone();
            let has_space = start.attributes().flatten().any(|attribute| attribute.key.as_ref() == b"xml:space");
            if !has_space { start.push_attribute(("xml:space", "preserve")); }
            events[start_index] = Event::Start(start);
        }
    }
    Ok(())
}

fn format_tagged(segments: &[Segment], boundaries: &[usize], open_tag: &str, close_tag: &str, format: &TextFormat) -> Result<(Vec<Vec<Piece>>, TransformStats), Box<dyn Error>> {
    if segments.iter().any(|segment| segment.run_index.is_none()) {
        return Err("formatting_requires_text_runs".into());
    }
    let source = joined_text(segments);
    let mut spans = Vec::new();
    let mut stack = Vec::new();
    let mut cursor = 0usize;
    let mut depth = 0usize;
    let mut stats = TransformStats::default();

    while cursor < source.len() {
        let open = source[cursor..].find(open_tag).map(|offset| cursor + offset);
        let close = source[cursor..].find(close_tag).map(|offset| cursor + offset);
        let (marker, is_open) = match (open, close) {
            (None, None) => break,
            (Some(start), None) => (start, true),
            (None, Some(start)) => (start, false),
            (Some(open), Some(close)) if open < close => (open, true),
            (Some(_), Some(close)) => (close, false),
        };
        if cursor < marker {
            spans.push((cursor, marker, depth > 0));
        }
        if is_open {
            stack.push(marker);
            depth += 1;
        } else {
            let open_start = stack.pop().ok_or("unmatched_b_tag_close")?;
            if boundaries.iter().any(|boundary| open_start < *boundary && *boundary < marker + close_tag.len()) {
                return Err("format_tag_pair_crosses_bookmark_boundary".into());
            }
            depth -= 1;
            stats.matches += 1;
            stats.modifications += 1;
        }
        cursor = marker + if is_open { open_tag.len() } else { close_tag.len() };
    }
    if !stack.is_empty() {
        return Err("unmatched_b_tag_open".into());
    }
    if cursor < source.len() {
        spans.push((cursor, source.len(), depth > 0));
    }
    let mut pieces = Vec::with_capacity(segments.len());
    let mut span_index = 0usize;
    let mut offset = 0usize;
    for segment in segments {
        let end = offset + segment.text.len();
        while span_index < spans.len() && spans[span_index].1 <= offset { span_index += 1; }
        let mut result: Vec<Piece> = Vec::new();
        let mut index = span_index;
        while index < spans.len() && spans[index].0 < end {
            let (start, span_end, bold) = spans[index];
            let from = start.max(offset) - offset;
            let to = span_end.min(end) - offset;
            if from < to {
                if let Some(previous) = result.last_mut() {
                    if previous.format.as_ref() == if bold { Some(format) } else { None } {
                        previous.text.push_str(&segment.text[from..to]);
                    } else {
                        result.push(Piece { text: segment.text[from..to].to_string(), format: bold.then(|| format.clone()) });
                    }
                } else {
                    result.push(Piece { text: segment.text[from..to].to_string(), format: bold.then(|| format.clone()) });
                }
            }
            index += 1;
        }
        if result.is_empty() {
            result.push(Piece { text: String::new(), format: None });
        }
        pieces.push(result);
        offset = end;
    }
    Ok((pieces, stats))
}

fn bold_format() -> TextFormat {
    TextFormat {
        bold: Some(true), italic: None, underline: None, strike: None, color: None,
        highlight: None, font_name: None, size_half_points: None,
    }
}

fn format_literal_text(
    segments: &[Segment], boundaries: &[usize], search: &str, format: &TextFormat,
) -> Result<(Vec<Vec<Piece>>, TransformStats), Box<dyn Error>> {
    let source = joined_text(segments);
    let matches: Vec<_> = source.match_indices(search).collect();
    let mut spans = Vec::with_capacity(matches.len() * 2 + 1);
    let mut cursor = 0usize;
    for (start, matched) in matches {
        let end = start + matched.len();
        if boundaries.iter().any(|boundary| start < *boundary && *boundary < end) {
            return Err("formatting_crosses_bookmark_boundary".into());
        }
        if cursor < start {
            spans.push((cursor, start, None));
        }
        spans.push((start, end, Some(format.clone())));
        cursor = end;
    }
    if cursor < source.len() {
        spans.push((cursor, source.len(), None));
    }
    let mut pieces = Vec::with_capacity(segments.len());
    let mut span_index = 0usize;
    let mut offset = 0usize;
    for segment in segments {
        let end = offset + segment.text.len();
        while span_index < spans.len() && spans[span_index].1 <= offset { span_index += 1; }
        let mut result = Vec::new();
        let mut index = span_index;
        while index < spans.len() && spans[index].0 < end {
            let (start, span_end, piece_format) = &spans[index];
            let from = (*start).max(offset) - offset;
            let to = (*span_end).min(end) - offset;
            if from < to {
                result.push(Piece { text: segment.text[from..to].to_string(), format: piece_format.clone() });
            }
            index += 1;
        }
        if result.is_empty() {
            result.push(Piece { text: String::new(), format: None });
        }
        pieces.push(result);
        offset = end;
    }
    let count = source.match_indices(search).count();
    Ok((pieces, TransformStats { matches: count, modifications: count }))
}

fn render_formatted_paragraph(
    events: &[Event<'static>], runs: &[Run], segments: &[Segment], pieces: &[Vec<Piece>], capacity: usize,
) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut result = Vec::with_capacity(capacity);
    let mut writer = Writer::new(&mut result);
    let mut index = 0usize;
    while index < events.len() {
        if let Some(run) = runs.iter().find(|run| run.start == index) {
            if let Some(segment_index) = run.segment_index {
                let changed = pieces[segment_index].len() != 1
                    || pieces[segment_index][0].format.is_some()
                    || pieces[segment_index][0].text != segments[segment_index].text;
                if changed {
                    write_split_run(&mut writer, events, run, &pieces[segment_index])?;
                    index = run.end + 1;
                    continue;
                }
            }
        }
        writer.write_event(events[index].clone())?;
        index += 1;
    }
    Ok(result)
}

fn write_split_run<W: Write>(writer: &mut Writer<W>, events: &[Event<'static>], run: &Run, pieces: &[Piece]) -> Result<(), Box<dyn Error>> {
    let text_start = run.text_start.ok_or("formatting_requires_text_start")?;
    let text_event = run.text_event.ok_or("formatting_requires_text_event")?;
    let text_end = run.text_end.ok_or("formatting_requires_text_end")?;
    let mut rpr_start = None;
    let mut rpr_end = None;
    let mut rpr_empty = None;
    for event in &events[run.start..=run.end] {
        match event {
            Event::Start(start) if start.name().as_ref() == b"w:rPr" => rpr_start = Some(()),
            Event::End(end) if end.name().as_ref() == b"w:rPr" => rpr_end = Some(()),
            Event::Empty(empty) if empty.name().as_ref() == b"w:rPr" => rpr_empty = Some(()),
            _ => {}
        }
    }
    if rpr_start.is_some() != rpr_end.is_some() || (rpr_empty.is_some() && rpr_start.is_some()) { return Err("malformed_run_properties".into()); }

    for (piece_index, piece) in pieces.iter().enumerate() {
        for index in run.start..=run.end {
            match &events[index] {
                Event::Start(_) if index == run.start => {
                    writer.write_event(events[index].clone())?;
                    if rpr_start.is_none() && rpr_empty.is_none() {
                        if let Some(format) = &piece.format {
                            writer.write_event(Event::Start(quick_xml::events::BytesStart::new("w:rPr")))?;
                            write_format_elements(writer, format)?;
                            writer.write_event(Event::End(quick_xml::events::BytesEnd::new("w:rPr")))?;
                        }
                    }
                }
                Event::Empty(empty) if empty.name().as_ref() == b"w:rPr" && piece.format.is_some() => {
                    writer.write_event(Event::Start(quick_xml::events::BytesStart::new("w:rPr")))?;
                    write_format_elements(writer, piece.format.as_ref().unwrap())?;
                    writer.write_event(Event::End(quick_xml::events::BytesEnd::new("w:rPr")))?;
                }
                Event::Empty(empty) if piece_index > 0 && empty.name().as_ref() == b"w:lastRenderedPageBreak" => {}
                Event::Start(start) if index == text_start => {
                    let mut start = start.clone();
                    let needs_preserve = piece.text.starts_with(char::is_whitespace) || piece.text.ends_with(char::is_whitespace);
                    let has_space = start.attributes().flatten().any(|attribute| attribute.key.as_ref() == b"xml:space");
                    if needs_preserve && !has_space { start.push_attribute(("xml:space", "preserve")); }
                    writer.write_event(Event::Start(start))?;
                }
                Event::Text(_) if index == text_event => writer.write_event(Event::Text(BytesText::new(&piece.text).into_owned()))?,
                Event::End(_) if index == text_end => writer.write_event(events[index].clone())?,
                Event::End(end) if end.name().as_ref() == b"w:rPr" => {
                    if let Some(format) = &piece.format {
                        write_format_elements(writer, format)?;
                    }
                    writer.write_event(events[index].clone())?;
                }
                _ => writer.write_event(events[index].clone())?,
            }
        }
    }
    Ok(())
}

fn write_format_elements<W: Write>(writer: &mut Writer<W>, format: &TextFormat) -> Result<(), Box<dyn Error>> {
    if let Some(value) = format.bold {
        write_toggle(writer, "w:b", value)?;
    }
    if let Some(value) = format.italic {
        write_toggle(writer, "w:i", value)?;
    }
    if let Some(value) = format.underline {
        let mut element = quick_xml::events::BytesStart::new("w:u");
        element.push_attribute(("w:val", if value { "single" } else { "none" }));
        writer.write_event(Event::Empty(element))?;
    }
    if let Some(value) = format.strike {
        write_toggle(writer, "w:strike", value)?;
    }
    if let Some(color) = &format.color {
        let mut element = quick_xml::events::BytesStart::new("w:color");
        element.push_attribute(("w:val", color.as_str()));
        writer.write_event(Event::Empty(element))?;
    }
    if let Some(highlight) = &format.highlight {
        let mut element = quick_xml::events::BytesStart::new("w:highlight");
        element.push_attribute(("w:val", highlight.as_str()));
        writer.write_event(Event::Empty(element))?;
    }
    if let Some(font_name) = &format.font_name {
        let mut element = quick_xml::events::BytesStart::new("w:rFonts");
        element.push_attribute(("w:ascii", font_name.as_str()));
        element.push_attribute(("w:hAnsi", font_name.as_str()));
        element.push_attribute(("w:eastAsia", font_name.as_str()));
        element.push_attribute(("w:cs", font_name.as_str()));
        writer.write_event(Event::Empty(element))?;
    }
    if let Some(size) = format.size_half_points {
        let value = size.to_string();
        for name in ["w:sz", "w:szCs"] {
            let mut element = quick_xml::events::BytesStart::new(name);
            element.push_attribute(("w:val", value.as_str()));
            writer.write_event(Event::Empty(element))?;
        }
    }
    Ok(())
}

fn write_toggle<W: Write>(writer: &mut Writer<W>, name: &str, value: bool) -> Result<(), Box<dyn Error>> {
    let mut element = quick_xml::events::BytesStart::new(name);
    if !value { element.push_attribute(("w:val", "0")); }
    writer.write_event(Event::Empty(element))?;
    Ok(())
}

fn joined_text(segments: &[Segment]) -> String {
    let mut result = String::new();
    for segment in segments {
        result.push_str(&segment.text);
    }
    result
}

fn replace_range(segments: &mut [Segment], start: usize, end: usize, replacement: &str) -> Result<(), Box<dyn Error>> {
    let mut starts = Vec::with_capacity(segments.len());
    let mut offset = 0usize;
    let mut first = None;
    let mut last = None;
    for (index, segment) in segments.iter().enumerate() {
        starts.push(offset);
        let next = offset + segment.text.len();
        if first.is_none() && start < next {
            first = Some(index);
        }
        if start < next && end <= next {
            last = Some(index);
            break;
        }
        offset = next;
    }
    let (first, last) = match (first, last) {
        (Some(first), Some(last)) => (first, last),
        _ => return Err("match_outside_text_segments".into()),
    };
    for current in (first..=last).rev() {
        let target = &mut segments[current];
        let segment_start = starts[current];
        let from = start.saturating_sub(segment_start);
        let to = end.min(segment_start + target.text.len()) - segment_start;
        if current == first {
            target.text.replace_range(from..to, replacement);
        } else {
            target.text.replace_range(from..to, "");
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::plan::{DeleteParagraphsOperation, EditPlan, FormatBTagsOperation, FormatTextOperation, Location, Operation, ParagraphMatch, ReplaceTextOperation, TextFormat};
    use std::io::Cursor;

    fn plan(search: &str, replacement: &str) -> EditPlan {
        EditPlan { operations: vec![Operation::ReplaceText(ReplaceTextOperation { id: "replace".into(), location: Location::Body, search: search.into(), replacement: replacement.into() })] }
    }

    fn format_plan() -> EditPlan {
        EditPlan { operations: vec![Operation::FormatBTags(FormatBTagsOperation { id: "format".into(), location: Location::Body })] }
    }

    fn text_format_plan() -> EditPlan {
        EditPlan { operations: vec![Operation::FormatText(FormatTextOperation {
            id: "format".into(), location: Location::Body, search: "target".into(),
            format: TextFormat {
                bold: Some(true), italic: Some(true), underline: Some(false), strike: Some(true),
                color: Some("FF0000".into()), highlight: Some("yellow".into()), font_name: Some("Aptos".into()),
                size_half_points: Some(27),
            },
        })] }
    }

    #[test]
    fn replaces_across_runs_and_keeps_the_first_run_properties() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:rPr><w:b/></w:rPr><w:t>Dear {{customer</w:t></w:r><w:r><w:t>_name}}</w:t></w:r></w:p>"#;
        let (result, stats) = transform_paragraph(xml, &plan("{{customer_name}}", "Alice"), ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("<w:t>Dear Alice</w:t>"));
        assert!(result.contains("<w:t></w:t>"));
        assert!(result.contains("<w:b/>"));
        assert_eq!(stats.matches, 1);
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn rejects_structural_boundaries() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:t>A</w:t><w:tab/><w:t>B</w:t></w:r></w:p>"#;
        assert!(transform_paragraph(xml, &plan("A", "B"), ParagraphLocation::Body).is_err());
    }

    #[test]
    fn preserves_bookmarks_when_a_replacement_does_not_cross_them() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:bookmarkStart w:id="1" w:name="keep"/><w:r><w:t>A</w:t></w:r><w:bookmarkEnd w:id="1"/><w:r><w:t>B</w:t></w:r></w:p>"#;
        let (result, _) = transform_paragraph(xml, &plan("A", "X"), ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("bookmarkStart"));
        assert!(result.contains("<w:t>X</w:t>"));
        assert!(transform_paragraph(xml, &plan("AB", "X"), ParagraphLocation::Body).is_err());
    }

    #[test]
    fn preserves_boundary_whitespace_from_literal_replacements() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:t>X</w:t></w:r></w:p>"#;
        let (result, _) = transform_paragraph(xml, &plan("X", " X "), ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("xml:space=\"preserve\""));
        assert!(result.contains("> X </w:t>"));
    }

    #[test]
    fn rebases_bookmarks_between_literal_operations() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:t>A</w:t></w:r><w:bookmarkStart w:id="1" w:name="keep"/><w:r><w:t>B</w:t></w:r></w:p>"#;
        let plan = EditPlan { operations: vec![
            Operation::ReplaceText(ReplaceTextOperation { id: "grow".into(), location: Location::Body, search: "A".into(), replacement: "LONG".into() }),
            Operation::ReplaceText(ReplaceTextOperation { id: "cross".into(), location: Location::Body, search: "LONGB".into(), replacement: "X".into() }),
        ] };
        assert!(transform_paragraph(xml, &plan, ParagraphLocation::Body).is_err());
    }

    #[test]
    fn removes_nested_tags_and_bolds_only_the_enclosed_text() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:rPr><w:i/></w:rPr><w:t>before &lt;B&gt;bold &lt;B&gt;more&lt;D&gt; text&lt;D&gt; after</w:t></w:r></w:p>"#;
        let (result, stats) = transform_paragraph(xml, &format_plan(), ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(!result.contains("&lt;B&gt;") && !result.contains("&lt;D&gt;"));
        assert!(result.contains("before "));
        assert!(result.contains("bold "));
        assert!(result.contains("bold more text"));
        assert_eq!(result.matches("<w:b/>").count(), 1);
        assert_eq!(stats.matches, 2);
        assert_eq!(stats.modifications, 2);
    }

    #[test]
    fn preserves_rendered_page_break_on_the_first_split_run() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:rPr/><w:lastRenderedPageBreak/><w:t>&lt;B&gt;bold&lt;D&gt; after</w:t></w:r></w:p>"#;
        let (result, _) = transform_paragraph(xml, &format_plan(), ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert_eq!(result.matches("lastRenderedPageBreak").count(), 1);
        assert!(result.contains("<w:b/>"));
    }

    #[test]
    fn expands_empty_run_properties_and_overrides_disabled_bold() {
        let empty = br#"<w:p xmlns:w="urn:word"><w:r><w:rPr/><w:t>&lt;B&gt;x&lt;D&gt;</w:t></w:r></w:p>"#;
        let (result, _) = transform_paragraph(empty, &format_plan(), ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert_eq!(result.matches("<w:rPr").count(), 1);
        assert!(result.contains("<w:rPr><w:b/></w:rPr>"));

        let disabled = br#"<w:p xmlns:w="urn:word"><w:r><w:rPr><w:b w:val="0"/></w:rPr><w:t>&lt;B&gt;x&lt;D&gt;</w:t></w:r></w:p>"#;
        let (result, _) = transform_paragraph(disabled, &format_plan(), ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("w:val=\"0\""));
        assert!(result.contains("<w:b/>"));
    }

    #[test]
    fn applies_literal_formatting_without_changing_surrounding_text() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:t>before target after</w:t></w:r></w:p>"#;
        let (result, stats) = transform_paragraph(xml, &text_format_plan(), ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("before "));
        assert!(result.contains("<w:t>target</w:t>"));
        assert!(result.contains(" after"));
        assert!(result.contains("<w:b/>"));
        assert!(result.contains("<w:i/>"));
        assert!(result.contains("<w:u w:val=\"none\"/>"));
        assert!(result.contains("<w:strike/>"));
        assert!(result.contains("<w:color w:val=\"FF0000\"/>"));
        assert!(result.contains("<w:highlight w:val=\"yellow\"/>"));
        assert!(result.contains("<w:rFonts w:ascii=\"Aptos\" w:hAnsi=\"Aptos\" w:eastAsia=\"Aptos\" w:cs=\"Aptos\"/>"));
        assert!(result.contains("<w:sz w:val=\"27\"/>"));
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn deletes_only_matching_body_paragraphs() {
        let xml = br#"<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>keep</w:t></w:r></w:p><w:p><w:r><w:t>TODO: remove</w:t></w:r></w:p></w:body></w:document>"#;
        let plan = EditPlan { operations: vec![Operation::DeleteParagraphs(DeleteParagraphsOperation {
            id: "delete_todos".into(), location: Location::Body, matcher: ParagraphMatch::StartsWith("TODO:".into()),
        })] };
        let mut output = Vec::new();
        let stats = transform_document(Cursor::new(xml), &mut output, &plan, PartKind::MainDocument).unwrap();
        let output = String::from_utf8(output).unwrap();
        assert!(output.contains("keep"));
        assert!(!output.contains("TODO: remove"));
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn replaces_regex_captures_across_runs() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:t>01.02.</w:t></w:r><w:r><w:t>2003</w:t></w:r></w:p>"#;
        let plan = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"date","type":"regex_replace","locations":["body"],"pattern":"(\\d{2})\\.(\\d{2})\\.(\\d{4})","replacement":"$3-$2-$1","case_insensitive":false}]}"#).unwrap();
        let (result, stats) = transform_paragraph(xml, &plan, ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("2003-02-01"));
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn removes_custom_tags_and_applies_the_requested_format() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:t>before &lt;strong&gt;target&lt;/strong&gt; after</w:t></w:r></w:p>"#;
        let plan = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"strong","type":"format_tagged","locations":["body"],"open_tag":"<strong>","close_tag":"</strong>","format":{"bold":true,"italic":true}}]}"#).unwrap();
        let (result, stats) = transform_paragraph(xml, &plan, ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(!result.contains("&lt;strong&gt;") && !result.contains("&lt;/strong&gt;"));
        assert!(result.contains("<w:t>target</w:t>"));
        assert!(result.contains("<w:b/>") && result.contains("<w:i/>"));
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn assigns_an_existing_style_to_matching_paragraphs() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:t>Title</w:t></w:r></w:p>"#;
        let plan = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"title","type":"set_paragraph_style","locations":["body"],"match":{"mode":"exact","text":"Title"},"style_id":"Heading1"}]}"#).unwrap();
        let (result, stats) = transform_paragraph(xml, &plan, ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("<w:pStyle w:val=\"Heading1\"/>"));
        assert!(result.contains("<w:jc w:val=\"center\"/>"));
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn formats_every_text_run_in_matching_paragraphs() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:t>Important: </w:t></w:r><w:r><w:t>read this</w:t></w:r></w:p>"#;
        let plan = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"important","type":"format_paragraphs","locations":["body"],"match":{"mode":"starts_with","text":"Important:"},"format":{"bold":true,"color":"FF0000"}}]}"#).unwrap();
        let (result, stats) = transform_paragraph(xml, &plan, ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert_eq!(result.matches("<w:b/>").count(), 2);
        assert_eq!(result.matches("<w:color w:val=\"FF0000\"/>").count(), 2);
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn sets_paragraph_layout_without_losing_existing_properties() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:pPr><w:spacing w:line="240" w:after="40"/><w:jc w:val="left"/></w:pPr><w:r><w:t>Title</w:t></w:r></w:p>"#;
        let plan = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"layout","type":"set_paragraph_layout","locations":["body"],"match":{"mode":"exact","text":"Title"},"layout":{"alignment":"center","space_after_pt":12,"left_indent_pt":18}}]}"#).unwrap();
        let (result, stats) = transform_paragraph(xml, &plan, ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("<w:jc w:val=\"center\"/>"));
        assert!(result.contains("<w:spacing w:line=\"240\" w:after=\"240\"/>"));
        assert!(result.contains("<w:ind w:left=\"360\"/>"));
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn sets_existing_numbering_and_pagination_without_losing_paragraph_properties() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:pPr><w:pStyle w:val="Heading1"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Step one</w:t></w:r></w:p>"#;
        let numbering = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"numbers","type":"set_paragraph_numbering","locations":["body"],"match":{"mode":"starts_with","text":"Step"},"num_id":5,"level":2}]}"#).unwrap();
        let (result, stats) = transform_paragraph(xml, &numbering, ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("<w:pStyle w:val=\"Heading1\"/>"));
        assert!(result.contains("<w:numPr><w:ilvl w:val=\"2\"/><w:numId w:val=\"5\"/></w:numPr>"));
        assert_eq!(stats.modifications, 1);

        let pagination = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"keep","type":"set_paragraph_pagination","locations":["body"],"match":{"mode":"exact","text":"Step one"},"pagination":{"keep_with_next":true,"keep_together":true,"page_break_before":false}}]}"#).unwrap();
        let (result, stats) = transform_paragraph(result.as_bytes(), &pagination, ParagraphLocation::Body).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("<w:keepNext w:val=\"1\"/>"));
        assert!(result.contains("<w:keepLines w:val=\"1\"/>"));
        assert!(result.contains("<w:pageBreakBefore w:val=\"0\"/>"));
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn inserts_styled_paragraphs_after_each_matching_anchor() {
        let xml = br#"<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>Introduction</w:t></w:r></w:p></w:body></w:document>"#;
        let plan = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"insert","type":"insert_paragraphs","locations":["body"],"anchor":{"mode":"exact","text":"Introduction"},"position":"after","paragraphs":[{"text":"New section","style_id":"Heading1","page_break_before":true,"format":{"bold":true}},{"text":"Body text"}]}]}"#).unwrap();
        let mut output = Vec::new();
        let stats = transform_document(Cursor::new(xml), &mut output, &plan, PartKind::MainDocument).unwrap();
        let output = String::from_utf8(output).unwrap();
        assert!(output.contains("Introduction</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val=\"Heading1\"/>"));
        assert!(output.contains("New section") && output.contains("Body text"));
        assert!(output.contains("<w:pageBreakBefore/>"));
        assert!(output.contains("<w:rPr><w:b/></w:rPr>"));
        assert_eq!(stats.modifications, 2);
    }

    #[test]
    fn deletes_complete_matching_table_rows_without_touching_other_rows() {
        let xml = br#"<w:document xmlns:w=\"urn:word\"><w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Keep this row</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>Item DISCONTINUED</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>Keep this too</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>"#;
        let plan = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"delete_row","type":"delete_table_rows","locations":["tables"],"match":{"mode":"contains","text":"DISCONTINUED"}}]}"#).unwrap();
        let mut output = Vec::new();
        let stats = transform_document(Cursor::new(xml), &mut output, &plan, PartKind::MainDocument).unwrap();
        let output = String::from_utf8(output).unwrap();
        assert!(output.contains("Keep this row") && output.contains("Keep this too"));
        assert!(!output.contains("DISCONTINUED"));
        assert_eq!(output.matches("<w:tr>").count(), 2);
        assert_eq!(stats.matches, 1);
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn formats_matching_table_cells_without_losing_existing_cell_properties() {
        let xml = br#"<w:document xmlns:w="urn:word"><w:body><w:tbl><w:tr><w:tc><w:tcPr><w:tcW w:w="2400" w:type="dxa"/><w:shd w:val="clear" w:fill="FFFFFF"/></w:tcPr><w:p><w:r><w:t>Total</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Other</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>"#;
        let plan = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"format_cell","type":"set_table_cell_format","locations":["tables"],"match":{"mode":"exact","text":"Total"},"format":{"fill_color":"FFF2CC","vertical_alignment":"center","border_color":"7F6000","border_size_pt":0.5}}]}"#).unwrap();
        let mut output = Vec::new();
        let stats = transform_document(Cursor::new(xml), &mut output, &plan, PartKind::MainDocument).unwrap();
        let output = String::from_utf8(output).unwrap();
        assert!(output.contains("<w:tcW w:w=\"2400\" w:type=\"dxa\"/>"));
        assert!(output.contains("<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"FFF2CC\"/>"));
        assert!(output.contains("<w:vAlign w:val=\"center\"/>"));
        assert!(output.contains("<w:tcBorders><w:top w:val=\"single\" w:sz=\"4\" w:color=\"7F6000\"/><w:left w:val=\"single\" w:sz=\"4\" w:color=\"7F6000\"/><w:bottom w:val=\"single\" w:sz=\"4\" w:color=\"7F6000\"/><w:right w:val=\"single\" w:sz=\"4\" w:color=\"7F6000\"/></w:tcBorders>"));
        assert_eq!(output.matches("w:vAlign").count(), 1);
        assert_eq!(stats.matches, 1);
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn clones_template_rows_and_supplies_cell_values() {
        let xml = br#"<w:document xmlns:w="urn:word"><w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Template item</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>0</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>"#;
        let plan = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"insert","type":"insert_table_rows","locations":["tables"],"anchor":{"mode":"contains","text":"Template item"},"position":"after","rows":[{"cells":["Widget","2"]}]}]}"#).unwrap();
        let mut output = Vec::new();
        let stats = transform_document(Cursor::new(xml), &mut output, &plan, PartKind::MainDocument).unwrap();
        let output = String::from_utf8(output).unwrap();
        assert_eq!(output.matches("<w:tr>").count(), 2);
        assert!(output.contains("Template item") && output.contains("Widget") && output.contains(">2</w:t>"));
        assert_eq!(stats.matches, 1);
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn sets_table_row_height_and_merges_cells_to_the_right() {
        let xml = br#"<w:document xmlns:w="urn:word"><w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Summary</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Details</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Amount</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>"#;
        let height = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"height","type":"set_table_row_height","locations":["tables"],"match":{"mode":"contains","text":"Summary"},"height_pt":24,"rule":"exact"}]}"#).unwrap();
        let mut sized = Vec::new();
        let stats = transform_document(Cursor::new(xml), &mut sized, &height, PartKind::MainDocument).unwrap();
        let sized = String::from_utf8(sized).unwrap();
        assert!(sized.contains("<w:trPr><w:trHeight w:val=\"480\" w:hRule=\"exact\"/></w:trPr>"));
        assert_eq!(stats.modifications, 1);

        let merge = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"merge","type":"merge_table_cells","locations":["tables"],"match":{"mode":"exact","text":"Summary"},"direction":"right","span":2}]}"#).unwrap();
        let mut merged = Vec::new();
        let stats = transform_document(Cursor::new(xml), &mut merged, &merge, PartKind::MainDocument).unwrap();
        let merged = String::from_utf8(merged).unwrap();
        assert!(merged.contains("<w:gridSpan w:val=\"2\"/>"));
        assert_eq!(merged.matches("<w:tc>").count(), 2);
        assert!(merged.contains("Summary") && merged.contains("Details") && merged.contains("Amount"));
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn updates_table_grid_widths_and_merges_cells_downward() {
        let xml = br#"<w:document xmlns:w="urn:word"><w:body><w:tbl><w:tblGrid><w:gridCol w:w="1000"/><w:gridCol w:w="1000"/></w:tblGrid><w:tr><w:tc><w:p><w:r><w:t>Summary</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>Detail</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>"#;
        let width = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"width","type":"set_table_column_width","locations":["tables"],"match":{"mode":"contains","text":"Summary"},"column_index":1,"width_pt":96}]}"#).unwrap();
        let mut output = Vec::new();
        transform_document(Cursor::new(xml), &mut output, &width, PartKind::MainDocument).unwrap();
        assert!(String::from_utf8(output).unwrap().contains("<w:gridCol w:w=\"1920\"/>"));

        let down = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"merge","type":"merge_table_cells","locations":["tables"],"match":{"mode":"exact","text":"Summary"},"direction":"down","span":2}]}"#).unwrap();
        let mut output = Vec::new();
        transform_document(Cursor::new(xml), &mut output, &down, PartKind::MainDocument).unwrap();
        let output = String::from_utf8(output).unwrap();
        assert!(output.contains("<w:vMerge w:val=\"restart\"/>"));
        assert!(output.contains("<w:vMerge/>"));
    }

    #[test]
    fn streams_edits_to_only_the_requested_document_locations() {
        let xml = br#"<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>A</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>"#;
        let plan = EditPlan { operations: vec![Operation::ReplaceText(ReplaceTextOperation {
            id: "table".into(), location: Location::Tables, search: "A".into(), replacement: "X".into(),
        })] };
        let mut output = Vec::new();
        let stats = transform_document(Cursor::new(xml), &mut output, &plan, PartKind::MainDocument).unwrap();
        let output = String::from_utf8(output).unwrap();
        assert!(output.contains("<w:p><w:r><w:t>A</w:t></w:r></w:p><w:tbl>"));
        assert!(output.contains("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>X</w:t>"));
        assert_eq!(stats.modifications, 1);
    }

    #[test]
    fn transforms_header_and_footer_parts_when_requested() {
        let xml = br#"<w:hdr xmlns:w="urn:word"><w:p><w:r><w:t>A</w:t></w:r></w:p></w:hdr>"#;
        let plan = EditPlan { operations: vec![Operation::ReplaceText(ReplaceTextOperation {
            id: "header".into(), location: Location::HeadersFooters, search: "A".into(), replacement: "X".into(),
        })] };
        let mut output = Vec::new();
        transform_document(Cursor::new(xml), &mut output, &plan, PartKind::HeaderFooter).unwrap();
        assert!(String::from_utf8(output).unwrap().contains("<w:t>X</w:t>"));
    }

    #[test]
    fn inserts_paragraphs_in_header_and_footer_parts() {
        let xml = br#"<w:hdr xmlns:w=\"urn:word\"><w:p><w:r><w:t>Company</w:t></w:r></w:p></w:hdr>"#;
        let plan = crate::plan::validate_plan_json(br#"{"schema_version":1,"operations":[{"id":"insert_header","type":"insert_paragraphs","locations":["headers_footers"],"anchor":{"mode":"exact","text":"Company"},"position":"after","paragraphs":[{"text":"Confidential","format":{"bold":true}}]}]}"#).unwrap();
        let mut output = Vec::new();
        let stats = transform_document(Cursor::new(xml), &mut output, &plan, PartKind::HeaderFooter).unwrap();
        let output = String::from_utf8(output).unwrap();
        assert!(output.contains("Company</w:t></w:r></w:p><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Confidential</w:t>"));
        assert_eq!(stats.modifications, 1);
    }
}
