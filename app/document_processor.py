"""Document processing module for parsing and chunking markdown files."""
import os
from pathlib import Path
from typing import List

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain.schema import Document

from app.config import settings


class DocumentProcessor:
    """Processes markdown documents for indexing."""
    
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
    
    def load_markdown_files(self, directory: str) -> List[Document]:
        """Load all markdown files from a directory.
        
        Args:
            directory: Path to directory containing markdown files
            
        Returns:
            List of Document objects
        """
        documents = []
        markdown_dir = Path(directory)
        
        if not markdown_dir.exists():
            raise ValueError(f"Directory {directory} does not exist")
        
        # Find all markdown files
        markdown_files = list(markdown_dir.glob("**/*.md"))
        
        if not markdown_files:
            raise ValueError(f"No markdown files found in {directory}")
        
        for file_path in markdown_files:
            try:
                loader = UnstructuredMarkdownLoader(str(file_path))
                file_docs = loader.load()
                
                # Add source metadata
                for doc in file_docs:
                    doc.metadata["source"] = str(file_path.relative_to(markdown_dir))
                    doc.metadata["filename"] = file_path.name
                
                documents.extend(file_docs)
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
        
        # Add chunk metadata
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_id"] = i
        
        return chunks
    
    def process_directory(self, directory: str = None) -> List[Document]:
        """Load and chunk all markdown files from a directory.
        
        Args:
            directory: Path to directory containing markdown files.
                      Defaults to settings.markdown_dir
            
        Returns:
            List of chunked Document objects
        """
        if directory is None:
            directory = settings.markdown_dir
        
        documents = self.load_markdown_files(directory)
        chunks = self.chunk_documents(documents)
        
        return chunks
