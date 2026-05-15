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
        # Vite picks the next free port when 5173 is taken (e.g. when another
        # project is also running). Allow the first three to cover the common
        # case of one or two sibling dev servers already up.
        default=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
        ]
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
