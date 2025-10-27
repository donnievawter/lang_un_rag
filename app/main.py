"""FastAPI application for the RAG system."""
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.document_processor import DocumentProcessor
from app.vector_store import VectorStore
from app.query_chunks import query_chunks

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

class QueryRequest(BaseModel):
    prompt: str
    k: Optional[int] = 5

class RetrievedChunk(BaseModel):
    content: str
    metadata: dict

class QueryResponse(BaseModel):
    prompt: str
    results: List[RetrievedChunk]

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Markdown RAG System API",
        "version": "0.1.0",
        "endpoints": {
            "/index": "Index markdown files into ChromaDB",
            "/reindex": "Clear and reindex markdown files",
            "/get_chunks": "Retrieve indexed chunks",
            "/stats": "Get collection statistics",
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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

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
