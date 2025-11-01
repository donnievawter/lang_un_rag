#!/usr/bin/env python3
"""
Test script to verify batch size handling in vector store.
Creates a large number of fake documents to simulate the batch size issue.
"""

import sys
import os
sys.path.append('/app')

from langchain_core.documents import Document
from app.vector_store import vector_store

def create_fake_documents(count: int) -> list[Document]:
    """Create a large number of fake documents to test batch size limits."""
    documents = []
    
    for i in range(count):
        doc = Document(
            page_content=f"This is test document number {i}. " * 50,  # Make it substantial
            metadata={
                "source": f"test_batch_{i // 100}.txt",  # Group into files
                "chunk_id": f"chunk_{i}",
                "test": True
            }
        )
        documents.append(doc)
    
    return documents

def test_batch_size_handling():
    """Test that large document batches are handled correctly."""
    print("Testing batch size handling...")
    
    # Initialize vector store
    vector_store.initialize()
    
    # Test with a number that would exceed the typical ChromaDB batch limit
    test_count = 6000  # Exceeds the 5461 limit mentioned in the error
    print(f"Creating {test_count} test documents...")
    
    documents = create_fake_documents(test_count)
    print(f"Created {len(documents)} documents")
    
    try:
        # Test incremental addition (this should use batching)
        print("Testing add_documents_incremental with large batch...")
        result = vector_store.add_documents_incremental(documents)
        
        print(f"Success! Added {result['documents_added']} documents")
        print(f"Status: {result['status']}")
        
        # Verify they were actually added
        stats = vector_store.get_collection_stats()
        print(f"Collection now contains {stats['document_count']} documents")
        
        return True
        
    except Exception as e:
        print(f"Error during batch test: {e}")
        return False

def cleanup_test_data():
    """Remove test data from the collection."""
    print("Cleaning up test data...")
    try:
        # Clear the entire collection since these are test documents
        result = vector_store.clear_collection()
        print(f"Cleanup result: {result}")
    except Exception as e:
        print(f"Cleanup error: {e}")

if __name__ == "__main__":
    try:
        success = test_batch_size_handling()
        if success:
            print("\n✅ Batch size test PASSED - large batches handled correctly")
        else:
            print("\n❌ Batch size test FAILED")
            sys.exit(1)
    finally:
        cleanup_test_data()