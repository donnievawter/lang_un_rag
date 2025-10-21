"""Vector store module for ChromaDB integration."""
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain.schema import Document
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import Chroma

from app.config import settings


class VectorStore:
    """Manages the ChromaDB vector store."""
    
    def __init__(self):
        """Initialize the vector store."""
        self.embeddings = OllamaEmbeddings(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
        )
        self.collection_name = settings.chroma_collection_name
        self.persist_directory = settings.chroma_db_path
        self._vectorstore: Optional[Chroma] = None
    
    def initialize(self):
        """Initialize or load the vector store."""
        self._vectorstore = Chroma(
            collection_name=self.collection_name,
            embedding_function=self.embeddings,
            persist_directory=self.persist_directory,
        )
    
    def index_documents(self, documents: List[Document]) -> Dict[str, Any]:
        """Index documents into the vector store.
        
        Args:
            documents: List of Document objects to index
            
        Returns:
            Dictionary with indexing results
        """
        if self._vectorstore is None:
            self.initialize()
        
        # Add documents to the vector store
        ids = self._vectorstore.add_documents(documents)
        
        return {
            "status": "success",
            "documents_indexed": len(documents),
            "ids": ids
        }
    
    def reindex_documents(self, documents: List[Document]) -> Dict[str, Any]:
        """Clear the existing collection and reindex documents.
        
        Args:
            documents: List of Document objects to index
            
        Returns:
            Dictionary with reindexing results
        """
        # Delete the existing collection
        self.clear_collection()
        
        # Re-initialize and index
        self.initialize()
        return self.index_documents(documents)
    
    def clear_collection(self):
        """Clear the existing collection."""
        try:
            client = chromadb.PersistentClient(
                path=self.persist_directory,
            )
            try:
                client.delete_collection(name=self.collection_name)
            except Exception:
                pass  # Collection doesn't exist
            self._vectorstore = None
        except Exception as e:
            print(f"Error clearing collection: {e}")
    
    def get_all_chunks(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve all chunks from the vector store.
        
        Args:
            limit: Maximum number of chunks to return
            
        Returns:
            List of dictionaries containing chunk data
        """
        if self._vectorstore is None:
            self.initialize()
        
        try:
            # Get the collection
            collection = self._vectorstore._collection
            
            # Get all documents
            results = collection.get(
                limit=limit if limit else None,
                include=["documents", "metadatas", "embeddings"]
            )
            
            chunks = []
            for i in range(len(results["ids"])):
                chunk = {
                    "id": results["ids"][i],
                    "content": results["documents"][i],
                    "metadata": results["metadatas"][i] if results["metadatas"] else {},
                }
                chunks.append(chunk)
            
            return chunks
        except Exception as e:
            print(f"Error retrieving chunks: {e}")
            return []
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the collection.
        
        Returns:
            Dictionary with collection statistics
        """
        if self._vectorstore is None:
            self.initialize()
        
        try:
            collection = self._vectorstore._collection
            count = collection.count()
            
            return {
                "collection_name": self.collection_name,
                "document_count": count,
                "persist_directory": self.persist_directory,
            }
        except Exception as e:
            return {
                "collection_name": self.collection_name,
                "document_count": 0,
                "persist_directory": self.persist_directory,
                "error": str(e)
            }
