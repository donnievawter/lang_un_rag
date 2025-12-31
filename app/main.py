"""FastAPI application for the RAG system."""
import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.document_processor import DocumentProcessor
from app.vector_store import VectorStore
from app.query_chunks import query_chunks

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Markdown RAG System",
    description="A RAG system for indexing and querying markdown documents",
    version="0.1.0",
)

# Initialize components
document_processor = DocumentProcessor()
vector_store = VectorStore()





class IndexResponse(BaseModel):
    """Response model for index operations."""
    status: str
    message: str
    documents_indexed: int
    chunks_created: int


class ReindexResponse(BaseModel):
    """Response model for reindex operations."""
    status: str
    message: str
    documents_indexed: int
    chunks_created: int


class SyncResponse(BaseModel):
    """Response model for sync operations."""
    status: str
    message: str
    files_checked: int
    files_added: int
    files_removed: int
    chunks_created: int


class ChunkData(BaseModel):
    """Model for chunk data."""
    id: str
    content: str
    metadata: Dict[str, Any]


class GetChunksResponse(BaseModel):
    """Response model for get_chunks endpoint."""
    total_chunks: int
    chunks: List[ChunkData]


class CollectionStatsResponse(BaseModel):
    """Response model for collection statistics."""
    collection_name: str
    document_count: int
    persist_directory: str


class DocumentInfo(BaseModel):
    """Model for indexed document information."""
    source: str
    chunk_count: int
    file_type: str


class GetDocumentsResponse(BaseModel):
    """Response model for get_documents endpoint."""
    total_documents: int
    documents: List[DocumentInfo]


class QueryRequest(BaseModel):
    prompt: str
    k: Optional[int] = 5

class RetrievedChunk(BaseModel):
    content: str
    metadata: dict

class QueryResponse(BaseModel):
    prompt: str
    results: List[RetrievedChunk]


class DocumentRequest(BaseModel):
    """Request model for document retrieval."""
    file_path: str = Field(..., description="Relative path to the document within the markdown_docs directory")


class DocumentResponse(BaseModel):
    """Response model for document content."""
    file_path: str
    content: str
    content_type: str
    size_bytes: int


class GetChunksForDocumentRequest(BaseModel):
    """Request model for retrieving chunks for a specific document."""
    source: str = Field(..., description="Source document name to retrieve chunks for")
    limit: Optional[int] = Field(None, description="Maximum number of chunks to return (default: all)")


class IncrementalRequest(BaseModel):
    """Request model for incremental operations."""
    file_path: str = Field(..., description="Relative path to the file that was added/modified/deleted")


class IncrementalResponse(BaseModel):
    """Response model for incremental operations."""
    status: str
    operation: str
    file_path: str
    chunks_affected: int
    message: str

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Markdown RAG System API",
        "version": "0.1.0",
        "endpoints": {
            "/index": "Index markdown files into ChromaDB",
            "/reindex": "Clear and reindex markdown files",
            "/sync": "Sync filesystem with vector store (only index missing/remove deleted files)",
            "/index_file": "Index or update a single file incrementally",
            "/delete_file": "Remove a file's chunks from the index",
            "/get_chunks": "Retrieve indexed chunks",
            "/get_chunks_for_document": "Retrieve chunks for a specific document source",
            "/stats": "Get collection statistics",
            "/query": "Perform similarity search on indexed documents",
            "/document": "Retrieve raw content of a specific document",
        }
    }


@app.post("/index", response_model=IndexResponse)
async def index_documents():
    """Index markdown documents from the configured directory.
    
    Returns:
        IndexResponse with status and counts
    """
    try:
        # Process documents from configured directory
        chunks = document_processor.process_directory()
        
        if not chunks:
            raise HTTPException(
                status_code=404,
                detail=f"No markdown files found in {settings.markdown_dir}"
            )
        
        # Index documents
        result = vector_store.index_documents(chunks)
        
        return IndexResponse(
            status="success",
            message=f"Successfully indexed documents from {settings.markdown_dir}",
            documents_indexed=result["documents_indexed"],
            chunks_created=len(chunks),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error indexing documents: {str(e)}"
        )


@app.post("/reindex", response_model=ReindexResponse)
async def reindex_documents():
    """Clear the existing index and reindex markdown documents.
    
    Returns:
        ReindexResponse with status and counts
    """
    try:
        # Process documents from configured directory
        chunks = document_processor.process_directory()
        
        if not chunks:
            raise HTTPException(
                status_code=404,
                detail=f"No markdown files found in {settings.markdown_dir}"
            )
        
        # Reindex documents
        result = vector_store.reindex_documents(chunks)
        
        return ReindexResponse(
            status="success",
            message=f"Successfully reindexed documents from {settings.markdown_dir}",
            documents_indexed=result["indexed"]["documents_indexed"],
            chunks_created=len(chunks),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reindexing documents: {str(e)}"
        )


