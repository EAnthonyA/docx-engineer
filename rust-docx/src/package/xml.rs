use std::{error::Error, io::{BufRead, Write}};

use quick_xml::{events::{BytesText, Event}, escape::unescape, Reader, Writer};

use crate::plan::{EditPlan, Operation};

const PARAGRAPH: &[u8] = b"w:p";
const TABLE: &[u8] = b"w:tbl";
const TEXT: &[u8] = b"w:t";
const UNSUPPORTED: &[&[u8]] = &[
    b"w:hyperlink", b"w:fldChar", b"w:instrText", b"w:tab", b"w:br", b"w:cr", b"w:drawing",
    b"w:commentRangeStart", b"w:commentRangeEnd", b"w:ins", b"w:del",
];
const BOOKMARKS: &[&[u8]] = &[b"w:bookmarkStart", b"w:bookmarkEnd"];

#[derive(Default)]
pub struct TransformStats {
    pub matches: usize,
    pub modifications: usize,
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
    bold: bool,
}

pub fn transform_document<R: BufRead, W: Write>(input: R, mut output: W, plan: &EditPlan) -> Result<TransformStats, Box<dyn Error>> {
    let mut reader = Reader::from_reader(input);
    reader.config_mut().trim_text(false);
    let mut writer = Writer::new(&mut output);
    let mut buffer = Vec::new();
    let mut paragraph = Vec::new();
    let mut paragraph_depth = 0usize;
    let mut table_depth = 0usize;
    let mut stats = TransformStats::default();

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
                    writer.write_event(event)?;
                }
            }
            Event::End(end) if end.name().as_ref() == TABLE && paragraph_depth == 0 => {
                table_depth = table_depth.saturating_sub(1);
                writer.write_event(event)?;
            }
            Event::Start(start) if start.name().as_ref() == PARAGRAPH && paragraph_depth == 0 && table_depth == 0 => {
                paragraph.clear();
                write_paragraph_event(&mut paragraph, event)?;
                paragraph_depth = 1;
            }
            Event::Start(_) if paragraph_depth > 0 => {
                write_paragraph_event(&mut paragraph, event)?;
                paragraph_depth += 1;
            }
            Event::End(_) if paragraph_depth > 0 => {
                write_paragraph_event(&mut paragraph, event)?;
                paragraph_depth -= 1;
                if paragraph_depth == 0 {
                    let (updated, paragraph_stats) = transform_paragraph(&paragraph, plan)?;
                    stats.matches += paragraph_stats.matches;
                    stats.modifications += paragraph_stats.modifications;
                    writer.get_mut().write_all(&updated)?;
                }
            }
            _ if paragraph_depth > 0 => write_paragraph_event(&mut paragraph, event)?,
            _ => writer.write_event(event)?,
        }
        buffer.clear();
    }
    Ok(stats)
}

fn write_paragraph_event(paragraph: &mut Vec<u8>, event: Event<'static>) -> Result<(), Box<dyn Error>> {
    Writer::new(paragraph).write_event(event)?;
    Ok(())
}

fn transform_paragraph(paragraph: &[u8], plan: &EditPlan) -> Result<(Vec<u8>, TransformStats), Box<dyn Error>> {
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

    let mut stats = TransformStats::default();
    let mut has_format_b_tags = false;
    for operation in &plan.operations {
        match operation {
            Operation::ReplaceText(operation) => {
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
            Operation::FormatBTags(_) => has_format_b_tags = true,
        }
    }
    let pieces = if has_format_b_tags {
        let boundaries = boundary_offsets(&segments, &boundary_events);
        let (pieces, format_stats) = format_b_tags(&segments, &boundaries)?;
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
    let mut result = Vec::with_capacity(paragraph.len());
    let mut writer = Writer::new(&mut result);
    for event in events {
        writer.write_event(event)?;
    }
    Ok((result, stats))
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

fn format_b_tags(segments: &[Segment], boundaries: &[usize]) -> Result<(Vec<Vec<Piece>>, TransformStats), Box<dyn Error>> {
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
        let open = source[cursor..].find("<B>").map(|offset| cursor + offset);
        let close = source[cursor..].find("<D>").map(|offset| cursor + offset);
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
            if boundaries.iter().any(|boundary| open_start < *boundary && *boundary < marker + 3) {
                return Err("format_tag_pair_crosses_bookmark_boundary".into());
            }
            depth -= 1;
            stats.matches += 1;
            stats.modifications += 1;
        }
        cursor = marker + 3;
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
                    if previous.bold == bold {
                        previous.text.push_str(&segment.text[from..to]);
                    } else {
                        result.push(Piece { text: segment.text[from..to].to_string(), bold });
                    }
                } else {
                    result.push(Piece { text: segment.text[from..to].to_string(), bold });
                }
            }
            index += 1;
        }
        if result.is_empty() {
            result.push(Piece { text: String::new(), bold: false });
        }
        pieces.push(result);
        offset = end;
    }
    Ok((pieces, stats))
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
                    || pieces[segment_index][0].bold
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
    let mut has_bold = false;
    for event in &events[run.start..=run.end] {
        match event {
            Event::Start(start) if start.name().as_ref() == b"w:rPr" => rpr_start = Some(()),
            Event::End(end) if end.name().as_ref() == b"w:rPr" => rpr_end = Some(()),
            Event::Empty(empty) if empty.name().as_ref() == b"w:rPr" => rpr_empty = Some(()),
            Event::Empty(empty) if empty.name().as_ref() == b"w:b" => has_bold = bold_enabled(empty),
            Event::Start(start) if start.name().as_ref() == b"w:b" => has_bold = bold_enabled(start),
            _ => {}
        }
    }
    if rpr_start.is_some() != rpr_end.is_some() || (rpr_empty.is_some() && rpr_start.is_some()) { return Err("malformed_run_properties".into()); }

    for (piece_index, piece) in pieces.iter().enumerate() {
        for index in run.start..=run.end {
            match &events[index] {
                Event::Start(_) if index == run.start => {
                    writer.write_event(events[index].clone())?;
                    if piece.bold && rpr_start.is_none() && rpr_empty.is_none() {
                        writer.write_event(Event::Start(quick_xml::events::BytesStart::new("w:rPr")))?;
                        writer.write_event(Event::Empty(quick_xml::events::BytesStart::new("w:b")))?;
                        writer.write_event(Event::End(quick_xml::events::BytesEnd::new("w:rPr")))?;
                    }
                }
                Event::Empty(empty) if empty.name().as_ref() == b"w:rPr" && piece.bold => {
                    writer.write_event(Event::Start(quick_xml::events::BytesStart::new("w:rPr")))?;
                    writer.write_event(Event::Empty(quick_xml::events::BytesStart::new("w:b")))?;
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
                    if piece.bold && !has_bold {
                        writer.write_event(Event::Empty(quick_xml::events::BytesStart::new("w:b")))?;
                    }
                    writer.write_event(events[index].clone())?;
                }
                _ => writer.write_event(events[index].clone())?,
            }
        }
    }
    Ok(())
}

