from functools import lru_cache
from typing import Literal

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
    # OpenAI side of side-by-side comparison (Phase 2). Common values:
    #   gpt-4o            — current flagship · ~$5/$20 per 1M tokens
    #   gpt-4o-mini       — cheaper          · ~$0.15/$0.60 per 1M tokens
    #   gpt-4-turbo       — older flagship
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o")
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_collection: str = Field(default="papermind")
    database_url: str = Field(default="sqlite:///./papermind.db")
    # Embedding backend selection — "sentence-transformers" (local, free,
    # 384 dim) or "voyage" (API, paid, 1024 dim). Different dims → different
    # Qdrant collections, so both can coexist for the Phase 2 experiment.
    embedding_provider: Literal["sentence-transformers", "voyage"] = Field(
        default="sentence-transformers"
    )
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    voyage_api_key: str = Field(default="")
    voyage_model: str = Field(default="voyage-3")
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
