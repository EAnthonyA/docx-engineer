use std::{error::Error, fs::File, io::BufReader, path::{Path, PathBuf}};

use serde::Serialize;
use zip::{write::SimpleFileOptions, ZipArchive, ZipWriter};

use crate::plan::EditPlan;

mod xml;
use xml::{transform_document, TransformStats};

#[derive(Debug, Serialize)]
pub struct TransformReport {
    pub matches: usize,
    pub modifications: usize,
    pub engine: &'static str,
    pub schema_version: u8,
}

pub fn transform(input: &Path, output: &Path, plan: &EditPlan) -> Result<TransformReport, Box<dyn Error>> {
    let partial = partial_path(output);
    let result = (|| -> Result<TransformReport, Box<dyn Error>> {
        let input_file = File::open(input)?;
        let mut archive = ZipArchive::new(input_file)?;
        if let Some(parent) = partial.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let output_file = File::create(&partial)?;
        let mut writer = ZipWriter::new(output_file);
        let mut stats = TransformStats::default();

        for index in 0..archive.len() {
            let file = archive.by_index(index)?;
            if file.name() == "word/document.xml" {
                let options = SimpleFileOptions::default().compression_method(file.compression());
                writer.start_file(file.name(), options)?;
                let document_stats = transform_document(BufReader::new(file), &mut writer, plan)?;
                stats.matches += document_stats.matches;
                stats.modifications += document_stats.modifications;
            } else {
                writer.raw_copy_file(file)?;
            }
        }
        writer.finish()?;
        std::fs::rename(&partial, output)?;
        Ok(TransformReport {
            matches: stats.matches,
            modifications: stats.modifications,
            engine: "rust-docx",
            schema_version: crate::plan::SCHEMA_VERSION,
        })
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&partial);
    }
    result
}

fn partial_path(output: &Path) -> PathBuf {
    let mut partial = output.as_os_str().to_owned();
    partial.push(".partial");
    PathBuf::from(partial)
}
