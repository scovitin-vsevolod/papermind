from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ask, auth, documents, graph, health

app = FastAPI(title="PaperMind", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# health first so it's always reachable even if a later router fails to import.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(ask.router)
app.include_router(graph.router)
