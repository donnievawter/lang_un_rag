"""Configuration settings for the application."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Ollama Configuration
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "nomic-embed-text"
    
    # ChromaDB Configuration
    chroma_db_path: str = "./chroma_db"
    chroma_collection_name: str = "markdown_docs"
    
    # Markdown Files Configuration
    markdown_dir: str = "./markdown_files"
    
    # FastAPI Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
