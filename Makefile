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
	docker compose exec -T \
	  -e JOBS_DIR=/tmp/docx-engineer-tests \
	  -e ADMIN_PASSWORD=testpass -e ADMIN_PASSWORD_HASH= \
	  -e SESSION_SECRET=test-secret \
	  backend pytest /app/tests -v -p no:cacheprovider

# Run the actual edit(doc, tools) contract against a disposable fixture.
test-sandbox:
	python3 scripts/smoke_sandbox.py

# Generate a bcrypt hash for ADMIN_PASSWORD_HASH
hash-password:
	@read -p "Password: " p && python3 -c "import bcrypt; print(bcrypt.hashpw('$$p'.encode(), bcrypt.gensalt()).decode())"
