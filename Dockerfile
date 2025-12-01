# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
  tesseract-ocr \
  poppler-utils \
  libmagic1 \
  tesseract-ocr-eng \
  ca-certificates \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY requirements.txt .
COPY README.md .

# Create virtual environment
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install PyTorch CPU-only first to avoid GPU dependencies
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Install sentence-transformers with CPU-only PyTorch
RUN pip install --no-cache-dir sentence-transformers

# Install remaining dependencies with pip
RUN pip install --no-cache-dir -r requirements.txt

# Download NLTK punkt tokenizer data for sentence splitting
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

# Copy application code
COPY app ./app
ARG SENTENCE_TRANSFORMER_MODEL=all-mpnet-base-v2
ENV SENTENCE_TRANSFORMER_MODEL=${SENTENCE_TRANSFORMER_MODEL}

# Pre-warm sentence-transformers model in the container build to avoid runtime download
# Create necessary directories
RUN mkdir -p markdown_files chroma_db

# Dependencies are already installed above


# Expose the FastAPI port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
