> Last updated: 2026-05-26

# Backend

## Language & Framework

- **Python:** 3.11+ (`.python-version` pins `3.11`)
- **Framework:** FastAPI 0.115+
- **Server:** Uvicorn 0.32+ (`uvicorn[standard]`)
- **Package manager:** `uv` (with `hatchling` as the build backend)

## Key dependencies

| Package | Purpose |
|---|---|
| `fastapi` ≥ 0.115 | HTTP framework |
| `uvicorn[standard]` ≥ 0.32 | ASGI server |
| `anthropic` ≥ 0.40 | Claude API SDK (primary LLM) |
| `openai` ≥ 1.55 | OpenAI SDK (Phase 2 side-by-side comparison) |
| `qdrant-client` ≥ 1.12 | Vector DB client (supports `:memory:` for tests) |
| `neo4j` ≥ 5.20 | Knowledge graph driver (Phase 3) |
| `sentence-transformers` ≥ 3.3 | Local embeddings (`all-MiniLM-L6-v2`, 384-dim) |
| `voyageai` ≥ 0.3 | Voyage embeddings (`voyage-3`, 1024-dim) for Phase 2 swap |
| `markitdown[pdf,docx,pptx,xlsx]` ≥ 0.0.1a3 | One library for all input formats |
| `sqlalchemy` ≥ 2.0 | ORM for document / chunk / query metadata |
| `alembic` ≥ 1.14 | DB migrations (placeholder; not yet wired) |
| `pydantic-settings` ≥ 2.6 | Config loaded from `.env` |
| `python-multipart` ≥ 0.0.12 | Multipart parser for file upload |
| `bcrypt` ≥ 4.2, `pyjwt` ≥ 2.10, `email-validator` ≥ 2.2 | Auth (password hashing, session JWT, email validation) |

## Database

- **Metadata:** SQLite (`papermind.db`) via SQLAlchemy — trivial migration path to Postgres later.
- **Vectors:** Qdrant in Docker — see [`../infra/STACK.md`](../infra/STACK.md).
- **Knowledge graph:** Neo4j in Docker (local) or Neo4j Aura (prod) — see [`../infra/STACK.md`](../infra/STACK.md).

## Tooling

- `ruff` ≥ 0.8 — lint + format (line-length 100, py311 target, FastAPI-aware `flake8-bugbear`)
- `pytest` ≥ 8 + `pytest-cov` ≥ 5 + `httpx` ≥ 0.28 — test suite (no network)
- Test doubles: in-process Qdrant `:memory:`, `StaticPool` in-memory SQLite, `FakeClaude` for Anthropic
- Test-only deps: `python-docx` ≥ 1.1, `fpdf2` ≥ 2.8 (generate DOCX/PDF fixtures on the fly)
- Coverage target: ≥70% across `app/services` and `app/routers` (Phase 4)
