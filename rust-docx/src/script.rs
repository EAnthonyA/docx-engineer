//! A deliberately small Rhai surface that compiles to validated edit-plan
//! operations. Rhai has no filesystem, process, or network APIs registered
//! here; scripts can only emit one of the document operations below.

use std::sync::{Arc, Mutex};

use rhai::{Engine, EvalAltResult};
use serde_json::{json, Value};

const MAX_SCRIPT_BYTES: usize = 128 * 1024;
const MAX_SCRIPT_OPERATIONS: usize = 32;

type Operations = Arc<Mutex<Vec<Value>>>;

pub fn compile_operations(source: &str) -> Result<Vec<Value>, Box<EvalAltResult>> {
    if source.len() > MAX_SCRIPT_BYTES {
        return Err("script exceeds the 128 KiB limit".into());
    }
    let operations = Arc::new(Mutex::new(Vec::<Value>::new()));
    let mut engine = Engine::new();
    engine.set_max_operations(20_000);
    engine.set_max_call_levels(32);
    engine.set_max_string_size(64 * 1024);
    engine.set_max_array_size(1_024);
    engine.set_max_map_size(128);

    register_document_api(&mut engine, &operations);
    engine.eval::<()>(source)?;
    drop(engine);
    Arc::try_unwrap(operations)
        .map_err(|_| "script operation state is still shared")?
        .into_inner()
        .map_err(|_| "script operation state is poisoned".into())
}

pub fn compile(source: &str) -> Result<Vec<u8>, Box<EvalAltResult>> {
    serde_json::to_vec(&json!({"schema_version": 1, "operations": compile_operations(source)?}))
        .map_err(|_| "cannot encode script plan".into())
}

fn register_document_api(engine: &mut Engine, operations: &Operations) {
    register_replace(engine, operations);
    register_formatting(engine, operations);
    register_paragraphs(engine, operations);
    register_tables(engine, operations);
}