@app.post("/sync", response_model=SyncResponse)
async def sync_documents():
    """Synchronize filesystem with vector store - only index missing files and remove deleted ones.
    Much more efficient than a full reindex.
    
    Returns:
        SyncResponse with sync statistics
    """
    try:
        # Get all files currently in the filesystem
        markdown_dir = Path(settings.markdown_dir).resolve()
        filesystem_files = set()
        
        for ext in settings.allowed_extensions:
            ext_pattern = f"**/*{ext}"
            for file_path in markdown_dir.glob(ext_pattern):
                if file_path.is_file():
                    # Get relative path
                    relative_path = str(file_path.relative_to(markdown_dir))
                    filesystem_files.add(relative_path)
        
        # Get all sources currently indexed in vector store
        indexed_chunks = vector_store.get_all_chunks()
        indexed_sources = set()
        for chunk in indexed_chunks:
            if "source" in chunk["metadata"]:
                indexed_sources.add(chunk["metadata"]["source"])
        
        # Find files to add (in filesystem but not in index)
        files_to_add = filesystem_files - indexed_sources
        
        # Find files to remove (in index but not in filesystem)
        files_to_remove = indexed_sources - filesystem_files
        
        logger.info(f"Sync check: {len(filesystem_files)} files in filesystem, {len(indexed_sources)} in index")
        logger.info(f"Files to add: {len(files_to_add)}, Files to remove: {len(files_to_remove)}")
        
        chunks_created = 0
        files_added = 0
        files_removed = 0
        
        # Remove deleted files from index
        for file_path in files_to_remove:
            try:
                vector_store.delete_documents_by_source(file_path)
                files_removed += 1
                logger.info(f"Removed from index: {file_path}")
            except Exception as e:
                logger.error(f"Error removing {file_path}: {e}")
        
        # Add missing files to index
        for file_path in files_to_add:
            try:
                full_path = markdown_dir / file_path
                # Process single file
                chunks = document_processor.process_file(str(full_path))
                if chunks:
                    # Index the chunks
                    vector_store.add_documents_incremental(chunks)
                    chunks_created += len(chunks)
                    files_added += 1
                    logger.info(f"Added to index: {file_path} ({len(chunks)} chunks)")
            except Exception as e:
                logger.error(f"Error indexing {file_path}: {e}")
        
        total_checked = len(filesystem_files)
        
        return SyncResponse(
            status="success",
            message=f"Sync complete: {files_added} added, {files_removed} removed",
            files_checked=total_checked,
            files_added=files_added,
            files_removed=files_removed,
            chunks_created=chunks_created
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error syncing documents: {str(e)}"
        )


@app.get("/get_chunks", response_model=GetChunksResponse)
async def get_chunks(
    limit: Optional[int] = Query(None, description="Maximum number of chunks to return")
):
    """Retrieve indexed document chunks.
    
    Args:
        limit: Optional maximum number of chunks to return
    
    Returns:
        GetChunksResponse with chunks and metadata
    """
    try:
        chunks = vector_store.get_all_chunks(limit=limit)
        
        chunk_data = [
            ChunkData(
                id=chunk["id"],
                content=chunk["content"],
                metadata=chunk["metadata"]
            )
            for chunk in chunks
        ]
        
        return GetChunksResponse(
            total_chunks=len(chunk_data),
            chunks=chunk_data,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving chunks: {str(e)}"
        )


@app.post("/get_chunks_for_document", response_model=GetChunksResponse)
async def get_chunks_for_document(request: GetChunksForDocumentRequest):
    """Retrieve chunks for a specific document source.
    
    Args:
        request: GetChunksForDocumentRequest with source and optional limit
    
    Returns:
        GetChunksResponse with matching chunks and metadata
    """
    try:
        # Convert limit=0 to None (meaning no limit)
        limit = None if request.limit == 0 else request.limit
        chunks = vector_store.get_chunks_for_document(request.source, limit=limit)
        
        chunk_data = [
            ChunkData(
                id=chunk["id"],
                content=chunk["content"],
                metadata=chunk["metadata"]
            )
            for chunk in chunks
        ]
        
        return GetChunksResponse(
            total_chunks=len(chunk_data),
            chunks=chunk_data,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving chunks for document '{request.source}': {str(e)}"
        )


@app.get("/stats", response_model=CollectionStatsResponse)
async def get_stats():
    """Get statistics about the collection.
    
    Returns:
        CollectionStatsResponse with collection information
    """
    try:
        stats = vector_store.get_collection_stats()
        return CollectionStatsResponse(
            collection_name=stats["collection_name"],
            document_count=stats["document_count"],
            persist_directory=stats["persist_directory"],
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving stats: {str(e)}"
        )


@app.get("/documents", response_model=GetDocumentsResponse)
async def get_documents():
    """Get a list of all indexed documents.
    
    Returns:
        GetDocumentsResponse with list of documents and their metadata
    """
    try:
        documents = vector_store.get_indexed_documents()
        return GetDocumentsResponse(
            total_documents=len(documents),
            documents=[DocumentInfo(**doc) for doc in documents]
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving indexed documents: {str(e)}"
        )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/document", response_model=DocumentResponse)
