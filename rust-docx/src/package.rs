use std::{error::Error, fs::File, io::BufReader, path::{Path, PathBuf}};

use serde::Serialize;
use zip::{write::SimpleFileOptions, ZipArchive, ZipWriter};

use crate::plan::{EditPlan, Location};

mod xml;
use xml::{transform_document, PartKind, TransformStats};

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
            let part_kind = if file.name() == "word/document.xml" {
                Some(PartKind::MainDocument)
            } else if is_header_or_footer(file.name()) {
                Some(PartKind::HeaderFooter)
            } else {
                None
            };
            if let Some(part_kind) = part_kind.filter(|kind| plan_targets_part(plan, *kind)) {
                let options = SimpleFileOptions::default().compression_method(file.compression());
                writer.start_file(file.name(), options)?;
                let document_stats = transform_document(BufReader::new(file), &mut writer, plan, part_kind)?;
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

fn is_header_or_footer(name: &str) -> bool {
    name.starts_with("word/header") && name.ends_with(".xml")
        || name.starts_with("word/footer") && name.ends_with(".xml")
}

fn plan_targets_part(plan: &EditPlan, part: PartKind) -> bool {
    plan.operations.iter().any(|operation| {
        let location = match operation {
            crate::plan::Operation::ReplaceText(operation) => operation.location,
            crate::plan::Operation::FormatBTags(operation) => operation.location,
            crate::plan::Operation::FormatText(operation) => operation.location,
            crate::plan::Operation::DeleteParagraphs(operation) => operation.location,
            crate::plan::Operation::RegexReplace(operation) => operation.location,
            crate::plan::Operation::FormatTagged(operation) => operation.location,
            crate::plan::Operation::SetParagraphStyle(operation) => operation.location,
            crate::plan::Operation::FormatParagraphs(operation) => operation.location,
            crate::plan::Operation::SetParagraphLayout(operation) => operation.location,
            crate::plan::Operation::SetParagraphNumbering(operation) => operation.location,
            crate::plan::Operation::SetParagraphPagination(operation) => operation.location,
            crate::plan::Operation::DeleteTableRows(operation) => operation.location,
            crate::plan::Operation::SetTableCellFormat(operation) => operation.location,
            crate::plan::Operation::InsertTableRows(operation) => operation.location,
            crate::plan::Operation::SetTableRowHeight(operation) => operation.location,
            crate::plan::Operation::MergeTableCells(operation) => operation.location,
            crate::plan::Operation::SetTableColumnWidth(operation) => operation.location,
            crate::plan::Operation::InsertParagraphs(operation) => operation.location,
        };
        matches!(
            (part, location),
            (PartKind::MainDocument, Location::Body | Location::Tables | Location::All)
                | (PartKind::HeaderFooter, Location::HeadersFooters | Location::All)
        )
    })
}

fn partial_path(output: &Path) -> PathBuf {
    let mut partial = output.as_os_str().to_owned();
    partial.push(".partial");
    PathBuf::from(partial)
}
