FROM rust:1.85-slim AS rust-builder

WORKDIR /build/rust-docx
COPY rust-docx/Cargo.toml rust-docx/Cargo.lock rust-docx/rust-toolchain.toml ./
COPY rust-docx/src ./src
RUN cargo build --release --locked

FROM python:3.12-slim

RUN pip install --no-cache-dir "python-docx==1.1.2" \
    && adduser --disabled-password --no-create-home appuser

WORKDIR /work

COPY sandbox/entrypoint.py /work/entrypoint.py
COPY sandbox/docxkit.py /work/docxkit.py
COPY sandbox/document_io.py /work/document_io.py
COPY --from=rust-builder /build/rust-docx/target/release/docx-engineer-rust /usr/local/bin/docx-engineer-rust

USER appuser

CMD ["python", "/work/entrypoint.py"]
