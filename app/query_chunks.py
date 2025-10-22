from typing import List
from langchain_core.documents import Document
from app.vector_store import vector_store

def query_chunks(prompt: str, k: int = 5) -> List[Document]:
    # Use the vector_store's embed_query helper (robust fallback) so query and documents use the same code-path
    query_embedding = vector_store.embed_query(prompt)
    print(f"Embedding preview: {query_embedding[:5]}... len={len(query_embedding)}")
    # Search for similar chunks
    results = vector_store.similarity_search_by_vector(query_embedding, k=k)
    return results