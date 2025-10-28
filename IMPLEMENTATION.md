# Implementation Notes

This document explains the main components, design decisions, and operational details for lang_un_rag.

## Components

1. app/document_processor.py
   - Loads files from the configured directory and selects an appropriate loader per file type (Unstructured loaders, langchain loaders, or custom logic).
   - Performs text extraction, optional OCR steps (images / scanned PDFs), and splits text into chunks using a LangChain text splitter (configurable chunk_size and chunk_overlap).
   - Attaches metadata to each chunk: `source` (filename), `chunk_id` (index), and other file metadata.

2. app/vector_store.py
   - Wrapper around Chroma (LangChain/Chroma integration).
   - Provides:
     - `initialize()` — create/load the Chroma collection
     - `index_documents(documents)` — build/overwrite collection from documents (preserves ids passed)
     - `reindex_documents(documents)` — clear + index (calls `clear_collection()` then `index_documents()`)
     - `get_all_chunks(limit=None)` — list all chunks in the collection; returns list of dicts with `id`, `content`, `metadata`
     - `list_chunks(limit=None)` — alias of `get_all_chunks`
     - `clear_collection()` — attempt to delete all items using collection API; falls back to deleting the persist directory if needed
     - `get_collection_stats()` — returns collection_name, persist_directory, document_count
     - `embed_query(text)` — returns embedding for queries using configured embedding provider
     - `similarity_search_by_vector(embedding, k)` — returns top-k similar Document objects
   - Implementation notes:
     - Defensive access to underlying Chroma collection: `_vectorstore._collection`, `_vectorstore.client`, or `_vectorstore` itself (covers multiple wrapper shapes).
     - `get_all_chunks` calls the Chroma `get()` API without including `"ids"` in the `include` list (some chroma versions return ids by default and reject "ids" in include).
     - `clear_collection` first tries collection.delete variants; if those fail it removes the persist directory and resets `_vectorstore`.

3. app/main.py
   - FastAPI app with endpoints:
     - `/index` — uses DocumentProcessor to build chunks and calls `vector_store.index_documents()`
     - `/reindex` — calls DocumentProcessor then `vector_store.reindex_documents()`
     - `/get_chunks` — calls `vector_store.get_all_chunks()` and returns results
     - `/stats` — `vector_store.get_collection_stats()`
     - `/query` — uses `app/query_chunks.py` (which uses `vector_store.embed_query()` + `vector_store.similarity_search_by_vector()`)

4. scripts/watch_and_index.py
   - PollingObserver-based watcher with a DebouncedHandler:
     - Waits for file stabilization (size unchanged) to avoid processing partial writes.
     - Debounces triggers using a configurable debounce window.
     - When triggered, posts `json: {}` to the configured `--endpoint` with `Content-Type: application/json`.
     - Retries with exponential backoff on transient network errors.
   - CLI options: `--watch-dir`, `--endpoint`, `--debounce`, `--poll-interval`, `--wait-stable`, `--insecure`.

5. scripts/wait_and_exec.sh
   - Small wrapper to avoid startup races when using `uv` to create a project venv in a volume that might not exist immediately.
   - Waits for candidate python interpreters to appear and prefer the one with `requests` and `watchdog` available.

## File type handling & loaders

- The processor selects loader based on extension/heuristics:
  - Markdown, HTML, plain text: Unstructured/markdown loader or simple open/read
  - PDF: pdfplumber/pypdf fallback
  - Office: python-docx/pptx readers
  - Images: use pillow + pytesseract (and pdf2image when converting PDF pages)
- The system is extensible: add loaders and register them in `document_processor.py`.

## Operational considerations

- Watcher:
  - Use PollingObserver for NFS mounts.
  - Keep `--debounce` high enough for large copy operations (e.g., 30–120s depending on source).
  - Ensure network egress from watcher to the index endpoint and TLS trust (ca-certificates).
- Venv & startup:
  - Using `uv venv`/`uv sync` is the recommended dev flow; the watcher startup wrapper prevents race conditions when venv is created on a shared mount.
  - When building images, prefer creating the venv at a path outside of any repo-mount to avoid overlay issues (e.g., `/app/.venv`).
- Chroma persistence & backups:
  - Persist the `CHROMA_DB_PATH` to a Docker volume or host bind mount for durability.
  - To migrate or back up, copy the persist directory while Chroma is not actively writing or use Chroma export methods if available.
- Certificates:
  - If using a reverse proxy with ACME certs (e.g., `rag.example.com`), ensure the proxy reloads after renewal. Containers should have `ca-certificates` installed to validate Let's Encrypt certs.

## Extending the system

- Add new loaders in `document_processor.py` and include tests to verify extraction.
- To add new endpoints or helpers, update `app/main.py` and keep vector_store helpers backward compatible.
- Add CI that runs `uv sync` in the build step or ensures dependencies are installed in a canonical venv path.

## Tests

- Add pytest tests in `tests/`. Use `pytest-asyncio` for async endpoint tests.
- Example:
  - Start the app locally or in test mode, run `pytest tests/test_main.py::test_get_chunks`

---
