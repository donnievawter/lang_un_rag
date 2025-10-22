from typing import Optional, List
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    markdown_dir: str = Field("./markdown_files", env="MARKDOWN_DIR")
    ollama_base_url: str = Field("http://localhost:11434", env="OLLAMA_BASE_URL")
    ollama_model: str = Field("ollama-model", env="OLLAMA_MODEL")
    chroma_collection_name: str = Field("markdown_docs", env="CHROMA_COLLECTION_NAME")
    chroma_db_path: str = Field("./chroma_db", env="CHROMA_DB_PATH")
    api_host: str = Field("0.0.0.0", env="API_HOST")
    api_port: int = Field(8000, env="API_PORT")
    allowed_extensions: List[str] = Field(
        default=[".md", ".markdown", ".pdf", ".docx", ".pptx", ".html", ".htm",
                 ".txt", ".csv", ".png", ".jpg", ".jpeg", ".tiff", ".tif"],
        env="ALLOWED_EXTENSIONS"
    )

    # New: directories to exclude during walking (relative directory names)
    exclude_dirs: List[str] = Field(
        default=["chroma_db", ".git"],
        env="EXCLUDE_DIRS"
    )


    # Optional sentence-transformers model name (Hugging Face / sentence-transformers)
    sentence_transformer_model: Optional[str] = Field(None, env="SENTENCE_TRANSFORMER_MODEL")

    # pydantic-settings configuration: env file and encoding
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

# instantiate settings
settings = Settings()