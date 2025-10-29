# AI Coding Agent Instructions for lang_un_rag

This is a local RAG (Retrieval-Augmented Generation) system that indexes documents into ChromaDB and provides REST API endpoints for similarity search. The system consists of a FastAPI app with a filesystem watcher sidecar for automatic reindexing.

## Architecture Overview

**Core Components:**
- `app/main.py` - FastAPI application with REST endpoints (`/index`, `/reindex`, `/query`, `/get_chunks`, `/stats`)
- `app/vector_store.py` - ChromaDB wrapper with custom helper methods and sentence-transformers embeddings
- `app/document_processor.py` - Multi-format document ingestion pipeline using Unstructured + LangChain text splitters
- `scripts/watch_and_index.py` - PollingObserver-based filesystem watcher that triggers `/index` via HTTP POST

**Data Flow:**
1. Documents → DocumentProcessor (extract/chunk) → VectorStore (embed/index) → ChromaDB collection
2. Query → embed_query → similarity_search_by_vector → ranked Document results
3. File changes → watcher debounce → HTTP POST `{}` to `/index` → automatic reindexing

## Key Development Patterns

**Configuration Management:**
- Uses `pydantic-settings` in `app/config.py` with `.env` file support
- All paths/URLs configurable via environment variables (see `.env.example`)
- Docker networking uses service names: `http://rag-api:8000/index`

**VectorStore Helper Methods:**
The `VectorStore` class provides backwards-compatible helper methods that endpoints rely on:
```python
# Always preserve these methods when modifying vector_store.py
get_all_chunks(limit=None)  # Returns [{"id": str, "content": str, "metadata": dict}]
get_collection_stats()      # Returns {"collection_name": str, "document_count": int}
clear_collection()          # Defensive deletion with persist directory fallback
reindex_documents(docs)     # clear_collection() + index_documents()
```

**Document Processing Pipeline:**
- Supports 15+ file types (markdown, PDF, Office, images with OCR)
- Uses `allowed_extensions` and `exclude_dirs` settings for filtering
- Text chunking via `RecursiveCharacterTextSplitter` (configurable chunk_size/overlap)
- Each chunk gets metadata: `source` (filename), `chunk_id` (index)

## Development Workflows

**Local Development:**
```bash
uv venv && source .venv/bin/activate && uv sync
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Docker Development:**
```bash
docker compose up -d --build  # Includes watcher sidecar from override.yml
docker compose logs -f rag-api
curl -X POST "http://localhost:2700/index"  # Manual trigger
```

**Adding New File Types:**
1. Add extension to `allowed_extensions` in `app/config.py`
2. Implement loader logic in `DocumentProcessor.load_documents()`
3. Add required parser dependencies to `pyproject.toml`
4. Update Dockerfile if system packages needed (e.g., tesseract for OCR)

## Testing & Debugging

**Manual API Testing:**
```bash
curl -X POST "http://localhost:2700/index"                    # Index documents
curl "http://localhost:2700/get_chunks?limit=5"              # List chunks
curl -X POST "http://localhost:2700/query" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "search terms", "k": 3}'                     # Similarity search
```

**Debug Files:** Use existing debug scripts for similarity and embedding analysis:
- `debug_similarity.py` - Test similarity searches
- `check_qdevice_*.py` - Validate embedding consistency

## Integration Points

**Watcher Sidecar:**
- Uses PollingObserver (NFS-safe) with debounce logic and file stability checks
- Posts `json: {}` to endpoint with exponential backoff retry
- Configure via `WATCHER_*` environment variables
- Startup wrapper `wait_and_exec.sh` avoids venv race conditions

**ChromaDB Persistence:**
- Persist `./chroma_db` directory for long-term storage
- Collection management through defensive API calls with directory fallback
- Uses sentence-transformers for local embeddings (no external API dependencies)

**Docker Networking:**
- Main service exposes port `2700:8000` 
- Watcher communicates via internal service name `rag-api:8000`
- Mount document directory as `./markdown_docs:/app/markdown_files`

## Common Gotchas

- **Volume Overlays:** Mount only needed subdirs (not project root) to avoid hiding build-time venvs
- **Watcher Python:** Ensure watcher uses venv with required packages (`/app/.venv/bin/python3`)
- **ChromaDB API Changes:** `get()` method behavior varies between versions - avoid `"ids"` in include parameter
- **OCR Dependencies:** Images require `tesseract` binary + `pytesseract` for text extraction
- **File Stability:** Large file copies need `--wait-stable` to avoid partial reads during processing

When modifying core components, test with both single files and batch operations to ensure the helper methods and endpoints remain functional.