# docx-engineer

Upload a `.docx`, describe the edit in plain language, get back a modified file.

Gemini generates a `python-docx` script. The script runs in a hardened Docker sandbox (no network, no filesystem, all capabilities dropped). You review a before/after diff, then download.

## How it works

1. Upload `.docx` + type instruction ("make all headings bold")
2. Backend sends doc structure + instruction to Gemini
3. Gemini returns a `transform(input_path, output_path)` function
4. Executor runs it in a throwaway container: `--network none`, `--read-only`, `--cap-drop ALL`, `--memory 256m`, `--pids-limit 64`
5. If the script crashes, the traceback feeds back to Gemini — up to 5 retry attempts
6. Diff renders paragraph-level changes; download when satisfied

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite + TypeScript |
| Backend | FastAPI (Python) |
| Executor | FastAPI — only service with `docker.sock` |
| Sandbox | `python:3.12-slim` + `python-docx`, non-root |
| AI | Gemini 2.5 Flash Lite |

## Local dev

**Prerequisites:** Docker, Docker Compose, Node 20+

```bash
cp .env.example .env
# Add GEMINI_API_KEY to .env

make sandbox    # build sandbox image (required)
make build      # build all dev images
make run        # start stack

# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
# Login password: admin (set ADMIN_PASSWORD in .env)
```

Run backend tests:
```bash
make test-backend
```

Verify sandbox isolation:
```bash
make test-sandbox
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | From [Google AI Studio](https://ai.google.dev/) |
| `SESSION_SECRET` | Yes (prod) | Long random string for cookie signing |
| `ADMIN_PASSWORD` | Dev only | Plaintext password (default: `admin`) |
| `ADMIN_PASSWORD_HASH` | Prod | Bcrypt hash — generate with `make hash-password` |
| `GEMINI_MODEL` | No | Override model (default: `gemini-2.5-flash-lite`) |
| `CORS_ORIGINS` | Prod | Comma-separated allowed origins |

## Production deploy

CI/CD via GitHub Actions — pushes to `main` build and deploy automatically.

Set `ADMIN_PASSWORD_HASH` (bcrypt) instead of plaintext `ADMIN_PASSWORD`. Generate with:
```bash
make hash-password
```

App runs on port `8080`. Put Cloudflare or nginx in front for TLS.
