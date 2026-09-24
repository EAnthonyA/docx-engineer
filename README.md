# docx-engineer

Upload a `.docx`, describe the edit in plain language, get back a modified file.

A DeepSeek-powered AI client generates a `python-docx` script. The script runs in a Docker sandbox with a read-only root filesystem, read-only input/script mounts, a writable output directory, and dropped capabilities. Its internal network provides access to a restricted webpage-fetching sidecar, with no direct internet access. You review a partial before/after preview, then download the full Word file.

## How it works

1. Upload `.docx` + type instruction ("make all headings bold")
2. Backend streams document structure, then sends bounded, labelled excerpts (including tables, headers and instruction matches) + instruction to the LLM
3. The LLM returns an `edit(doc, tools)` function
4. Executor runs it in a throwaway container: internal network, `--read-only`, `--cap-drop ALL`, bounded memory (production default 1500 MiB), `--pids-limit 64`
5. Script errors feed back to the LLM, up to 5 attempts. Temporary AI requests retry up to 3 times; infrastructure failures stop without rewriting code. An editing-phase timeout/OOM gets at most one repair attempt; loading/saving resource failures stop immediately.
6. Validation compares Word content and formatting, including changes outside the paragraph preview. Download to review the complete layout, tables, images and styles.

Uploads are limited to 50 MiB compressed and 512 MiB expanded. The expanded-size check limits decompression work; it is not a guarantee that every accepted file fits in sandbox memory. Large files may still need to be split into smaller documents.
The sandbox streams XML into the output ZIP to avoid allocating a second full document XML buffer while saving.

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite + TypeScript |
| Backend | FastAPI (Python) |
| Executor | FastAPI — only service with `docker.sock` |
| Sandbox | `python:3.12-slim` + `python-docx`, non-root |
| AI | DeepSeek (`deepseek-v4-pro`) |

## Local dev

**Prerequisites:** Docker, Docker Compose, Node 20+

```bash
cp .env.example .env
# Add DEEPSEEK_API_KEY to .env

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
| `DEEPSEEK_API_KEY` | Yes | From [DeepSeek Platform](https://platform.deepseek.com/) |
| `DEEPSEEK_MODEL` | No | Override model (default: `deepseek-v4-pro`) |
| `SESSION_SECRET` | Yes (prod) | Long random string for cookie signing |
| `ADMIN_PASSWORD` | Dev only | Plaintext password (default: `admin`) |
| `ADMIN_PASSWORD_HASH` | Prod | Bcrypt hash — generate with `make hash-password` |
| `SANDBOX_MEMORY` | No | Sandbox container memory limit (production default: `1500m`; dev compose sets `1536m`) |
| `SANDBOX_TIMEOUT` | No | Maximum sandbox runtime in seconds (production default: `180`) |
| `JOBS_HOST_DIR` | Prod | Absolute host directory mounted at `/jobs`; required because the executor bind-mounts individual files into nested sandbox containers |
| `CORS_ORIGINS` | Prod | Comma-separated allowed origins |

## Production deploy

Pushes to `main` build and deploy after the CI checks pass. You can also run
**Build and deploy to VPS** manually from the `main` branch in GitHub Actions.
The workflow builds and deploys all five images (including the scraper) tagged with that commit's SHA,
then checks the backend and the `sangri.tech` route through the shared nginx proxy.
For a manual Compose command on the VPS, set `IMAGE_TAG` to a commit SHA whose
images have been built and pushed.
