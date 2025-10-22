"""
Simple chunker: coarse, word-based chunking with overlap.
You can replace this with token-based chunking (tiktoken) later if desired.
"""
from typing import List

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
    if not text:
        return []
    words = text.split()
    if len(words) <= chunk_size:
        return [" ".join(words)]
    chunks = []
    i = 0
    while i < len(words):
        chunk = words[i:i + chunk_size]
        chunks.append(" ".join(chunk))
        i += chunk_size - overlap
    return chunks