async def get_document(request: DocumentRequest):
    """Retrieve the raw content of a document from the markdown_docs directory.
    
    Args:
        request: DocumentRequest with file_path relative to markdown_docs
        
    Returns:
        DocumentResponse with file content and metadata
    """
    try:
        # Ensure the file path is relative and safe
        file_path = request.file_path.strip().lstrip('/')
        
        # Construct the full path within the configured markdown directory
        markdown_dir = Path(settings.markdown_dir).resolve()
        full_path = markdown_dir / file_path
        
        # Security check: ensure the resolved path is within the markdown directory
        try:
            full_path = full_path.resolve()
            full_path.relative_to(markdown_dir)
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail="Invalid file path: path must be within the configured document directory"
            )
        
        # Check if file exists
        if not full_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Document not found: {file_path}"
            )
        
        # Check if it's a file (not a directory)
        if not full_path.is_file():
            raise HTTPException(
                status_code=400,
                detail=f"Path is not a file: {file_path}"
            )
        
        # Read the file content
        try:
            # Try to read as text first (UTF-8)
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            content_type = "text/plain"
        except UnicodeDecodeError:
            # If UTF-8 fails, read as binary and return base64
            with open(full_path, 'rb') as f:
                import base64
                content = base64.b64encode(f.read()).decode('ascii')
            content_type = "application/octet-stream"
        
        # Get file size
        size_bytes = full_path.stat().st_size
        
        return DocumentResponse(
            file_path=file_path,
            content=content,
            content_type=content_type,
            size_bytes=size_bytes
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reading document: {str(e)}"
        )


@app.post("/index_file", response_model=IncrementalResponse)
async def index_single_file(request: IncrementalRequest):
    """Index a single file (add new or update existing).
    
    Args:
        request: IncrementalRequest with file_path
        
    Returns:
        IncrementalResponse with operation details
    """
    try:
        file_path = request.file_path.strip().lstrip('/')
        #logger.info(f"in main.py.index)signle_file Indexing single file: {file_path}")
        # Construct full path
        markdown_dir = Path(settings.markdown_dir).resolve()
        full_path = markdown_dir / file_path

        
        # Security check
        try:
            full_path = full_path.resolve()
            full_path.relative_to(markdown_dir)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid file path: path must be within the configured document directory"
            )
        
        # Check if file exists and is allowed
        if not full_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {file_path}"
            )
        
        if not full_path.is_file():
            raise HTTPException(
                status_code=400,
                detail=f"Path is not a file: {file_path}"
            )
        
        # Check if file extension is allowed
        #logger.info(f"Allowed extensions: {settings.allowed_extensions}")
        if full_path.suffix.lower() not in settings.allowed_extensions:
            return IncrementalResponse(
                status="skipped",
                operation="index_file",
                file_path=file_path,
                chunks_affected=0,
                message=f"File extension {full_path.suffix} not in allowed extensions"
            )
        
        # Process the single file
        chunks = document_processor.process_file(str(full_path))
        
        if not chunks:
            return IncrementalResponse(
                status="success",
                operation="index_file",
                file_path=file_path,
                chunks_affected=0,
                message="No content extracted from file"
            )
        
        # Update documents for this source (delete old, add new)
        result = vector_store.update_documents_by_source(str(full_path), chunks)
        
        return IncrementalResponse(
            status="success",
            operation="index_file",
            file_path=file_path,
            chunks_affected=result.get("added_count", 0),
            message=f"Indexed {result.get('added_count', 0)} chunks (deleted {result.get('deleted_count', 0)} old chunks)"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error indexing file: {str(e)}"
        )


@app.post("/delete_file", response_model=IncrementalResponse)
async def delete_file_from_index(request: IncrementalRequest):
    """Remove a file's chunks from the index.
    
    Args:
        request: IncrementalRequest with file_path
        
    Returns:
        IncrementalResponse with deletion details
    """
    try:
        file_path = request.file_path.strip().lstrip('/')
        
        # Construct full path for validation
        markdown_dir = Path(settings.markdown_dir).resolve()
        full_path = markdown_dir / file_path
        
        # Security check
        try:
            full_path = full_path.resolve()
            full_path.relative_to(markdown_dir)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid file path: path must be within the configured document directory"
            )
        
        # Delete documents by source (use the full resolved path as key)
        result = vector_store.delete_documents_by_source(str(full_path))
        
        return IncrementalResponse(
            status="success",
            operation="delete_file",
            file_path=file_path,
            chunks_affected=result.get("deleted_count", 0),
            message=f"Deleted {result.get('deleted_count', 0)} chunks from index"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting file from index: {str(e)}"
        )


@app.post("/query", response_model=QueryResponse)
async def query_route(request: QueryRequest):
    try:
        results = query_chunks(request.prompt, request.k)
        return QueryResponse(
            prompt=request.prompt,
            results=[
                RetrievedChunk(content=doc.page_content, metadata=doc.metadata)
                for doc in results
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True
    )
