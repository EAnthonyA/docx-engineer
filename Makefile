.PHONY: sandbox build run stop logs test-backend test-sandbox hash-password

# Build the sandbox image (required before running)
sandbox:
	docker build -t docx-sandbox ./sandbox

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
	docker compose exec backend pytest -v

# Quick sandbox smoke-test: run a no-op transform on a fixture docx
test-sandbox:
	@echo "Running sandbox smoke test..."
	@mkdir -p /tmp/sandbox-test/out
	@echo 'from docx import Document\ndef transform(inp, out):\n    doc = Document(inp)\n    doc.save(out)' > /tmp/sandbox-test/script.py
	@cp tests/fixtures/sample.docx /tmp/sandbox-test/in.docx 2>/dev/null || \
	  python3 -c "from docx import Document; d=Document(); d.add_paragraph('test'); d.save('/tmp/sandbox-test/in.docx')"
	docker run --rm \
	  --network none --read-only \
	  --tmpfs /tmp:size=64m \
	  --cap-drop ALL --security-opt no-new-privileges \
	  --memory 256m --cpus 1 --pids-limit 64 \
	  -v /tmp/sandbox-test/in.docx:/work/in.docx:ro \
	  -v /tmp/sandbox-test/out:/work/out:rw \
	  -v /tmp/sandbox-test/script.py:/work/script.py:ro \
	  docx-sandbox
	@echo "Sandbox test passed"

# Generate a bcrypt hash for ADMIN_PASSWORD_HASH
hash-password:
	@read -p "Password: " p && python3 -c "import bcrypt; print(bcrypt.hashpw('$$p'.encode(), bcrypt.gensalt()).decode())"
