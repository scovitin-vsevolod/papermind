> Last updated: 2026-05-26

# PaperMind — stack overview

Monorepo with two code subprojects and one infra subproject. Each has
its own `STACK.md` with full details; this file is the aggregator.

## Subprojects

| Path | Role | Language / Framework | Details |
|---|---|---|---|
| [`backend/`](backend/STACK.md)   | REST API, ingestion, RAG pipeline, auth | Python 3.11 + FastAPI | [backend/STACK.md](backend/STACK.md) |
| [`frontend/`](frontend/STACK.md) | SPA UI                                  | TypeScript 5.7 + React 19 + Vite 6 | [frontend/STACK.md](frontend/STACK.md) |
| [`infra/`](infra/STACK.md)       | Local-dev docker-compose (Qdrant, Neo4j)| Docker Compose | [infra/STACK.md](infra/STACK.md) |

## At a glance

- **Backend** — FastAPI on `uv`; Claude (`anthropic`) primary LLM, OpenAI
  for Phase 2 comparison; `sentence-transformers` (local) + `voyageai`
  for embeddings; `markitdown` for ingestion; SQLAlchemy + SQLite for
  metadata; `qdrant-client` for vectors; `neo4j` driver for the graph.
- **Frontend** — Vite + React 19 + Tailwind 4 (CSS-based config, no
  PostCSS); `react-markdown` + `remark-gfm` for answers, `react-force-graph-2d`
  for Phase 3 graph view. Single SPA, talks to backend over `/api`.
- **Infra** — one `docker-compose.yml` brings up Qdrant (`v1.12.4`) and
  Neo4j (`5.24-community`) for local dev. Production deploy is Phase 4
  (AWS, service TBD); compose is not used in prod.

## Why this split

- Backend and frontend are deployed independently (separate Dockerfiles,
  different runtimes) — keeping their dependency lists separate avoids
  one side's bumps from rebuilding the other.
- `infra/` is config-only (no source code) but it owns the dev-environment
  contract: ports, volumes, container names. Keeping it as its own
  subproject means `./manage.sh` and `scripts/dev.sh` have one obvious
  place to read compose from.

## How to run

See [`infra/STACK.md`](infra/STACK.md) for the compose-level commands,
and `./manage.sh` at the repo root for the dev workflow (`start`, `stop`,
`down`, `restart`, `status`, `logs`, `reset-db`).
