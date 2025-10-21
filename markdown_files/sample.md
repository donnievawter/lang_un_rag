# Sample Document

This is a sample markdown document for testing the RAG system.

## Introduction

This document demonstrates how the system processes markdown files and indexes them into ChromaDB.

## Features

The system includes:

- Markdown file parsing using Unstructured
- Document chunking with LangChain
- Vector embeddings with Ollama
- Storage in ChromaDB

## Usage

Simply place your markdown files in the markdown_files directory and use the API to index them.

### Indexing

Call the `/index` endpoint to process and store your documents:

```bash
curl -X POST http://localhost:8000/index
```

### Retrieving

Use the `/get_chunks` endpoint to retrieve indexed content:

```bash
curl http://localhost:8000/get_chunks
```

## Conclusion

This RAG system provides a complete solution for local document processing and retrieval.
