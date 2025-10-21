# Quick Start Guide

Get the RAG system up and running in 5 minutes!

## Prerequisites

Before you begin, ensure you have:

1. **Docker and Docker Compose** installed
2. **Ollama** installed and running on your host machine

## Step 1: Install Ollama

If you haven't already, install Ollama on your host machine:

```bash
# Visit https://ollama.ai/download for installation instructions
# Or use this quick install (Linux/Mac):
curl -fsSL https://ollama.ai/install.sh | sh
```

## Step 2: Pull an Ollama Model

Pull a model for embeddings (llama2 is recommended):

```bash
ollama pull llama2
```

Verify Ollama is running:

```bash
# Should return the Ollama version
curl http://localhost:11434/api/version
```

## Step 3: Configure the Application

Copy the example environment file:

```bash
cp .env.example .env
```

The default settings should work for most cases. The important settings are:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama2
MARKDOWN_DIR=./markdown_files
```

## Step 4: Add Markdown Files

Create markdown files in the `markdown_files` directory:

```bash
# The directory already exists with a sample file
ls markdown_files/

# Add your own markdown files
cp /path/to/your/docs/*.md markdown_files/
```

## Step 5: Start the System

Use the convenience script to start everything:

```bash
./run.sh
```

Or use Docker Compose directly:

```bash
docker-compose up --build
```

The API will be available at `http://localhost:8000`

## Step 6: Index Your Documents

Once the system is running, index your markdown files:

```bash
curl -X POST http://localhost:8000/index
```

You should see a response like:

```json
{
  "status": "success",
  "message": "Successfully indexed documents from ./markdown_files",
  "documents_indexed": 5,
  "chunks_created": 23
}
```

## Step 7: Retrieve Chunks

Get the indexed chunks:

```bash
curl "http://localhost:8000/get_chunks?limit=5"
```

## Step 8: Check Statistics

View collection statistics:

```bash
curl http://localhost:8000/stats
```

## Troubleshooting

### Ollama Connection Issues

If you get connection errors to Ollama:

1. Verify Ollama is running: `curl http://localhost:11434/api/version`
2. Check Docker can reach host: `docker run --rm curlimages/curl curl http://host.docker.internal:11434/api/version`
3. On Linux, you may need to use `http://172.17.0.1:11434` instead of `host.docker.internal`

### No Markdown Files Found

If indexing fails with "No markdown files found":

1. Check that markdown files exist: `ls markdown_files/`
2. Ensure files have `.md` extension
3. Check file permissions

### Port Already in Use

If port 8000 is already in use:

1. Change the port in `.env`: `API_PORT=8080`
2. Update docker-compose.yml ports: `"8080:8080"`

## Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Check [IMPLEMENTATION.md](IMPLEMENTATION.md) for technical details
- Run [examples.sh](examples.sh) to see all API endpoints in action
- Add more markdown files and reindex: `curl -X POST http://localhost:8000/reindex`

## Stopping the System

To stop the system:

```bash
# Press Ctrl+C in the terminal where it's running
# Or if running in detached mode:
docker-compose down
```

## Development Mode

To run in development mode with auto-reload:

```bash
# Install UV (if not using Docker)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt

# Run with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Getting Help

- Check the logs: `docker-compose logs -f`
- Visit the API docs: `http://localhost:8000/docs` (Swagger UI)
- Review the health endpoint: `http://localhost:8000/health`

Happy RAG-ing! 🚀
