from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = Field(default="")
    # Claude model used by the /ask endpoint. Common values:
    #   claude-sonnet-4-6  — current default · $3/$15 per 1M tokens · good RAG quality
    #   claude-opus-4-7    — most capable    · $5/$15 per 1M tokens · best reasoning
    #   claude-haiku-4-5   — fastest/cheap   · $1/$5  per 1M tokens · ok for simple Q&A
    # See docs/models.md for the rationale and when to switch.
    claude_model: str = Field(default="claude-sonnet-4-6")
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_collection: str = Field(default="papermind")
    database_url: str = Field(default="sqlite:///./papermind.db")
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    cors_origins: list[str] = Field(
        # PaperMind frontend is pinned to 5209 (strictPort:true) — Vite fails
        # loudly if the port is taken, so there's no need to allow-list siblings.
        default=[
            "http://localhost:5209",
        ]
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
