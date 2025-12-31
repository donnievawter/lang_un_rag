"""Vector store module for ChromaDB integration."""
from typing import List, Dict, Any, Optional
import uuid
import shutil
import os
import logging

import chromadb
from chromadb.config import Settings as ChromaSettings

from langchain_core.documents import Document

# sentence-transformers wrapper (optional dependency)
from sentence_transformers import SentenceTransformer

from langchain_chroma import Chroma

from app.config import settings

logger = logging.getLogger(__name__)


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
        """Index documents into the vector store. Replaces/creates the collection from documents."""
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

        # Pass explicit ids and use Chroma.from_documents (this will create/overwrite collection)
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

    # --- Re-added helpers for API compatibility ---

    def _get_collection_obj(self):
        """Return the underlying Chroma collection object in a few common shapes.

        Returns:
            chroma_collection_object
        Raises:
            RuntimeError if no collection object is accessible.
        """
        if self._vectorstore is None:
            self.initialize()

        # If _vectorstore is a LangChain Chroma wrapper, it often stores the inner chroma collection
        # at _vectorstore._collection. Otherwise the _vectorstore itself might be the collection.
        try:
            # LangChain Chroma wrapper
            coll = getattr(self._vectorstore, "_collection", None)
            if coll is not None:
                return coll
        except Exception:
            pass

        # Some wrappers expose client or underlying collection directly
        try:
            coll = getattr(self._vectorstore, "client", None)
            if coll is not None:
                return coll
        except Exception:
            pass

        # Fallback to assuming _vectorstore is already the collection
        if self._vectorstore is not None:
            return self._vectorstore

        raise RuntimeError("Unable to access underlying Chroma collection object")

    def get_all_chunks(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Return a list of chunks currently stored in the collection.

        Each item is a dict:
          {"id": <id>, "content": <document_text>, "metadata": <metadata_dict>}

        limit: optional integer to cap returned items (None means all).
        """
        coll = self._get_collection_obj()

        # NOTE: chroma Collection.get returns ids by default and some implementations
        # reject 'ids' as an include value. Do NOT include 'ids' in include list.
        # Request documents, metadatas, embeddings (embeddings optional).
        include_fields = ["documents", "metadatas", "embeddings"]

        # Try to call the Chroma collection get() method in a defensive way
        try:
            results = coll.get(limit=limit or None, include=include_fields)
        except TypeError:
            # Some wrappers may not accept keyword args; try positional (defensive)
            try:
                results = coll.get(limit or None, include_fields)
            except Exception as e:
                raise RuntimeError(f"Collection.get failed: {e}")
        except Exception as e:
            raise RuntimeError(f"Collection.get failed: {e}")

        # coll.get typically returns 'ids' by default (not necessarily in include), so read it defensively
        ids = results.get("ids", []) or []
        docs = results.get("documents", []) or []
        metadatas = results.get("metadatas", []) or []

        chunks = []
        for i, _id in enumerate(ids):
            content = docs[i] if i < len(docs) else ""
            metadata = metadatas[i] if i < len(metadatas) else {}
            chunks.append({"id": _id, "content": content, "metadata": metadata})

        return chunks

    def list_chunks(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Alias kept for compatibility with older names."""
        return self.get_all_chunks(limit=limit)

    def get_chunks_for_document(self, source_name: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Return chunks for a specific document source.

        Args:
            source_name: The source document name (from metadata['source'])
                        Can be absolute path, relative path, or just filename
            limit: Optional limit on number of chunks to return (None means all)

        Returns:
            List of chunk dictionaries matching the source
        """
        import os
        import unicodedata
        
        # Normalize Unicode characters to handle space variants
        normalized_source_name = unicodedata.normalize('NFKC', source_name)
        
        # Get all chunks first
        all_chunks = self.get_all_chunks(limit=None)
        
        # Filter by source with flexible matching
        matching_chunks = []
        for chunk in all_chunks:
            metadata = chunk.get("metadata", {})
            chunk_source = metadata.get("source", "")
            normalized_chunk_source = unicodedata.normalize('NFKC', chunk_source)
            
            # Try multiple matching strategies:
            # 1. Exact match (after normalization)
            if normalized_chunk_source == normalized_source_name:
                matching_chunks.append(chunk)
                if limit is not None and len(matching_chunks) >= limit:
                    break
                continue
            
            # 2. If source_name looks like a relative path, see if chunk_source ends with it
            if not normalized_source_name.startswith('/') and normalized_chunk_source.endswith('/' + normalized_source_name):
                matching_chunks.append(chunk)
                if limit is not None and len(matching_chunks) >= limit:
                    break
                continue
            
            # 3. If source_name is absolute, see if it matches the relative part
            if normalized_source_name.startswith('/'):
                # Extract relative part from chunk_source (after /app/markdown_files/)
                if '/markdown_files/' in normalized_chunk_source:
                    relative_part = normalized_chunk_source.split('/markdown_files/')[-1]
                    if relative_part == normalized_source_name.lstrip('/'):
                        matching_chunks.append(chunk)
                        if limit is not None and len(matching_chunks) >= limit:
                            break
                        continue
            
            # 4. Filename-only match (after normalization)
            source_filename = os.path.basename(normalized_source_name)
            chunk_filename = os.path.basename(normalized_chunk_source)
            if source_filename == chunk_filename:
                matching_chunks.append(chunk)
                if limit is not None and len(matching_chunks) >= limit:
                    break
        
        return matching_chunks

    def clear_collection(self) -> Dict[str, Any]:
        """Attempt to remove all items from the collection.

        Returns a status dict.
        """
        if self._vectorstore is None:
            self.initialize()

        coll = self._get_collection_obj()

        # Primary attempt: use collection.delete() API to remove all items
        try:
            # First, try to get all IDs in the collection
            try:
                # Get all IDs to delete them explicitly
                results = coll.get(include=[])  # Only get IDs, not documents or metadata
                ids_to_delete = results.get("ids", [])
                
                if ids_to_delete:
                    # Delete by providing specific IDs
                    coll.delete(ids=ids_to_delete)
                else:
                    # Collection is already empty
                    return {"status": "success", "cleared": True, "method": "collection_already_empty"}
                    
            except Exception:
                # Fallback: try delete with where clause that matches everything
                try:
                    # Use a where clause that should match all documents
                    coll.delete(where={"$or": [{"source": {"$ne": ""}}, {"source": {"$eq": ""}}]})
                except Exception:
                    # Last resort: try to delete by metadata catch-all
                    coll.delete(where={})
                    
        except Exception as e:
            # As a fallback, remove the persist_directory and reinitialize the store.
            try:
                if os.path.isdir(self.persist_directory):
                    shutil.rmtree(self.persist_directory)
            except Exception as e2:
                raise RuntimeError(f"Failed to clear collection via API ({e}) and failed to remove persist directory ({e2})")
            # Recreate an empty store instance on next initialize
            self._vectorstore = None
            return {"status": "success", "cleared": True, "method": "persist_dir_removed"}

        return {"status": "success", "cleared": True, "method": "collection.delete_called"}

    def reindex_documents(self, documents: List[Document]) -> Dict[str, Any]:
        """Clear existing collection and index provided documents."""
        # Clear existing collection
        clear_res = self.clear_collection()

        # Re-index (index_documents will create or overwrite collection)
        index_res = self.index_documents(documents)

        return {
            "status": "success",
            "cleared": clear_res,
            "indexed": index_res
        }

    def get_collection_stats(self) -> Dict[str, Any]:
        """Return some basic statistics about the collection."""
        stats = {
            "collection_name": self.collection_name,
            "persist_directory": self.persist_directory,
            "document_count": 0,
        }
        try:
            chunks = self.get_all_chunks(limit=None)
            stats["document_count"] = len(chunks)
        except Exception:
            # If we can't enumerate, try alternate method by asking the underlying collection for count
            try:
                coll = self._get_collection_obj()
                # Some chroma wrappers have a count() or len-like API
                if hasattr(coll, "count"):
                    stats["document_count"] = coll.count()
                elif hasattr(coll, "get"):
                    res = coll.get(limit=None, include=["documents", "metadatas"])
                    stats["document_count"] = len(res.get("ids", []))
            except Exception:
                stats["document_count"] = 0

        return stats

    def get_indexed_documents(self) -> List[Dict[str, Any]]:
        """Return a list of unique documents that have been indexed.
        
        Returns:
            List of dicts with document info: {"source": str, "chunk_count": int, "file_type": str}
        """
        try:
            all_chunks = self.get_all_chunks(limit=None)
            
            # Group chunks by source
            doc_map = {}
            for chunk in all_chunks:
                source = chunk.get("metadata", {}).get("source")
                if source:
                    if source not in doc_map:
                        doc_map[source] = {
                            "source": source,
                            "chunk_count": 0,
                            "file_type": chunk.get("metadata", {}).get("file_type", "unknown")
                        }
                    doc_map[source]["chunk_count"] += 1
            
            # Return sorted list by source name
            return sorted(doc_map.values(), key=lambda x: x["source"])
        except Exception as e:
            logger.error(f"Error getting indexed documents: {e}")
            return []

    def add_documents_incremental(self, documents: List[Document]) -> Dict[str, Any]:
        """Add new documents to the existing collection without clearing it first.
        
        Args:
            documents: List of Document objects to add
            
        Returns:
            Dict with status and counts
        """
        logger.info(f"🎯 add_documents_incremental called with {len(documents)} documents")
        print(f"🎯 add_documents_incremental called with {len(documents)} documents")
        
        if self._vectorstore is None:
            self.initialize()
        
        if not documents:
            logger.info("No documents to add, returning early")
            return {"status": "success", "documents_added": 0, "ids": []}
        
        # Generate unique IDs for new documents
        ids = []
        for i, doc in enumerate(documents):
            source = doc.metadata.get("source")
            chunk_id = doc.metadata.get("chunk_id")
            if source is not None and chunk_id is not None:
                unique_id = f"{source}::{chunk_id}"
            else:
                unique_id = str(uuid.uuid4())
            ids.append(unique_id)
        
        # Add documents in batches to avoid ChromaDB batch size limits
        # ChromaDB has a max batch size limit (typically ~5000), so we batch to be safe
        BATCH_SIZE = 1000  # Conservative batch size to avoid hitting limits
        total_batches = (len(documents) + BATCH_SIZE - 1) // BATCH_SIZE  # Ceiling division
        
        logger.info(f"🚀 Starting batch processing: {len(documents)} documents in {total_batches} batches of {BATCH_SIZE}")
        print(f"🚀 Starting batch processing: {len(documents)} documents in {total_batches} batches of {BATCH_SIZE}")
        
        total_added = 0
        
        for i in range(0, len(documents), BATCH_SIZE):
            batch_docs = documents[i:i + BATCH_SIZE]
            batch_texts = [doc.page_content for doc in batch_docs]
            batch_metadatas = [doc.metadata for doc in batch_docs]
            batch_ids = ids[i:i + BATCH_SIZE]
            
            batch_num = i//BATCH_SIZE + 1
            logger.info(f"📦 Processing batch {batch_num}/{total_batches}: {len(batch_docs)} documents")
            print(f"📦 Processing batch {batch_num}/{total_batches}: {len(batch_docs)} documents")
            
            self._vectorstore.add_texts(
                texts=batch_texts,
                metadatas=batch_metadatas,
                ids=batch_ids
            )
            
            total_added += len(batch_docs)
            logger.info(f"✅ Batch {batch_num}/{total_batches} completed")
            print(f"✅ Batch {batch_num}/{total_batches} completed")
        
        logger.info(f"🎉 All batches completed! Successfully added {total_added} documents")
        print(f"🎉 All batches completed! Successfully added {total_added} documents")
        
        return {
            "status": "success", 
            "documents_added": total_added,
            "ids": ids
        }
    
    def delete_documents_by_source(self, source_file: str) -> Dict[str, Any]:
        """Delete all documents/chunks that came from a specific source file.
        
        Args:
            source_file: The source file path to delete documents for
            
        Returns:
            Dict with status and deletion count
        """
        if self._vectorstore is None:
            self.initialize()
        
        coll = self._get_collection_obj()
        deleted_count = 0
        
        try:
            # Find all documents with this source
            results = coll.get(
                where={"source": source_file},
                include=["documents", "metadatas"]
            )
            
            ids_to_delete = results.get("ids", [])
            
            if ids_to_delete:
                # Delete the documents
                coll.delete(ids=ids_to_delete)
                deleted_count = len(ids_to_delete)
                logger.info(f"Deleted {deleted_count} chunks from source: {source_file}")
            
        except Exception as e:
            logger.error(f"Error deleting documents for source {source_file}: {e}")
            return {"status": "error", "message": str(e), "deleted_count": 0}
        
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "source_file": source_file
        }
    
    def update_documents_by_source(self, source_file: str, new_documents: List[Document]) -> Dict[str, Any]:
        """Update documents for a specific source file (delete old, add new).
        
        Args:
            source_file: The source file path to update
            new_documents: New documents to replace the old ones
            
        Returns:
            Dict with status and operation counts
        """
        # Delete existing documents for this source
        delete_result = self.delete_documents_by_source(source_file)
        
        # Add new documents
        add_result = self.add_documents_incremental(new_documents)
        
        return {
            "status": "success",
            "source_file": source_file,
            "deleted_count": delete_result.get("deleted_count", 0),
            "added_count": add_result.get("documents_added", 0),
            "new_ids": add_result.get("ids", [])
        }


# singleton used by the app
vector_store = VectorStore()