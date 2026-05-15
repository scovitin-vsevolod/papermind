from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ask, documents

app = FastAPI(title="PaperMind", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(ask.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "claude_model": settings.claude_model,
        "embedding_model": settings.embedding_model,
    }
