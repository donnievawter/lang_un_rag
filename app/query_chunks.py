from typing import List
from langchain_core.documents import Document
from app.vector_store import vector_store

def query_chunks(prompt: str, k: int = 5) -> List[Document]:
    # Embed the prompt using the vector store's embedding model
    query_embedding = vector_store.embeddings.embed_query(prompt)
    print(f"Embedding preview: {query_embedding[:5]}... len={len(query_embedding)}")
    # Search for similar chunks
    results = vector_store.similarity_search_by_vector(query_embedding, k=k)
    return results