fn register_replace(engine: &mut Engine, operations: &Operations) {
    let target = Arc::clone(operations);
    engine.register_fn("replace_text", move |search: &str, replacement: &str, location: &str| {
        emit(&target, "replace_text", json!({"locations":[location], "search":search, "replacement":replacement, "match_case":true}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("regex_replace", move |pattern: &str, replacement: &str, location: &str| {
        emit(&target, "regex_replace", json!({"locations":[location], "pattern":pattern, "replacement":replacement, "case_insensitive":false}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("delete_paragraphs", move |text: &str, mode: &str| {
        emit(&target, "delete_paragraphs", json!({"locations":["body"], "match":{"mode":mode, "text":text}}))
    });
}

fn register_formatting(engine: &mut Engine, operations: &Operations) {
    let target = Arc::clone(operations);
    engine.register_fn("format_b_tags", move |location: &str| {
        emit(&target, "format_b_tags", json!({"locations":[location], "open_tag":"<B>", "close_tag":"<D>", "bold":true}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("format_tagged", move |open_tag: &str, close_tag: &str, location: &str, bold: bool| {
        emit(&target, "format_tagged", json!({"locations":[location], "open_tag":open_tag, "close_tag":close_tag, "format":{"bold":bold}}))
    });
    register_text_format(engine, operations, "set_bold", "bold");
    register_text_format(engine, operations, "set_italic", "italic");
    register_text_format(engine, operations, "set_underline", "underline");
    register_text_format(engine, operations, "set_strike", "strike");
    register_text_string_format(engine, operations, "set_text_color", "color");
    register_text_string_format(engine, operations, "set_text_highlight", "highlight");
    register_text_string_format(engine, operations, "set_text_font", "font_name");
    let target = Arc::clone(operations);
    engine.register_fn("set_text_size_pt", move |search: &str, size_pt: f64, location: &str| {
        emit(&target, "format_text", json!({"locations":[location], "search":search, "match_case":true, "format":{"size_pt":size_pt}}))
    });
}

fn register_text_format(engine: &mut Engine, operations: &Operations, function: &str, field: &'static str) {
    let target = Arc::clone(operations);
    engine.register_fn(function, move |search: &str, location: &str| {
        let mut format = serde_json::Map::new();
        format.insert(field.to_string(), json!(true));
        emit(&target, "format_text", json!({"locations":[location], "search":search, "match_case":true, "format":format}))
    });
}

fn register_text_string_format(engine: &mut Engine, operations: &Operations, function: &str, field: &'static str) {
    let target = Arc::clone(operations);
    engine.register_fn(function, move |search: &str, value: &str, location: &str| {
        let mut format = serde_json::Map::new();
        format.insert(field.to_string(), json!(value));
        emit(&target, "format_text", json!({"locations":[location], "search":search, "match_case":true, "format":format}))
    });
}

fn register_paragraphs(engine: &mut Engine, operations: &Operations) {
    let target = Arc::clone(operations);
    engine.register_fn("set_paragraph_style", move |text: &str, mode: &str, location: &str, style_id: &str| {
        emit(&target, "set_paragraph_style", json!({"locations":[location], "match":{"mode":mode, "text":text}, "style_id":style_id}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("format_paragraphs_bold", move |text: &str, mode: &str, location: &str| {
        emit(&target, "format_paragraphs", json!({"locations":[location], "match":{"mode":mode, "text":text}, "format":{"bold":true}}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("set_paragraph_alignment", move |text: &str, mode: &str, location: &str, alignment: &str| {
        emit(&target, "set_paragraph_layout", json!({"locations":[location], "match":{"mode":mode, "text":text}, "layout":{"alignment":alignment}}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("insert_paragraph_after", move |anchor: &str, mode: &str, location: &str, text: &str, style_id: &str| {
        let paragraph = if style_id.is_empty() { json!({"text":text}) } else { json!({"text":text, "style_id":style_id}) };
        emit(&target, "insert_paragraphs", json!({"locations":[location], "anchor":{"mode":mode, "text":anchor}, "position":"after", "paragraphs":[paragraph]}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("set_paragraph_numbering", move |text: &str, mode: &str, num_id: i64, level: i64| {
        emit(&target, "set_paragraph_numbering", json!({"locations":["body"], "match":{"mode":mode, "text":text}, "num_id":num_id, "level":level}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("set_paragraph_pagination", move |text: &str, mode: &str, keep_with_next: bool, keep_together: bool, page_break_before: bool| {
        emit(&target, "set_paragraph_pagination", json!({"locations":["body"], "match":{"mode":mode, "text":text}, "pagination":{"keep_with_next":keep_with_next, "keep_together":keep_together, "page_break_before":page_break_before}}))
    });
}

fn register_tables(engine: &mut Engine, operations: &Operations) {
    let target = Arc::clone(operations);
    engine.register_fn("delete_table_rows", move |text: &str, mode: &str| {
        emit(&target, "delete_table_rows", json!({"locations":["tables"], "match":{"mode":mode, "text":text}}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("set_table_cell_fill", move |text: &str, mode: &str, fill_color: &str| {
        emit(&target, "set_table_cell_format", json!({"locations":["tables"], "match":{"mode":mode, "text":text}, "format":{"fill_color":fill_color}}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("insert_table_row_after", move |anchor: &str, mode: &str, cell_1: &str, cell_2: &str, cell_3: &str| {
        emit(&target, "insert_table_rows", json!({"locations":["tables"], "anchor":{"mode":mode, "text":anchor}, "position":"after", "rows":[{"cells":[cell_1, cell_2, cell_3]}]}))
    });
    let target = Arc::clone(operations);
    engine.register_fn("set_table_row_height", move |text: &str, mode: &str, height_pt: i64, rule: &str| {
        emit(&target, "set_table_row_height", json!({"locations":["tables"], "match":{"mode":mode, "text":text}, "height_pt":height_pt, "rule":rule}))
    });
    register_merge(engine, operations, "merge_table_cells_right", "right");
    register_merge(engine, operations, "merge_table_cells_down", "down");
    let target = Arc::clone(operations);
    engine.register_fn("set_table_column_width", move |text: &str, mode: &str, column_index: i64, width_pt: i64| {
        emit(&target, "set_table_column_width", json!({"locations":["tables"], "match":{"mode":mode, "text":text}, "column_index":column_index, "width_pt":width_pt}))
    });
}

fn register_merge(engine: &mut Engine, operations: &Operations, function: &str, direction: &'static str) {
    let target = Arc::clone(operations);
    engine.register_fn(function, move |text: &str, mode: &str, span: i64| {
        emit(&target, "merge_table_cells", json!({"locations":["tables"], "match":{"mode":mode, "text":text}, "direction":direction, "span":span}))
    });
}

fn emit(operations: &Operations, kind: &str, mut operation: Value) -> Result<(), Box<EvalAltResult>> {
    let mut items = operations.lock().map_err(|_| "script operation state is poisoned")?;
    if items.len() >= MAX_SCRIPT_OPERATIONS {
        return Err("script exceeds the 32-operation limit".into());
    }
    let object = operation.as_object_mut().ok_or("invalid script operation")?;
    object.insert("id".to_string(), json!(format!("script_{}", items.len() + 1)));
    object.insert("type".to_string(), json!(kind));
    items.push(operation);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::compile;

    #[test]
    fn compiles_control_flow_into_a_strict_plan() {
        let plan = String::from_utf8(compile(
            "for location in [\"body\", \"headers_footers\"] { replace_text(\"TODO\", \"Done\", location); } set_bold(\"Done\", \"body\");",
        ).unwrap()).unwrap();
        assert!(plan.contains("replace_text") && plan.contains("format_text"));
    }

    #[test]
    fn caps_script_operations() {
        let source = "for item in 0..33 { replace_text(\"a\", \"b\", \"body\"); }";
        assert!(compile(source).is_err());
    }
}
