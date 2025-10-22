#!/usr/bin/env python3
"""
Reindex script that uses app.extractors and app.chunker to create Documents and push to Chroma.
This script is intended to run locally in your container or venv.

Usage:
  python scripts/reindex_with_extractors.py --input-dir ./docs --collection my_collection
"""
import os
import argparse
from typing import List

from langchain_core.documents import Document
from app.vector_store import vector_store  # uses your existing Chroma wrapper
from app.extractors import extract
from app.chunker import chunk_text

def gather_files(input_dir: str):
    for root, _, files in os.walk(input_dir):
        for f in files:
            # skip some common unwanted files
            if f.startswith(".") or f.endswith(".lock"):
                continue
            yield os.path.join(root, f)

def build_documents_from_file(path: str):
    pieces = extract(path)
    docs = []
    for p in pieces:
        text = p.get("text", "")
        metadata = p.get("metadata", {}).copy()
        # chunk
        chunks = chunk_text(text, chunk_size=500, overlap=100)
        for i, chunk in enumerate(chunks):
            md = metadata.copy()
            md["chunk_id"] = f"{os.path.basename(path)}::{i}"
            md["source"] = os.path.basename(path)
            docs.append(Document(page_content=chunk, metadata=md))
    return docs

def main(args):
    input_dir = args.input_dir
    all_docs = []
    for path in gather_files(input_dir):
        print(f"Extracting: {path}")
        docs = build_documents_from_file(path)
        if docs:
            all_docs.extend(docs)
            print(f" -> {len(docs)} chunks")
    if not all_docs:
        print("No documents to index.")
        return
    # Index in batches to avoid memory surges
    BATCH = 200
    for i in range(0, len(all_docs), BATCH):
        batch = all_docs[i:i+BATCH]
        print(f"Indexing batch {i//BATCH + 1} ({len(batch)} docs)")
        vector_store.index_documents(batch)
    print("Reindex complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="./docs", help="Directory containing documents to index")
    parser.add_argument("--collection", default=None, help="Optional collection name")
    args = parser.parse_args()
    main(args)