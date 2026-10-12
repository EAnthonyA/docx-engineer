.PHONY: sandbox build run stop logs test-backend test-sandbox rust-test hash-password

# Build the Rust-only sandbox image (required before running)
sandbox:
	docker build --target sandbox-rust -t docx-sandbox-rust -f sandbox/Dockerfile .

# Build all dev images + sandbox
build: sandbox
	docker compose build

# Start dev stack (frontend + backend + executor)
run:
	docker compose up -d

stop:
	docker compose down

logs:
	docker compose logs -f

# Run backend tests
test-backend:
	docker compose exec -T \
	  -e JOBS_DIR=/tmp/docx-engineer-tests \
	  -e ADMIN_PASSWORD=testpass -e ADMIN_PASSWORD_HASH= \
	  -e SESSION_SECRET=test-secret \
	  backend pytest /app/tests -v -p no:cacheprovider

# Run the Rust worker against a disposable DOCX fixture.
test-sandbox:
	python3 scripts/smoke_sandbox.py

# Uses the pinned toolchain from rust-docx/rust-toolchain.toml.
rust-test:
	cargo test --manifest-path rust-docx/Cargo.toml --locked

# Generate a bcrypt hash for ADMIN_PASSWORD_HASH
hash-password:
	@read -p "Password: " p && python3 -c "import bcrypt; print(bcrypt.hashpw('$$p'.encode(), bcrypt.gensalt()).decode())"
