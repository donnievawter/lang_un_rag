"""Vector store module for ChromaDB integration."""
from typing import List, Dict, Any, Optional
import uuid

import chromadb
from chromadb.config import Settings as ChromaSettings

from langchain_core.documents import Document

# sentence-transformers wrapper (optional dependency)
from sentence_transformers import SentenceTransformer

from langchain_chroma import Chroma

from app.config import settings


class SentenceTransformerWrapper:
    """Simple wrapper providing embed_documents and embed_query to match the previous interface."""

    def __init__(self, model_name: str = "all-mpnet-base-v2"):
        self.model_name = model_name
        # load SentenceTransformer model (will download on first run if not present)
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embs = self.model.encode(texts, show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=False)
        return [e.tolist() for e in embs]

    def embed_query(self, text: str) -> List[float]:
        emb = self.model.encode([text], show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=False)[0]
        return emb.tolist()


class VectorStore:
    """Manages the ChromaDB vector store."""
    
    def __init__(self):
        """Initialize the vector store."""
        # safe: read from settings with a fallback to a sensible default
        model_name = getattr(settings, "sentence_transformer_model", None) or "all-mpnet-base-v2"
        self.embeddings = SentenceTransformerWrapper(model_name=model_name)

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
        print(f"Chroma class: {self._vectorstore.__class__}")
    
    def index_documents(self, documents: List[Document]) -> Dict[str, Any]:
        """Index documents into the vector store."""
        if self._vectorstore is None:
            self.initialize()
        
        # Ensure unique ids
        ids = []
        for i, doc in enumerate(documents):
            source = doc.metadata.get("source")
            chunk_id = doc.metadata.get("chunk_id")
            if source is not None and chunk_id is not None:
                unique_id = f"{source}::{chunk_id}"
            else:
                unique_id = str(uuid.uuid4())
            ids.append(unique_id)

        # Pass explicit ids and use Chroma.from_documents
        self._vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            collection_name=self.collection_name,
            persist_directory=self.persist_directory,
            ids=ids,
        )

        return {
            "status": "success",
            "documents_indexed": len(documents),
            "ids": ids
        }

    def embed_query(self, text: str) -> List[float]:
        """Return a single embedding for the given text."""
        return self.embeddings.embed_query(text)

    def similarity_search_by_vector(self, embedding: List[float], k: int = 5) -> List[Document]:
        """Retrieve top-k most similar chunks to the given embedding."""
        if self._vectorstore is None:
            self.initialize()
        return self._vectorstore.similarity_search_by_vector(embedding, k=k)

    # keep existing methods intact (get_all_chunks, reindex_documents, clear_collection, get_collection_stats, etc.)

# singleton used by the app
vector_store = VectorStore()