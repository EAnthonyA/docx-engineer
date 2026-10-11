mod plan;
mod package;

use std::{env, fs, process::ExitCode};

use serde::Serialize;

#[derive(Serialize)]
struct Capabilities<'a> {
    engine: &'a str,
    engine_version: &'a str,
    schema_versions: [u8; 1],
    operations: [&'a str; 2],
    locations: [&'a str; 1],
}

fn main() -> ExitCode {
    let args: Vec<_> = env::args_os().skip(1).collect();
    match args.as_slice() {
        [flag] if flag == "--capabilities" => {
            let capabilities = Capabilities {
                engine: "rust-docx",
                engine_version: env!("CARGO_PKG_VERSION"),
                schema_versions: [plan::SCHEMA_VERSION],
                operations: ["replace_text", "format_b_tags"],
                locations: ["body"],
            };
            match serde_json::to_string(&capabilities) {
                Ok(value) => println!("{value}"),
                Err(_) => return ExitCode::from(1),
            }
            ExitCode::SUCCESS
        }
        [flag, path] if flag == "--validate-plan" => validate_plan(path),
        [input_flag, input, plan_flag, plan_path, output_flag, output]
            if input_flag == "--input" && plan_flag == "--plan" && output_flag == "--output" => {
            transform(input, plan_path, output)
        }
        _ => {
            eprintln!("usage: rust-docx --capabilities | --validate-plan PLAN.json | --input IN.docx --plan PLAN.json --output OUT.docx");
            ExitCode::from(2)
        }
    }
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