fn bold_enabled(start: &quick_xml::events::BytesStart<'_>) -> bool {
    start.attributes().flatten().find(|attribute| attribute.key.as_ref() == b"w:val")
        .map(|attribute| !matches!(attribute.value.as_ref(), b"0" | b"false" | b"off"))
        .unwrap_or(true)
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
    use crate::plan::{EditPlan, FormatBTagsOperation, Operation, ReplaceTextOperation};

    fn plan(search: &str, replacement: &str) -> EditPlan {
        EditPlan { operations: vec![Operation::ReplaceText(ReplaceTextOperation { id: "replace".into(), search: search.into(), replacement: replacement.into() })] }
    }

    fn format_plan() -> EditPlan {
        EditPlan { operations: vec![Operation::FormatBTags(FormatBTagsOperation { id: "format".into() })] }
    }

    #[test]
    fn replaces_across_runs_and_keeps_the_first_run_properties() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:rPr><w:b/></w:rPr><w:t>Dear {{customer</w:t></w:r><w:r><w:t>_name}}</w:t></w:r></w:p>"#;
        let (result, stats) = transform_paragraph(xml, &plan("{{customer_name}}", "Alice")).unwrap();
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
        assert!(transform_paragraph(xml, &plan("A", "B")).is_err());
    }

    #[test]
    fn preserves_bookmarks_when_a_replacement_does_not_cross_them() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:bookmarkStart w:id="1" w:name="keep"/><w:r><w:t>A</w:t></w:r><w:bookmarkEnd w:id="1"/><w:r><w:t>B</w:t></w:r></w:p>"#;
        let (result, _) = transform_paragraph(xml, &plan("A", "X")).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("bookmarkStart"));
        assert!(result.contains("<w:t>X</w:t>"));
        assert!(transform_paragraph(xml, &plan("AB", "X")).is_err());
    }

    #[test]
    fn preserves_boundary_whitespace_from_literal_replacements() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:t>X</w:t></w:r></w:p>"#;
        let (result, _) = transform_paragraph(xml, &plan("X", " X ")).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("xml:space=\"preserve\""));
        assert!(result.contains("> X </w:t>"));
    }

    #[test]
    fn rebases_bookmarks_between_literal_operations() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:t>A</w:t></w:r><w:bookmarkStart w:id="1" w:name="keep"/><w:r><w:t>B</w:t></w:r></w:p>"#;
        let plan = EditPlan { operations: vec![
            Operation::ReplaceText(ReplaceTextOperation { id: "grow".into(), search: "A".into(), replacement: "LONG".into() }),
            Operation::ReplaceText(ReplaceTextOperation { id: "cross".into(), search: "LONGB".into(), replacement: "X".into() }),
        ] };
        assert!(transform_paragraph(xml, &plan).is_err());
    }

    #[test]
    fn removes_nested_tags_and_bolds_only_the_enclosed_text() {
        let xml = br#"<w:p xmlns:w="urn:word"><w:r><w:rPr><w:i/></w:rPr><w:t>before &lt;B&gt;bold &lt;B&gt;more&lt;D&gt; text&lt;D&gt; after</w:t></w:r></w:p>"#;
        let (result, stats) = transform_paragraph(xml, &format_plan()).unwrap();
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
        let (result, _) = transform_paragraph(xml, &format_plan()).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert_eq!(result.matches("lastRenderedPageBreak").count(), 1);
        assert!(result.contains("<w:b/>"));
    }

    #[test]
    fn expands_empty_run_properties_and_overrides_disabled_bold() {
        let empty = br#"<w:p xmlns:w="urn:word"><w:r><w:rPr/><w:t>&lt;B&gt;x&lt;D&gt;</w:t></w:r></w:p>"#;
        let (result, _) = transform_paragraph(empty, &format_plan()).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert_eq!(result.matches("<w:rPr").count(), 1);
        assert!(result.contains("<w:rPr><w:b/></w:rPr>"));

        let disabled = br#"<w:p xmlns:w="urn:word"><w:r><w:rPr><w:b w:val="0"/></w:rPr><w:t>&lt;B&gt;x&lt;D&gt;</w:t></w:r></w:p>"#;
        let (result, _) = transform_paragraph(disabled, &format_plan()).unwrap();
        let result = String::from_utf8(result).unwrap();
        assert!(result.contains("w:val=\"0\""));
        assert!(result.contains("<w:b/>"));
    }
}
