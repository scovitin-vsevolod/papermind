# PaperMind

Personal research companion built on the Claude API. Upload documents
(PDF, DOCX, MD, TXT, HTML, …), ask questions grounded in their content
with citations, and (later) build a knowledge graph from them.

Designed as a learning project + portfolio piece for a Junior AI
Developer interview.

- [`CLAUDE.md`](CLAUDE.md) — stack rationale and assistant context
- [`ROADMAP.md`](ROADMAP.md) — step-by-step plan with progress checkboxes
- [`docs/models.md`](docs/models.md) — current model defaults and how to switch
- [`docs/retro.md`](docs/retro.md) — Phase 1 retro: surprises, lessons, interview talking points

## Stack

- **Backend:** Python 3.11+ · FastAPI · SQLAlchemy + SQLite · `uv`
- **LLM:** Claude (`anthropic` SDK)
- **Embeddings:** `sentence-transformers` (local)
- **Vector DB:** Qdrant (single Docker container)
- **Ingestion:** `markitdown` (PDF / DOCX / PPTX / XLSX / MD / HTML / TXT)
- **Frontend:** Vite + React + TypeScript + Tailwind (Phase 1.5)

## First-time setup

```bash
# Backend
cd backend
uv sync                     # creates .venv, installs deps from pyproject.toml
cp .env.example .env        # then fill in ANTHROPIC_API_KEY
```

Docker is required (used to run Qdrant).

## Daily run

```bash
./scripts/dev.sh
```

This single command:

1. Starts Qdrant (`docker compose up -d`)
2. Waits for Qdrant to become healthy
3. Creates DB tables (Alembic replaces this in a later phase)
4. Starts the backend (`uvicorn` on `:8130`) — and the frontend
   once it exists

Press **Ctrl+C** to stop the dev servers. Qdrant stays up.

```bash
./scripts/down.sh           # stop Qdrant, keep vectors
./scripts/down.sh --wipe    # stop + delete all vectors
```

## URLs

| What | Where |
|---|---|
| Backend | http://localhost:8130 |
| OpenAPI docs | http://localhost:8130/docs |
| Health | http://localhost:8130/health |
| Qdrant dashboard | http://localhost:6333/dashboard |

## Layout

```
PaperMind/
├── README.md
├── CLAUDE.md                — assistant context, stack rationale
├── scripts/
│   ├── dev.sh               — one-command dev launcher
│   └── down.sh              — stop Qdrant
├── infra/
│   └── docker-compose.yml   — Qdrant
├── backend/                 — Python FastAPI service
│   ├── pyproject.toml
│   ├── .env.example
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── db.py
│       ├── models.py        — Document, Chunk, Query
│       ├── routers/
│       ├── services/        — embeddings, qdrant, claude
│       └── loaders/         — markitdown wrapper
└── frontend/                — Vite + React + TS (Phase 1.5)
```
