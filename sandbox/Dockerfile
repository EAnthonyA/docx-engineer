FROM rust:1.85-slim AS rust-builder

WORKDIR /build/rust-docx
COPY rust-docx/Cargo.toml rust-docx/Cargo.lock rust-docx/rust-toolchain.toml ./
COPY rust-docx/src ./src
RUN cargo build --release --locked

FROM rust-builder AS rust-test

RUN cargo test --locked

FROM debian:bookworm-slim AS sandbox-rust

RUN adduser --disabled-password --no-create-home appuser

WORKDIR /work

COPY --from=rust-builder /build/rust-docx/target/release/docx-engineer-rust /usr/local/bin/docx-engineer-rust

USER appuser

CMD ["/usr/local/bin/docx-engineer-rust", "--capabilities"]
