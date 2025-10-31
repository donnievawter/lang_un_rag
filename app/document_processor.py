"""Document processing module for parsing and chunking a variety of document types."""
import os
from pathlib import Path
from typing import List, Set

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain_core.documents import Document

from app.config import settings

# If you later want token-aware chunking, replace with tiktoken-based splitter
text_splitter = RecursiveCharacterTextSplitter(chunk_size=100, chunk_overlap=0)


class DocumentProcessor:
    """Processes documents for indexing."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """Initialize the document processor.

        Args:
            chunk_size: Size of text chunks
            chunk_overlap: Overlap between chunks
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
        )

    def _is_excluded(self, path: Path, root: Path, exclude_dirs: Set[str]) -> bool:
        """Return True if path is inside any excluded directory name."""
        try:
            rel = path.relative_to(root)
        except Exception:
            return True
        parts = [p for p in rel.parts]
        for p in parts:
            if p in exclude_dirs:
                return True
        return False

    def load_documents(self, directory: str) -> List[Document]:
        """Load documents of multiple types from a directory (recursively).

        Uses UnstructuredMarkdownLoader for markdown files, and the generic
        extract() function (app.extractors) for other supported types.

        Args:
            directory: Path to directory containing documents

        Returns:
            List of Document objects
        """
        documents: List[Document] = []
        docs_dir = Path(directory).resolve()

        # Validate path and existence
        try:
            if ".." in str(docs_dir):
                raise ValueError("Path traversal not allowed")
            if not docs_dir.exists():
                raise ValueError(f"Directory {directory} does not exist")
            if not docs_dir.is_dir():
                raise ValueError(f"{directory} is not a directory")
        except (OSError, RuntimeError) as e:
            raise ValueError(f"Invalid directory path: {e}")

        # Build allowed extensions and exclude list from settings (fall back to defaults)
        allowed_exts = {ext.lower() for ext in getattr(settings, "allowed_extensions", [
            ".md", ".markdown", ".pdf", ".docx", ".pptx", ".html", ".htm", ".txt", ".csv", ".png", ".jpg", ".jpeg", ".tiff", ".tif"
        ])}
        exclude_dirs = set(getattr(settings, "exclude_dirs", ["chroma_db", ".git"]))

        # Lazy import of extractor so we don't hard-fail if not present during earlier phases
        try:
            from app.extractors import extract as generic_extract
        except Exception:
            generic_extract = None

        # Recursively walk tree and pick files with allowed extensions, excluding exclude_dirs
        all_files = list(docs_dir.rglob("*"))
        candidate_files = [p for p in all_files if p.is_file() and p.suffix.lower() in allowed_exts]
        if not candidate_files:
            raise ValueError(f"No supported documents found in {directory}")

        for file_path in candidate_files:
            if self._is_excluded(file_path, docs_dir, exclude_dirs):
                # skip files in excluded directories
                continue

            try:
                suffix = file_path.suffix.lower()
                rel_source = str(file_path.relative_to(docs_dir))
                print(f"Loading document: {rel_source}")
                # Markdown: use UnstructuredMarkdownLoader to preserve structure
                if suffix in {".md", ".markdown"}:
                    loader = UnstructuredMarkdownLoader(str(file_path))
                    file_docs = loader.load()
                    for doc in file_docs:
                        doc.metadata["source"] = rel_source
                        doc.metadata["filename"] = file_path.name
                    documents.extend(file_docs)
                    continue

                # For non-markdown types: use the extractors module if available
                if generic_extract:
                    pieces = generic_extract(str(file_path))
                    for p in pieces:
                        text = p.get("text", "")
                        md = p.get("metadata", {}).copy()
                        # ensure source and filename metadata exist and use relative paths
                        md.setdefault("source", rel_source)
                        md.setdefault("filename", file_path.name)
                        # Create langchain Document
                        documents.append(Document(page_content=text, metadata=md))
                    continue

                # Fallback: attempt to read plain text
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    if text.strip():
                        documents.append(Document(page_content=text, metadata={"source": rel_source, "filename": file_path.name}))
                except Exception:
                    print(f"Skipping unsupported file: {file_path}")
                    continue

            except Exception as e:
                print(f"Error loading {file_path}: {e}")
                continue

        return documents

    def chunk_documents(self, documents: List[Document]) -> List[Document]:
        """Split documents into chunks.

        Args:
            documents: List of Document objects to chunk

        Returns:
            List of chunked Document objects
        """
        chunks = self.text_splitter.split_documents(documents)

        # Add chunk metadata; make chunk_id include source to keep it unique across files
        for i, chunk in enumerate(chunks):
            source = chunk.metadata.get("source", "unknown")
            chunk.metadata["chunk_id"] = f"{source}::{i}"

        return chunks

    def process_file(self, file_path: str) -> List[Document]:
        """Load and chunk a single file.
        
        Args:
            file_path: Absolute path to the file to process
            
        Returns:
            List of chunked Document objects
        """
        file_path = Path(file_path)
        
        # Validate file
        if not file_path.exists():
            raise ValueError(f"File {file_path} does not exist")
        if not file_path.is_file():
            raise ValueError(f"{file_path} is not a file")
        
        # Check allowed extensions
        allowed_exts = {ext.lower() for ext in getattr(settings, "allowed_extensions", [
            ".md", ".markdown", ".pdf", ".docx", ".pptx", ".html", ".htm", ".txt", ".csv", ".png", ".jpg", ".jpeg", ".tiff", ".tif"
        ])}
        
        if file_path.suffix.lower() not in allowed_exts:
            return []  # Skip unsupported files
        
        # Load the single file
        documents = []
        rel_source = str(file_path)  # Use absolute path as source for consistency
        
        try:
            # Try loading with extractors first
            try:
                from app.extractors import extract as generic_extract
                text = generic_extract(str(file_path))
                if text and text.strip():
                    documents.append(Document(page_content=text, metadata={"source": rel_source, "filename": file_path.name}))
                else:
                    # If extractor returns empty, try fallback
                    raise ValueError("No content from extractor")
            except Exception:
                # Fallback: try markdown loader for .md files
                if file_path.suffix.lower() in [".md", ".markdown"]:
                    try:
                        loader = UnstructuredMarkdownLoader(str(file_path))
                        docs = loader.load()
                        for doc in docs:
                            doc.metadata.update({"source": rel_source, "filename": file_path.name})
                        documents.extend(docs)
                    except Exception:
                        pass
                
                # Final fallback: read as plain text
                if not documents:
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read()
                        if text.strip():
                            documents.append(Document(page_content=text, metadata={"source": rel_source, "filename": file_path.name}))
                    except Exception:
                        raise ValueError(f"Could not read file: {file_path}")
                        
        except Exception as e:
            raise ValueError(f"Error processing file {file_path}: {e}")
        
        # Chunk the documents
        if documents:
            chunks = self.chunk_documents(documents)
            return chunks
        
        return []

    def process_directory(self) -> List[Document]:
        """Load and chunk all supported files from the configured directory."""
        directory = settings.markdown_dir  # kept name for compatibility; points at root docs folder
        documents = self.load_documents(directory)
        chunks = self.chunk_documents(documents)

        return chunks