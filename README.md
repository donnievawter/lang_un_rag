# lang_un_rag

A local Retrieval-Augmented Generation (RAG) system for indexing and querying documents.  
This project provides a FastAPI service that indexes documents into a ChromaDB vector store, exposes REST endpoints for indexing, querying, and retrieving chunks, and includes a robust filesystem watcher sidecar that triggers indexing when files change.

This README replaces the old documentation and reflects the current repository state after recent updates:
- watcher sidecar + startup wrapper to avoid venv/startup races
- restored and hardened vector_store helpers
- broader document-type support (beyond Markdown)

---

## Key features

- FastAPI REST API:
  - `GET /` — API information
  - `GET /health` — basic health check
  - `POST /index` — process and index supported files from the configured directory
  - `POST /reindex` — clear and reindex all files
  - `GET /get_chunks` — enumerate stored chunks (supports `?limit=N`)
  - `GET /stats` — collection statistics
  - `POST /query` — run a similarity query (RAG)
- Vector store:
  - ChromaDB-backed store (wrapper in `app/vector_store.py`)
  - Embeddings via local sentence-transformers wrapper (or other configured provider)
  - Backwards-compatible helper methods: `get_all_chunks`, `reindex_documents`, `clear_collection`, `get_collection_stats`, etc.
- Document processing:
  - Uses Unstructured and LangChain splitting to extract and chunk document text
  - Per-chunk metadata (source, chunk_id, other file metadata)
  - Supports many file types (see "Supported file types" below)
- Watcher sidecar:
  - `scripts/watch_and_index.py` — PollingObserver-based watcher (robust on NFS)
  - Debounce + "wait for file stable" logic to avoid partial reads during large copies
  - Posts JSON `{}` to the configured index endpoint (supports HTTPS), retries with backoff
  - `scripts/wait_and_exec.sh` helper to avoid venv/startup race conditions
- Dockerized development:
  - Dockerfile + `docker compose` support
  - `docker-compose.override.yml` adds a `watcher` sidecar for local development
  - Uses `uv` for venv creation/sync in development flows (project-managed deps)

---

## Supported file types & allowed extensions

The document ingestion pipeline has been extended beyond Markdown and now accepts a variety of common document formats. The pipeline behavior depends on installed parsers/optional system tools (OCR for images, etc.). Typical supported/allowed extensions handled by the current pipeline include:

- Plain text / markup
  - .md, .markdown, .txt
  - .html, .htm
- PDF
  - .pdf (processed via pdf libraries such as pypdf / pdfplumber)
- Office documents
  - .docx (Microsoft Word)
  - .pptx (PowerPoint)
  - (Note: legacy .doc/.ppt binary formats may require additional tooling or conversion)
- Images (text extraction requires OCR)
  - .png, .jpg, .jpeg, .tif, .tiff, .bmp, .gif
  - (OCR via pytesseract + pillow/pdf2image where appropriate)
- Other
  - Any file types for which Unstructured or installed loaders provide support; the pipeline will attempt to extract text where possible.

Important notes about file handling:
- OCR: Image-based files and scanned PDFs require OCR to produce useful text. Ensure `pytesseract` is installed and the tesseract binary is available on the host/image if you expect to process images/scanned PDFs.
- Binary legacy Office formats (.doc, .ppt) are not guaranteed; prefer modern OOXML (.docx/.pptx) or convert before indexing.
- If you plan to add new file types, extend/adjust `app/document_processor.py` document loader logic and ensure any extra libraries are listed in dependencies and available in the container image.
- There may be per-file-size or per-chunk limits depending on the splitter settings — very large single files may be chunked or may require tuning of the text splitter.

---

## Repo layout

- app/
  - main.py — FastAPI app and endpoints
  - config.py — pydantic settings
  - document_processor.py — document loading & chunking pipeline
  - vector_store.py — Chroma integration (wrapper + restored helpers)
  - query_chunks.py — query helper used by /query
- scripts/
  - watch_and_index.py — filesystem watcher that triggers POST to /index
  - wait_and_exec.sh — startup wrapper that waits for an appropriate python/venv
- docker-compose.yml — primary compose file
- docker-compose.override.yml — local override (adds watcher sidecar)
- Dockerfile — image build
- pyproject.toml / uv.lock — project metadata & dependency tool (uv)
- markdown_docs/ (or configured directory) — host-mounted documents directory (gitignored)
- chroma_db/ — ChromaDB persistence (gitignored)

---

## Quick start — Docker

Notes:
- Use `docker compose` (newer Compose plugin).
- Remove `version:` keys from compose files if you see warnings about them being obsolete.

1. Build and start services (app + watcher sidecar):
   ```
   docker compose up -d --build
   ```

2. Check services:
   ```
   docker compose ps
   ```

3. Tail logs:
   - App:
     ```
     docker compose logs -f <app-service-name>
     ```
   - Watcher:
     ```
     docker compose logs -f watcher
     ```

