#!/bin/bash
# Script to run the RAG system

# Check if .env exists
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
fi

# Check if markdown_files directory exists
if [ ! -d markdown_files ]; then
    echo "Creating markdown_files directory..."
    mkdir -p markdown_files
fi

# Check if chroma_db directory exists
if [ ! -d chroma_db ]; then
    echo "Creating chroma_db directory..."
    mkdir -p chroma_db
fi

echo "Starting the RAG system with Docker Compose..."
docker-compose up --build
