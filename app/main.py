"""FastAPI application for the RAG system."""
import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
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


class EmailViewResponse(BaseModel):
    """Response model for formatted email viewing."""
    file_path: str
    subject: str
    from_addr: str
    to_addr: str
    date: str
    body_text: str
    body_html: Optional[str] = None
    size_bytes: int


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
            "/view_email": "View a parsed and formatted email with metadata (JSON)",
            "/render_email": "Render an email as formatted HTML for browser viewing",
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


@app.post("/view_email", response_model=EmailViewResponse)
async def view_email(request: DocumentRequest):
    """View a formatted email with parsed metadata and body.
    
    Args:
        request: DocumentRequest with file_path to the email file
        
    Returns:
        EmailViewResponse with parsed email content and metadata
    """
    try:
        from email import policy
        from email.parser import BytesParser
        from bs4 import BeautifulSoup
        
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
                detail=f"Email file not found: {file_path}"
            )
        
        # Check if it's a file (not a directory)
        if not full_path.is_file():
            raise HTTPException(
                status_code=400,
                detail=f"Path is not a file: {file_path}"
            )
        
        # Check if it's an email file
        if not full_path.suffix.lower() in ['.eml', '.emlx']:
            raise HTTPException(
                status_code=400,
                detail=f"File is not an email file: {file_path}"
            )
        
        # Parse the email
        with open(full_path, 'rb') as f:
            # Mac .emlx files have a header line with message length, skip it
            first_line = f.readline()
            # If it looks like a length header (just digits), it's .emlx format
            if first_line.strip().isdigit():
                # Continue reading from current position (after the length line)
                msg = BytesParser(policy=policy.default).parse(f)
            else:
                # Regular .eml file, rewind and parse from beginning
                f.seek(0)
                msg = BytesParser(policy=policy.default).parse(f)
        
        # Extract metadata
        subject = msg.get('subject', '(No Subject)')
        from_addr = msg.get('from', '(Unknown Sender)')
        to_addr = msg.get('to', '(Unknown Recipient)')
        date = msg.get('date', '(No Date)')
        
        # Extract body content
        body_text = ""
        body_html = None
        
        if msg.is_multipart():
            # Handle multipart messages
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get('Content-Disposition', ''))
                
                # Skip attachments
                if 'attachment' in content_disposition:
                    continue
                    
                # Get plain text parts
                if content_type == 'text/plain':
                    try:
                        text = part.get_content()
                        if text:
                            body_text += text + "\n"
                    except Exception:
                        pass
                        
                # Get HTML parts
                elif content_type == 'text/html':
                    try:
                        html_content = part.get_content()
                        body_html = html_content
                        # Also create text version if we don't have one
                        if not body_text:
                            soup = BeautifulSoup(html_content, 'html.parser')
                            for script in soup(['script', 'style']):
                                script.decompose()
                            body_text = soup.get_text(separator='\n', strip=True)
                    except Exception:
                        pass
        else:
            # Simple non-multipart message
            content_type = msg.get_content_type()
            if content_type == 'text/plain':
                try:
                    body_text = msg.get_content()
                except Exception:
                    pass
            elif content_type == 'text/html':
                try:
                    html_content = msg.get_content()
                    body_html = html_content
                    soup = BeautifulSoup(html_content, 'html.parser')
                    for script in soup(['script', 'style']):
                        script.decompose()
                    body_text = soup.get_text(separator='\n', strip=True)
                except Exception:
                    pass
        
        # Get file size
        size_bytes = full_path.stat().st_size
        
        return EmailViewResponse(
            file_path=file_path,
            subject=subject,
            from_addr=from_addr,
            to_addr=to_addr,
            date=date,
            body_text=body_text.strip(),
            body_html=body_html,
            size_bytes=size_bytes
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error parsing email: {str(e)}"
        )


