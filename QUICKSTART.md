# lang_un_rag

A local Retrieval‑Augmented Generation (RAG) system for indexing and querying documents.  
This project provides a FastAPI service that extracts text from documents, chunks them, stores embeddings in a ChromaDB collection, and exposes endpoints for indexing, reindexing, enumerating chunks, statistics, and similarity queries. It also includes a robust filesystem watcher sidecar that will trigger indexing automatically when files change.

This README replaces the older documentation and reflects the current repo state (watcher sidecar, startup wrapper, restored vector store helpers, expanded ingestion support).

---

## Highlights

- FastAPI API: index, reindex, list chunks, stats, query
- ChromaDB-backed vector store with local embedding provider (sentence-transformers wrapper)
- Document ingestion pipeline using Unstructured + LangChain chunking
- Support for many file types (text, markdown, HTML, PDF, Office, images with OCR)
- NFS‑safe watcher sidecar (PollingObserver) with debounce and stability checks
- Dockerized development with `docker compose` and uv-managed venvs

---

## Supported file types (allowed extensions)

The pipeline attempts to extract text from these types (subject to installed libraries and optional binaries like `tesseract`):

- Text / markup:
  - .md, .markdown, .txt, .html, .htm
- PDFs:
  - .pdf
- Office formats:
  - .docx, .pptx
  - (legacy .doc/.ppt may require conversion)
- Images (require OCR to extract text):
  - .png, .jpg, .jpeg, .tif, .tiff, .bmp, .gif
- Other:
  - Any file types supported by Unstructured loaders or added custom loaders

Notes:
- OCR: image and some scanned PDFs require `tesseract` (binary) + `pytesseract` installed in the image to extract text.
- If you need additional extensions, update `app/document_processor.py` and add any parser dependencies to pyproject/uv config.

---

## Quickstart — Docker (recommended)

Prereqs:
- Docker
- `docker compose` (Docker Compose V2 plugin). Avoid the deprecated `docker-compose` binary.

1. Build and start the services (application + watcher override):
   - This repository includes a `docker-compose.override.yml` that defines a `watcher` sidecar for local dev.
   ```
   docker compose up -d --build
   ```

2. Confirm services:
   ```
   docker compose ps
   ```

3. Watch logs:
   - App (replace service name with yours):
     ```
     docker compose logs -f <app-service-name>
     ```
   - Watcher:
     ```
     docker compose logs -f watcher
     ```

4. Manually trigger an index:
   - Local app:
     ```
     curl -X POST "http://localhost:8000/index"
     ```
   - If using the reverse proxy / external endpoint:
     ```
     curl -X POST "https://rag.hlab.cam/index" -H "Content-Type: application/json" -d '{}'
     ```

5. Inspect chunks:
   ```
   curl "http://localhost:8000/get_chunks?limit=10" | jq .
   ```

---

## Quickstart — Local development (no Docker)

Prereqs:
- Python 3.11+
- Optional: uv (recommended for this repo)

Using uv:
1. Install uv:
   ```
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Create venv and activate:
   ```
   uv venv
   source .venv/bin/activate
   ```

3. Sync dependencies:
   ```
   uv sync
   ```

4. Run the app:
   ```
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

If you do not use uv, create a standard venv and install dependencies with pip (pip install -e . or pip install -r requirements.txt).

---

## Configuration (env vars)

Settings are defined in `app/config.py` (Pydantic). Common env vars:

- MARKDOWN_DIR or MARKDOWN_DIR-like setting — directory to scan (default `./markdown_docs`)
- CHROMA_DB_PATH — ChromaDB persist directory (default `./chroma_db`)
- CHROMA_COLLECTION_NAME — collection name (default `markdown_docs`)
- OLLAMA_BASE_URL — Ollama host (if used)
- OLLAMA_MODEL — model name for embeddings (if used)
- API_HOST — host (default `0.0.0.0`)
- API_PORT — port (default `8000`)
- REQUESTS_CA_BUNDLE — optional CA bundle when using private CAs

Place env values into `.env` in repo root (see `.env.example`).

---

## Watcher sidecar (behavior & tuning)

- Script: `scripts/watch_and_index.py`
  - Uses Watchdog's `PollingObserver` (works on NFS)
  - Debounce window to avoid repeated triggers during bulk file operations
  - Waits for file size to stabilize (to avoid partial reads)
  - Posts a JSON body `{}` with header `Content-Type: application/json` to the configured endpoint
  - Retries with exponential backoff on transient network failures
  - CLI opts: `--watch-dir`, `--endpoint`, `--debounce`, `--poll-interval`, `--wait-stable`, `--insecure`
- Startup wrapper: `scripts/wait_and_exec.sh`
  - Waits for project venv python to appear to avoid race conditions with `uv venv`/`uv sync`
  - Prefers a python interpreter that already has required packages (requests, watchdog)
- Volumes recommendation:
  - Mount only the folders you need (scripts & markdown_docs) rather than mounting the whole repo root to avoid hiding build-time venvs:
    ```yaml
    volumes:
      - ./scripts:/opt/dockerapps/lang_un_rag/scripts:rw
      - ./markdown_docs:/app/markdown_files:rw
    ```

---

## API overview

- GET / — API info
- GET /health — health check
- POST /index — process & index documents from configured directory
- POST /reindex — clear index and reindex files
- GET /get_chunks?limit=N — enumerate stored chunks; returns `total_chunks` and `chunks` list
- GET /stats — collection stats (collection_name, document_count, persist_directory)
- POST /query — similarity query; payload: `{ "prompt": "...", "k": 5 }`

Response shapes and example calls are located in the in-repo examples and `app/main.py`.

---

## Troubleshooting (common issues)

- ModuleNotFoundError for `requests` in watcher:
  - Ensure the watcher is executed with the venv that has dependencies (e.g., `/app/.venv/bin/python3`) or install deps into the image.
- Venv hidden by bind mount:
  - If you mount the repo root to the same path used during image build, you may hide build-time artifacts (venv). Create the venv outside the mount point (e.g., `/app/.venv`) or mount narrower paths.
- OCR is not extracting text:
  - Install the `tesseract` binary in the image or host and ensure `pytesseract` is available in Python dependencies.
- TLS errors:
  - Ensure `ca-certificates` are installed in the image. For private CAs set `REQUESTS_CA_BUNDLE` or install CA cert into system trust store.

---

## Maintenance & operations

- Full reindex:
  - POST `/reindex` triggers clear + rebuild. `clear_collection()` tries to call a Chroma delete API and falls back to removing the persist directory when needed.
- Persistence:
  - Persist the `CHROMA_DB_PATH` with a Docker volume or bind mount for durability.
- Cert renewals:
  - If an external reverse proxy (e.g., nginx) manages ACME certs, ensure it reloads after renewal so watchers and external clients continue to validate TLS.

---

## Contributing

- Keep vector_store helper methods stable because API endpoints depend on `get_all_chunks`, `get_collection_stats`, etc.
- Add tests under `tests/` and run with `pytest`.
- Open PRs against `main` with a concise commit message.

---

## License

MIT
