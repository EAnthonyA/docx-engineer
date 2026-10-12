mod plan;
mod package;
mod script;

use std::{env, fs, process::ExitCode};

use serde::Serialize;

#[derive(Serialize)]
struct Capabilities<'a> {
    engine: &'a str,
    engine_version: &'a str,
    schema_versions: [u8; 1],
    operations: [&'a str; 18],
    locations: [&'a str; 4],
    script_language: &'a str,
    script_operation_limit: u8,
}

fn main() -> ExitCode {
    let args: Vec<_> = env::args_os().skip(1).collect();
    match args.as_slice() {
        [flag] if flag == "--capabilities" => {
            let capabilities = Capabilities {
                engine: "rust-docx",
                engine_version: env!("CARGO_PKG_VERSION"),
                schema_versions: [plan::SCHEMA_VERSION],
                operations: ["replace_text", "format_b_tags", "format_text", "delete_paragraphs", "regex_replace", "format_tagged", "set_paragraph_style", "format_paragraphs", "set_paragraph_layout", "set_paragraph_numbering", "set_paragraph_pagination", "delete_table_rows", "set_table_cell_format", "insert_table_rows", "set_table_row_height", "merge_table_cells", "set_table_column_width", "insert_paragraphs"],
                locations: ["body", "tables", "headers_footers", "all"],
                script_language: "rhai",
                script_operation_limit: 32,
            };
            match serde_json::to_string(&capabilities) {
                Ok(value) => println!("{value}"),
                Err(_) => return ExitCode::from(1),
            }
            ExitCode::SUCCESS
        }
        [flag, path] if flag == "--validate-plan" => validate_plan(path),
        [flag, path] if flag == "--compile-script" => compile_script(path),
        [input_flag, input, script_flag, script_path, output_flag, output]
            if input_flag == "--input" && script_flag == "--script" && output_flag == "--output" => {
            transform_script(input, script_path, output)
        }
        [input_flag, input, plan_flag, plan_path, output_flag, output]
            if input_flag == "--input" && plan_flag == "--plan" && output_flag == "--output" => {
            transform(input, plan_path, output)
        }
        _ => {
            eprintln!("usage: rust-docx --capabilities | --validate-plan PLAN.json | --compile-script SCRIPT.rhai | --input IN.docx (--plan PLAN.json | --script SCRIPT.rhai) --output OUT.docx");
            ExitCode::from(2)
        }
    }
}

fn transform_script(input: &std::ffi::OsString, script_path: &std::ffi::OsString, output: &std::ffi::OsString) -> ExitCode {
    let source = match fs::read_to_string(script_path) { Ok(source) => source, Err(_) => return ExitCode::from(2) };
    let operations = match script::compile_operations(&source) { Ok(operations) => operations, Err(error) => { eprintln!("error: {error}"); return ExitCode::from(2); } };
    if operations.is_empty() { eprintln!("error: script produced no edits"); return ExitCode::from(2); }
    let operation_count = operations.len();
    let output = std::path::Path::new(output);
    let mut current = std::path::PathBuf::from(input);
    let mut temporary = Vec::new();
    for (index, operation) in operations.into_iter().enumerate() {
        let bytes = match serde_json::to_vec(&serde_json::json!({"schema_version": 1, "operations": [operation]})) { Ok(bytes) => bytes, Err(_) => return ExitCode::from(2) };
        let plan = match plan::validate_plan_json(&bytes) { Ok(plan) => plan, Err(error) => { eprintln!("error: {}", error.code()); return ExitCode::from(2); } };
        let next = if index + 1 == operation_count { output.to_path_buf() } else { output.with_extension(format!("script-{index}.docx")) };
        if let Err(error) = package::transform(&current, &next, &plan) { eprintln!("error: {error}"); return ExitCode::from(1); }
        if current != std::path::Path::new(input) { temporary.push(current); }
        current = next;
    }
    for path in temporary { let _ = fs::remove_file(path); }
    ExitCode::SUCCESS
}

fn compile_script(path: &std::ffi::OsString) -> ExitCode {
    let source = match fs::read_to_string(path) { Ok(source) => source, Err(_) => return ExitCode::from(2) };
    match script::compile(&source) { Ok(plan) => { println!("{}", String::from_utf8_lossy(&plan)); ExitCode::SUCCESS }, Err(error) => { eprintln!("error: {error}"); ExitCode::from(2) } }
}

fn transform(input: &std::ffi::OsString, plan_path: &std::ffi::OsString, output: &std::ffi::OsString) -> ExitCode {
    let contents = match fs::read(plan_path) {
        Ok(contents) => contents,
        Err(_) => {
            eprintln!("error: cannot read plan");
            return ExitCode::from(2);
        }
    };
    let plan = match plan::validate_plan_json(&contents) {
        Ok(plan) => plan,
        Err(error) => {
            eprintln!("error: {}", error.code());
            return ExitCode::from(2);
        }
    };
    match package::transform(std::path::Path::new(input), std::path::Path::new(output), &plan) {
        Ok(report) => match serde_json::to_string(&report) {
            Ok(report) => {
                println!("{report}");
                ExitCode::SUCCESS
            }
            Err(_) => ExitCode::from(1),
        },
        Err(error) => {
            eprintln!("error: {error}");
            ExitCode::from(1)
        }
    }
}

fn validate_plan(path: &std::ffi::OsString) -> ExitCode {
    let contents = match fs::read(path) {
        Ok(contents) => contents,
        Err(_) => {
            eprintln!("error: cannot read plan");
            return ExitCode::from(2);
        }
    };
    match plan::validate_plan_json(&contents) {
        Ok(_) => {
            println!("{{\"valid\":true,\"schema_version\":1}}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("error: {}", error.code());
            ExitCode::from(2)
        }
    }
}
