# PaperMind

[![CI](https://github.com/REPLACE-ME-with-your-username/PaperMind/actions/workflows/ci.yml/badge.svg)](https://github.com/REPLACE-ME-with-your-username/PaperMind/actions/workflows/ci.yml)

Personal research companion built on the Claude API. Upload documents
(PDF, DOCX, MD, TXT, HTML, …), ask questions grounded in their content
with citations, compare Claude vs GPT-4 side-by-side, and visualise the
entities extracted from your corpus as a force-directed knowledge graph.

Designed as a learning project + portfolio piece for a Junior AI
Developer interview.

## Features

- **RAG over arbitrary documents.** Upload → `markitdown` parse →
  paragraph-aware chunker → `sentence-transformers` (or `voyage-3`)
  embeddings → Qdrant → Claude answers grounded in cited chunks.
- **Tool use.** Claude can call web_search and web_fetch (Anthropic
  server-side) plus a safe client-side calculator (AST-evaluated,
  whitelisted operators).
- **Multi-provider comparison.** One question, two columns, two
  providers (Claude + GPT-4) rendered as each response lands.
- **Knowledge graph.** Per-chunk entity/relation extraction via Claude's
  JSON-schema mode, deduplicated into Neo4j, rendered with
  `react-force-graph-2d` in the browser.
- **GraphRAG.** When the request opts in (`use_graph=true`), the
  knowledge graph augments vector retrieval: extract question
  entities, walk 1-hop neighbours, pull additional chunks from
  related documents. Each citation is tagged with its source
  (`vector` or `graph`) for full provenance.
- **Side-quest harnesses.** `backend/scripts/retrieval_experiment.py`
  runs a recall@5 A/B between local MiniLM and voyage-3.
  `backend/scripts/graph_experiment.py` measures the lift from
  graph augmentation on top of a fixed embedding.

- [`CLAUDE.md`](CLAUDE.md) — stack rationale and assistant context
- [`ROADMAP.md`](ROADMAP.md) — step-by-step plan with progress checkboxes
- [`docs/models.md`](docs/models.md) — current model defaults and how to switch
- [`docs/retro.md`](docs/retro.md) — phase-by-phase retros: surprises, lessons, interview talking points
- [`docs/retrieval-experiment.md`](docs/retrieval-experiment.md) — MiniLM vs voyage-3 recall@5 harness
- [`docs/graph-experiment.md`](docs/graph-experiment.md) — vector vs vector+graph recall@5 harness (GraphRAG lift)
- [`docs/deploy.md`](docs/deploy.md) — Fly.io deployment recipe

## Stack

- **Backend:** Python 3.11 · FastAPI · SQLAlchemy + SQLite · `uv`
- **LLMs:** Claude (`anthropic`) + GPT-4 (`openai`) — switchable per request
- **Embeddings:** `sentence-transformers` (local) or `voyage-3` (API)
- **Vector DB:** Qdrant
- **Knowledge graph:** Neo4j 5
- **Ingestion:** `markitdown` (PDF / DOCX / PPTX / XLSX / MD / HTML / TXT)
- **Frontend:** Vite 6 · React 19 · TypeScript 5.7 · Tailwind 4 · `react-force-graph-2d`
- **CI:** GitHub Actions (ruff, pytest with `--cov-fail-under=70`, tsc, vite build)
- **Deploy:** Docker images + Fly.io (see [docs/deploy.md](docs/deploy.md))

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
4. Starts the backend (`uvicorn` on `:8109`) — and the frontend
   once it exists

Press **Ctrl+C** to stop the dev servers. Qdrant stays up.

```bash
./scripts/down.sh           # stop Qdrant, keep vectors
./scripts/down.sh --wipe    # stop + delete all vectors
```

## URLs

| What | Where |
|---|---|
| Backend | http://localhost:8109 |
| OpenAPI docs | http://localhost:8109/docs |
| Health | http://localhost:8109/health |
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
