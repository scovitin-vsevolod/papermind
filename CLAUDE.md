# PaperMind — Assistant Context

## What PaperMind is

Personal research companion built on top of the Claude API. Upload
your documents (PDF, DOCX, MD, TXT, HTML, …), ask questions grounded
in their content with citations, build a knowledge graph from them,
and side-by-side compare Claude vs GPT-4.

The project doubles as a portfolio piece for a Junior AI Developer
interview targeted 2–3 months out (currently May 2026).

## Stack

- **Backend:** Python 3.11+ · FastAPI · SQLAlchemy + SQLite · `uv`
- **LLM:** Claude (`anthropic` SDK), default `claude-sonnet-4-6` for the MVP — switchable via `CLAUDE_MODEL` env var; see [`docs/models.md`](docs/models.md). OpenAI added in Phase 2 for comparison.
- **Embeddings:** `sentence-transformers` locally for Phase 1. `voyage-3` added in Phase 2 for a side-by-side quality experiment.
- **Vector DB:** Qdrant (single Docker container)
- **Ingestion:** `markitdown` (one library for PDF / DOCX / PPTX / XLSX / MD / HTML / TXT)
- **Knowledge graph:** Neo4j (Phase 3)
- **Frontend:** Vite + React 19 + TypeScript + Tailwind 4 (Phase 1.5 / 2)
- **Infra:** `docker-compose` locally · AWS in production (Phase 4, service TBD)

## Stack rationale

- **`uv` over `poetry`.** Modern, fast, de-facto standard in 2026.
- **Claude primary, OpenAI later.** PaperMind exists to learn the
  Claude API; the GPT-4 comparison is a planned Phase 2 feature, not
  the default.
- **`sentence-transformers` first, `voyage-3` second.** Free, local,
  and forces real understanding of what embeddings are before
  outsourcing them to an API. The Phase 2 swap becomes a natural
  learning experiment (and a good interview talking point).
- **Qdrant, not Milvus.** Milvus standalone needs etcd + MinIO to
  even boot — three containers, three failure modes. Qdrant is one
  container, with an embedded mode if needed. Sibling project Sherpa
  runs Milvus and the operational cost is visible. For a personal
  project, Qdrant is the right trade-off.
- **`markitdown`, not per-format loaders.** Sherpa hand-rolls a loader
  per format (pdf / markdown / youtube). `markitdown` covers PDF,
  DOCX, PPTX, XLSX, HTML, MD, images (OCR) through one API. Less
  code, fewer bugs, easier to add formats later.
- **SQLite + SQLAlchemy for metadata.** Vector DB stores vectors and
  payload. Document state, ingestion status, query history live in
  SQLite. Trivial migration path to Postgres if it ever matters.
- **Vite + React, not Next.js.** Backend is a separate Python service
  — no SSR benefit, no app-router benefit. Next.js is overkill for a
  pure SPA talking to an API.
- **No LangChain / LlamaIndex in Phase 1.** Hand-roll the pipeline
  (parse → chunk → embed → upsert → search → generate). Goal is to
  *see* the moving parts. Frameworks come in if/when the pipeline
  grows beyond what's comfortable hand-rolled.

## Features

1. **RAG over uploaded documents** — chunking → embeddings → retrieval → answer with citations.
2. **Tool use** — web search, calculator, fetch URL.
3. **Knowledge graph** — Claude extracts entities and relations.
4. **Side-by-side comparison** — Claude vs GPT-4 on the same query.

## Roadmap

- [ ] **Phase 1 — MVP RAG (2–3 weeks):** scaffolding, document upload,
  ingestion via `markitdown`, chunking, `sentence-transformers`
  embeddings, Qdrant storage, Q&A endpoint with citations, minimal
  Vite+React UI.
- [ ] **Phase 2 — Tool use + model comparison (2–3 weeks):** Claude
  tool use (web search, calc, fetch URL), OpenAI integration,
  side-by-side UI, `voyage-3` embedding swap with retrieval-quality
  comparison.
- [ ] **Phase 3 — Knowledge graph (2–3 weeks):** Neo4j, entity
  extraction via Claude, graph visualization with `react-force-graph`.
- [ ] **Phase 4 — Tests, CI/CD, deploy (1–2 weeks):** pytest coverage,
  GitHub Actions, AWS deploy (service TBD).

Each phase ends with a commit and a working demo.

Step-level breakdown with progress checkboxes lives in
[`ROADMAP.md`](ROADMAP.md). Update it as the last action of every
step.

## Background

- **Have:** Python, FastAPI (some), React (some), OpenAI API.
- **Don't have:** Claude API, tool use, RAG in production, vector DB,
  knowledge graphs, Docker in production.

## Working principles

- This is a learning project — favor explanations of *why*, not just
  *how*.
- Minimum working version first, then iterate. No premature
  abstraction.
- All code, comments, file names, configs, and docs in **English**.
  Conversation with the user is in **Russian**.

## Reference

- Sibling project: `~/startups/Sherpa/` — Milvus-based RAG over course
  material. Similar shape, different LLM (OpenAI) and vector DB
  (Milvus). Useful for layout and ergonomics, not for stack choices.
