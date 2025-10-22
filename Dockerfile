# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# Install uv package manager
RUN apt-get update && apt-get install -y curl tar \
  && curl -LsSf https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz -o uv.tar.gz \
  && mkdir uv-bin \
  && tar -xzf uv.tar.gz -C uv-bin \
  && mv uv-bin/uv-x86_64-unknown-linux-gnu/uv /usr/local/bin/uv \
  && chmod +x /usr/local/bin/uv \
  && uv --version \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install uv package manager
#RUN curl -LsSf https://astral.sh/uv/install.sh | bash -s -- --yes --root /usr/local
ENV PATH="/usr/local/bin:$PATH"

# Copy project files
COPY pyproject.toml .
COPY uv.lock .
COPY README.md .
RUN echo $PATH
RUN ls uv-bin
RUN ls /usr/local/bin
RUN ls -l /usr/local/bin/uv
ENV UV_VENV_DIR=/app/.venv
RUN which uv && uv --version
RUN uv venv
#COPY requirements.txt ./
RUN uv sync
COPY app ./app
ARG SENTENCE_TRANSFORMER_MODEL=all-mpnet-base-v2
ENV SENTENCE_TRANSFORMER_MODEL=${SENTENCE_TRANSFORMER_MODEL}

# Pre-warm sentence-transformers model in the container build to avoid runtime download
# Create necessary directories
RUN mkdir -p markdown_files chroma_db

# Install dependencies using uv (with fallback to pip)
#RUN uv pip install --system --no-cache -r requirements.txt || \
#    pip install --no-cache-dir -r requirements.txt


# Expose the FastAPI port
EXPOSE 8000

# Run the application
CMD ["uv","run" ,"uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
