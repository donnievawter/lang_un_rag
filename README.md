# lang_un_rag

A Retrieval-Augmented Generation (RAG) system for indexing and querying markdown documents using LangChain, Unstructured, Ollama, and ChromaDB.

## Features

- 📄 Parse and index markdown files from a directory
- 🔍 Vector search using ChromaDB for efficient retrieval
- 🤖 Local LLM integration with Ollama (no cloud dependencies)
- 🚀 FastAPI REST API with endpoints for indexing and querying
- 🐳 Fully containerized with Docker
- 📦 Modern Python package management with `uv`

## Prerequisites

- Docker and Docker Compose
- Ollama installed and running locally (outside the container)
- Python 3.11+ (if running without Docker)

## Quick Start

### 1. Set up Ollama

Make sure Ollama is installed and running on your host machine:

```bash
# Install Ollama (if not already installed)
# Visit: https://ollama.ai/download

# Pull a model (e.g., llama2)
ollama pull llama2

# Start Ollama service (it should be running by default)
ollama serve
```

### 2. Configure Environment

Copy the example environment file and adjust settings as needed:

```bash
cp .env.example .env
```

Edit `.env` to configure:
- `OLLAMA_BASE_URL`: URL to your Ollama instance (default: `http://host.docker.internal:11434`)
- `OLLAMA_MODEL`: Model to use for embeddings (default: `llama2`)
- `MARKDOWN_DIR`: Directory containing markdown files (default: `./markdown_files`)

### 3. Add Markdown Files

Create a `markdown_files` directory and add your markdown documents:

```bash
mkdir -p markdown_files
# Add your .md files to this directory
```

### 4. Run with Docker Compose

Build and start the service:

```bash
docker-compose up --build
```

The API will be available at `http://localhost:8000`.

## API Endpoints

### Root
```bash
GET /
```
Returns API information and available endpoints.

### Health Check
```bash
GET /health
```
Returns health status of the API.

### Index Documents
```bash
POST /index
```
Index markdown files from the configured directory into ChromaDB. Creates embeddings and stores them in the vector database.

The directory is configured via the `MARKDOWN_DIR` environment variable.

**Example:**
```bash
curl -X POST "http://localhost:8000/index"
```

**Response:**
```json
{
  "status": "success",
  "message": "Successfully indexed documents from ./markdown_files",
  "documents_indexed": 10,
  "chunks_created": 45
}
```

### Reindex Documents
```bash
POST /reindex
```
Clear the existing index and reindex all documents from the configured directory.

The directory is configured via the `MARKDOWN_DIR` environment variable.

**Example:**
```bash
curl -X POST "http://localhost:8000/reindex"
```

### Get Chunks
```bash
GET /get_chunks
```
Retrieve indexed document chunks.

**Query Parameters:**
- `limit` (optional): Maximum number of chunks to return

**Example:**
```bash
curl "http://localhost:8000/get_chunks?limit=10"
```

**Response:**
```json
{
  "total_chunks": 10,
  "chunks": [
    {
      "id": "chunk_id_1",
      "content": "Document content...",
      "metadata": {
        "source": "file.md",
        "chunk_id": 0
      }
    }
  ]
}
```

### Collection Statistics
```bash
GET /stats
```
Get statistics about the indexed collection.

**Example:**
```bash
curl "http://localhost:8000/stats"
```

**Response:**
```json
{
  "collection_name": "markdown_docs",
  "document_count": 45,
  "persist_directory": "./chroma_db"
}
```

## Development

### Local Development (without Docker)

1. Install `uv` package manager:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Create a virtual environment and install dependencies:
```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e .
```

3. Run the application:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Project Structure

```
lang_un_rag/
├── app/
│   ├── __init__.py
│   ├── config.py              # Configuration settings
│   ├── document_processor.py  # Markdown parsing and chunking
│   ├── vector_store.py        # ChromaDB integration
│   └── main.py               # FastAPI application
├── markdown_files/            # Your markdown documents (git-ignored)
├── chroma_db/                # ChromaDB storage (git-ignored)
├── .env.example              # Example environment configuration
├── .gitignore
├── pyproject.toml            # Project dependencies
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Configuration

All configuration is done through environment variables (`.env` file):

| Variable | Description | Default |
|----------|-------------|---------|
| `OLLAMA_BASE_URL` | URL to Ollama instance | `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | Model name for embeddings | `llama2` |
| `CHROMA_DB_PATH` | Path to ChromaDB storage | `./chroma_db` |
| `CHROMA_COLLECTION_NAME` | ChromaDB collection name | `markdown_docs` |
| `MARKDOWN_DIR` | Directory with markdown files | `./markdown_files` |
| `API_HOST` | API host address | `0.0.0.0` |
| `API_PORT` | API port | `8000` |

## Technology Stack

- **FastAPI**: Modern web framework for building APIs
- **LangChain**: Framework for LLM applications
- **Unstructured**: Document parsing library
- **ChromaDB**: Vector database for embeddings
- **Ollama**: Local LLM inference
- **uv**: Fast Python package manager
- **Docker**: Containerization

## Notes

- The system is designed to run Ollama on the host machine and connect to it from within the Docker container
- ChromaDB data is persisted in the `chroma_db` directory
- Markdown files should be placed in the `markdown_files` directory
- The container uses `host.docker.internal` to access services on the host machine

## License

MIT