@app.post("/render_email", response_class=HTMLResponse)
async def render_email(request: DocumentRequest):
    """Render an email as formatted HTML for viewing in browser.
    
    Args:
        request: DocumentRequest with file_path to the email file
        
    Returns:
        HTML response with formatted email
    """
    try:
        from email import policy
        from email.parser import BytesParser
        from bs4 import BeautifulSoup
        import html
        
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
                detail=f"Email file not found: {file_path}"
            )
        
        # Check if it's a file (not a directory)
        if not full_path.is_file():
            raise HTTPException(
                status_code=400,
                detail=f"Path is not a file: {file_path}"
            )
        
        # Check if it's an email file
        if not full_path.suffix.lower() in ['.eml', '.emlx']:
            raise HTTPException(
                status_code=400,
                detail=f"File is not an email file: {file_path}"
            )
        
        # Parse the email
        with open(full_path, 'rb') as f:
            # Mac .emlx files have a header line with message length, skip it
            first_line = f.readline()
            # If it looks like a length header (just digits), it's .emlx format
            if first_line.strip().isdigit():
                # Continue reading from current position (after the length line)
                msg = BytesParser(policy=policy.default).parse(f)
            else:
                # Regular .eml file, rewind and parse from beginning
                f.seek(0)
                msg = BytesParser(policy=policy.default).parse(f)
        
        # Extract metadata
        subject = html.escape(msg.get('subject', '(No Subject)'))
        from_addr = html.escape(msg.get('from', '(Unknown Sender)'))
        to_addr = html.escape(msg.get('to', '(Unknown Recipient)'))
        date = html.escape(msg.get('date', '(No Date)'))
        
        # Extract body content
        body_text = ""
        body_html = None
        
        if msg.is_multipart():
            # Handle multipart messages
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get('Content-Disposition', ''))
                
                # Skip attachments
                if 'attachment' in content_disposition:
                    continue
                    
                # Get plain text parts
                if content_type == 'text/plain':
                    try:
                        text = part.get_content()
                        if text:
                            body_text += text + "\n"
                    except Exception:
                        pass
                        
                # Get HTML parts
                elif content_type == 'text/html':
                    try:
                        html_content = part.get_content()
                        body_html = html_content
                    except Exception:
                        pass
        else:
            # Simple non-multipart message
            content_type = msg.get_content_type()
            if content_type == 'text/plain':
                try:
                    body_text = msg.get_content()
                except Exception:
                    pass
            elif content_type == 'text/html':
                try:
                    body_html = msg.get_content()
                except Exception:
                    pass
        
        # Render HTML response
        if body_html:
            # Use the HTML version if available
            email_body = f"""
                <div style="border: 1px solid #ddd; padding: 15px; margin-top: 15px; background: white;">
                    {body_html}
                </div>
            """
        else:
            # Use plain text, convert to HTML with line breaks
            escaped_text = html.escape(body_text.strip())
            formatted_text = escaped_text.replace('\n', '<br>\n')
            email_body = f"""
                <div style="border: 1px solid #ddd; padding: 15px; margin-top: 15px; background: white; white-space: pre-wrap; font-family: monospace;">
                    {formatted_text}
                </div>
            """
        
        # Build complete HTML page
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{subject}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .email-container {{
            background: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .email-header {{
            background: #f8f9fa;
            padding: 20px;
            border-bottom: 2px solid #e9ecef;
        }}
        .email-subject {{
            font-size: 24px;
            font-weight: 600;
            margin: 0 0 15px 0;
            color: #212529;
        }}
        .email-meta {{
            display: grid;
            gap: 8px;
            font-size: 14px;
            color: #495057;
        }}
        .email-meta-row {{
            display: flex;
        }}
        .email-meta-label {{
            font-weight: 600;
            min-width: 80px;
            color: #6c757d;
        }}
        .email-meta-value {{
            flex: 1;
        }}
        .email-body {{
            padding: 20px;
        }}
        .file-info {{
            background: #e9ecef;
            padding: 10px 20px;
            border-top: 1px solid #ddd;
            font-size: 12px;
            color: #6c757d;
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="email-header">
            <h1 class="email-subject">{subject}</h1>
            <div class="email-meta">
                <div class="email-meta-row">
                    <span class="email-meta-label">From:</span>
                    <span class="email-meta-value">{from_addr}</span>
                </div>
                <div class="email-meta-row">
                    <span class="email-meta-label">To:</span>
                    <span class="email-meta-value">{to_addr}</span>
                </div>
                <div class="email-meta-row">
                    <span class="email-meta-label">Date:</span>
                    <span class="email-meta-value">{date}</span>
                </div>
            </div>
        </div>
        <div class="email-body">
            {email_body}
        </div>
        <div class="file-info">
            File: {html.escape(file_path)}
        </div>
    </div>
</body>
</html>
        """
        
        return HTMLResponse(content=html_content)
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error rendering email: {str(e)}"
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
