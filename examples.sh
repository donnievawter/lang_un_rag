#!/bin/bash
# Example API calls for the RAG system

BASE_URL="http://localhost:8000"

echo "=== RAG System API Examples ==="
echo ""

# Health check
echo "1. Health Check"
echo "   curl $BASE_URL/health"
curl -s $BASE_URL/health | jq '.'
echo ""

# Root endpoint
echo "2. API Information"
echo "   curl $BASE_URL/"
curl -s $BASE_URL/ | jq '.'
echo ""

# Index documents
echo "3. Index Documents"
echo "   curl -X POST $BASE_URL/index"
curl -s -X POST $BASE_URL/index | jq '.'
echo ""

# Get collection stats
echo "4. Collection Statistics"
echo "   curl $BASE_URL/stats"
curl -s $BASE_URL/stats | jq '.'
echo ""

# Get chunks (limited to 5)
echo "5. Get Chunks (limit=5)"
echo "   curl $BASE_URL/get_chunks?limit=5"
curl -s "$BASE_URL/get_chunks?limit=5" | jq '.'
echo ""

# Reindex documents
echo "6. Reindex Documents"
echo "   curl -X POST $BASE_URL/reindex"
curl -s -X POST $BASE_URL/reindex | jq '.'
echo ""

echo "=== Examples completed ==="
