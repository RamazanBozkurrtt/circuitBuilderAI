from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    ollama_timeout_seconds: float = Field(default=30.0, gt=0)
    ollama_max_retries: int = Field(default=2, ge=0, le=10)
    max_design_iterations: int = Field(default=3, ge=0, le=100)
    ai_pcb_projects_dir: Path = Path("projects")
    ai_pcb_knowledge_dir: Path = Path("knowledge")
    ai_pcb_index_dir: Path = Path("projects/local_runtime/indexes")
    ai_pcb_ingestion_dir: Path = Path("projects/local_runtime/ingestion")
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_device: str = "cpu"
    embedding_cache_dir: Path = Path("projects/local_runtime/embedding_cache")
    embedding_batch_size: int = Field(default=16, ge=1, le=512)
    retrieval_collection: str = "engineering_evidence"
    chunk_target_characters: int = Field(default=1800, ge=300, le=12000)
    chunk_max_characters: int = Field(default=3200, ge=500, le=20000)
    ocr_minimum_characters: int = Field(default=40, ge=0, le=1000)
    acquisition_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    acquisition_max_redirects: int = Field(default=5, ge=0, le=10)
    trusted_manufacturer_domains: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "Analog Devices": ["analog.com"],
            "Texas Instruments": ["ti.com"],
        }
    )
