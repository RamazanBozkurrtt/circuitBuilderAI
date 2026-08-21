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