4. Trigger indexing manually:
   ```
   curl -X POST "http://localhost:8000/index"
   ```
   Or (if using the external proxy):
   ```
   curl -X POST "https://rag.hlab.cam/index" -H "Content-Type: application/json" -d '{}'
   ```

---

## Configuration (environment variables)

Settings are read by `app/config.py` via pydantic. Key environment variables (set in `.env`):

- `MARKDOWN_DIR` or `MARKDOWN_DIR`-equivalent — directory to scan (e.g., `./markdown_docs`)
- `CHROMA_DB_PATH` — ChromaDB persist directory (default: `./chroma_db`)
- `CHROMA_COLLECTION_NAME` — collection name (default: `markdown_docs`)
- `OLLAMA_BASE_URL` — Ollama URL, if using a local Ollama instance
- `OLLAMA_MODEL` — model used for embeddings, if configured
- `API_HOST` — host to bind (default: `0.0.0.0`)
- `API_PORT` — port to bind (default: `8000`)

See `.env.example` for a sample configuration.

---

## Watcher sidecar details

- Script: `scripts/watch_and_index.py`
  - Uses Watchdog's `PollingObserver` (robust on NFS)
  - CLI options:
    - `--watch-dir` (required) — directory to observe inside the container
    - `--endpoint` — full URL to POST (e.g., `https://rag.hlab.cam/index`)
    - `--debounce` — seconds to debounce repeated events
    - `--poll-interval` — PollingObserver interval
    - `--wait-stable` — seconds a file must be unchanged before triggering
    - `--insecure` — (not recommended) disable TLS verification
  - Behavior:
    - Waits for files to stabilize (size unchanged) before triggering
    - Debounces multiple events to avoid duplicate indexing
    - Posts JSON `{}` to endpoint and retries on transient failures
- Startup wrapper: `scripts/wait_and_exec.sh`
  - Waits for the project venv/python to appear (avoids race with `uv venv` or other setup)
  - Prefers an interpreter that already has the required packages (requests/watchdog), falls back to system python if allowed
- Example compose override snippet (recommended to mount only required dirs to avoid overlaying venv):
  ```yaml
  services:
    watcher:
      command: >
        /app/.venv/bin/python3 /opt/dockerapps/lang_un_rag/scripts/watch_and_index.py
        --watch-dir /app/markdown_files
        --endpoint https://rag.hlab.cam/index
        --debounce 60
        --poll-interval 5
        --wait-stable 2
      volumes:
        - ./scripts:/opt/dockerapps/lang_un_rag/scripts:rw
        - ./markdown_docs:/app/markdown_files:rw
  ```

---

## API reference (summary)

- GET /
  - Returns API info & endpoints
- GET /health
  - Returns `{"status":"healthy"}`
- POST /index
  - Index supported files from the configured directory
- POST /reindex
  - Clear and reindex all files
- GET /get_chunks?limit=10
  - Returns list of stored chunks (id, content, metadata)
- GET /stats
  - Returns `collection_name`, `document_count`, `persist_directory`
- POST /query
  - Send `{ "prompt": "...", "k": 5 }` to retrieve similar chunks

---

## Local development (without Docker)

Prereqs: Python 3.11+, `uv` (recommended) or use standard venv/pip.

Using `uv`:
1. Install `uv`:
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
4. Run app:
   ```
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

If not using `uv`, create a venv and `pip install -e .` or `pip install -r requirements.txt`.

---

## Troubleshooting & gotchas

- Missing Python packages in watcher:
  - Ensure the watcher runs under the venv that has project deps (example: `/app/.venv/bin/python3`) or install required packages into the image.
- Venv vs volume overlay:
  - Mounting the host repo onto a path that contained build-time artifacts (like a venv) will hide those artifacts. Either create the venv outside of the mounted path (e.g., `/app/.venv`) or mount only the needed subfolders.
- OCR / image handling:
  - Install the `tesseract` binary and `pytesseract` to process images / scanned PDFs.
- TLS:
  - Ensure `ca-certificates` is installed in the image (Let’s Encrypt ACME certs are normally trusted). For private CAs add your CA to the container trust store.
- Docker Compose warnings:
  - Remove `version:` keys from compose files to silence obsolescence warnings.

---

## Maintenance & operations

- Reindex (full rebuild)
  - Use `POST /reindex` to clear and rebuild from the configured directory.
  - `clear_collection()` will attempt an API delete and falls back to removing the persist directory if necessary.
- Chroma persistence
  - Persist `CHROMA_DB_PATH` with a Docker volume or bind-mount for long-term storage.
- Certificates
  - If a reverse proxy (e.g., nginx at `rag.hlab.cam`) provides ACME certs, ensure it reloads after renewal.

---

## Contributing

- Keep vector_store helper methods stable — API endpoints rely on `get_all_chunks`, `get_collection_stats`, etc.
- Add tests under `tests/` and run `pytest`.
- Open PRs against `main` with a concise commit message and description.

---

## License

MIT
