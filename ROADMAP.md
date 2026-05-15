# PaperMind — Roadmap

Step-level breakdown of every phase. Tick a box (`- [x]`) when a step
ships with a working demo. High-level rationale lives in
[`CLAUDE.md`](CLAUDE.md); this file is the operational checklist.

**Legend:** `[ ]` not started · `[~]` in progress · `[x]` done

---

## Phase 1 — MVP RAG (2–3 weeks)

Goal: upload a document, ask a question about it, get an answer with
citations — all via REST.

- [x] **1.1 Scaffolding.** Folder layout, `pyproject.toml` (uv),
  `docker-compose.yml` for Qdrant, `scripts/dev.sh`, FastAPI app with
  `/health`, SQLAlchemy + SQLite, `Document` / `Chunk` / `Query`
  models, `.env.example`, `CLAUDE.md`, `README.md`, `ROADMAP.md`.
  *Demo: `./scripts/dev.sh` boots Qdrant + backend, `/health` returns
  `{"status":"ok"}`.*
- [x] **1.2 Loaders — `markitdown` wrapper.** `loaders/markitdown_loader.py`:
  `to_markdown(bytes, filename) -> str`, with `LoaderError` for missing
  extension / empty parse. Tests generate DOCX (python-docx) and PDF
  (fpdf2) fixtures on the fly — no binary files in the repo.
  *Demo: `uv run pytest` → 6 passed in ~3s, covers TXT, MD, DOCX, PDF
  plus two error cases.*
- [x] **1.3 Chunker.** `services/chunker.py`: paragraph → sentence →
  hard-word fallback splitter with explicit overlap word-carry. Hand
  rolled, no LangChain. **Sizing was revised**: defaults are 200 words /
  30 overlap (≈ 250 / 40 tokens), not the original ~800/~100 — the
  binding constraint is the embedding window of
  `all-MiniLM-L6-v2` (256 tokens), not Claude's context. 13 unit tests
  cover size cap, overlap correctness, paragraph preference, fallbacks,
  empty input, and frozen-dataclass guard. *Demo: `uv run pytest` →
  19 passed in ~2.5s.*
- [x] **1.4 Embeddings service.** `services/embeddings.py`: lazy-load
  `all-MiniLM-L6-v2` via `lru_cache`-backed singleton; `embed()` returns
  unit-normalised float32 vectors (so cosine == dot product in Qdrant);
  `embedding_dim()` exposes the model's output dim for collection
  setup. 6 integration tests cover shape, normalisation, determinism,
  empty input, and a semantic sanity-check (paraphrase scores higher
  than an unrelated sentence). *Demo: `uv run pytest` → 25 passed
  (first run ~55s downloading the 80 MB model, subsequent ~10s).*
- [x] **1.5 Qdrant service.** `services/qdrant.py`: process-wide client
  singleton with `use_client_for_tests()` swap; `ensure_collection()`
  idempotent, COSINE distance, `dim` injectable for tests;
  `upsert_chunks` / `search(filter=document_id)` /
  `delete_by_document`. Point identity simplified — **`Chunk.id` IS the
  Qdrant point_id**, no UUID sync (dropped `qdrant_point_id` field from
  the model). 6 tests run against in-process `QdrantClient(':memory:')`
  — no Docker container needed. *Demo: `uv run pytest` → 31 passed in
  ~9s; self-query of an inserted chunk scores >0.99, document filter
  scopes results correctly, delete-by-document removes only its own
  points.*
- [x] **1.6 Documents API.** `routers/documents.py`: `POST /documents`
  runs the full ingest pipeline synchronously (parse → chunk → embed →
  upsert + Chunk rows, status transitions PARSING → EMBEDDING → READY,
  ERROR on `LoaderError`). `GET /documents`, `GET /documents/{id}`,
  `DELETE /documents/{id}` (cascades through both stores). Added
  `app/schemas.py` (`DocumentRead`) and `tests/conftest.py` with a
  `StaticPool` in-memory SQLite + in-memory Qdrant fixture so the full
  TestClient flow needs zero external services. 10 new tests cover
  upload, list ordering, get, delete (both stores), 404s, unsupported
  extension, empty file, and a real semantic search on the persisted
  chunks. *Demo: `uv run pytest` → 41 passed in ~4s.*
- [x] **1.7 Claude service + `/ask`.** `services/claude.py`: process-wide
  Anthropic client singleton with `use_client_for_tests()` swap;
  fixed ~150-token system prompt; user message tags excerpts with
  `[chunk:<id>]`; no `temperature`/`top_p`/`thinking` (so it works on
  both Opus 4.7 and Sonnet 4.6); citation parser dedupes + preserves
  order. `routers/ask.py`: `POST /ask` — embed → Qdrant search (with
  optional `document_id` filter) → Claude → return only the chunks
  the model **actually cited** (hallucinated IDs are dropped); logs
  the query into the `Query` table. `FakeClaude` test double in
  `conftest.py` so no test can hit the real API. 9 tests cover prompt
  shape, citation parsing, dedup, hallucination filtering, document
  filter, 404, validation, empty-corpus path. *Demo: `uv run pytest`
  → 50 passed in ~5s; `POST /ask` in `/docs` returns grounded answer
  with citations.*
- [x] **1.8 Tests.** Already covered as we went — 50 tests across
  chunker (13), embeddings (6, real model, cached), Qdrant (6, in-memory),
  loaders (6), documents API (10), `/ask` (9 with `FakeClaude`). No
  network needed; the 2-second target is missed (~4-5s) because we use
  real `sentence-transformers` + real Qdrant-`:memory:` rather than
  mocks — a deliberate trade: contract drift in `qdrant-client` or
  `anthropic` surfaces here, not in prod. Added ruff with FastAPI-aware
  `flake8-bugbear` config (`Depends`/`File` whitelisted). *Demo:
  `uv run pytest` → 50 passed in ~4s · `uv run ruff check` → clean.*
- [x] **1.9 Frontend MVP.** Vite 6 + React 19 + TypeScript 5.7 +
  Tailwind 4 (CSS-based config, `@tailwindcss/vite` plugin — no
  `tailwind.config.js`). `src/api.ts` owns the wire types + thin
  `fetch` wrappers; `src/App.tsx` is a single-file three-section UI
  (header with live model badges from `/health`, documents
  upload/list/delete, ask form with scope picker + answer +
  citations). No state libs — plain `useState` + `useEffect`. CORS in
  backend extended to 5173-5175 so Vite's auto-port-jump works when
  sibling projects are running. *Demo: `npm install && npm run build`
  → 200 KB JS bundle, no TS errors; `npm run dev` serves the UI; when
  backend is up, full upload → ask → cited-chunks flow works in the
  browser.*
- [x] **1.10 Phase-1 commit + retro.** Retro written in
  [`docs/retro.md`](../docs/retro.md) — surprises (`:memory:` testing,
  embedding window as binding constraint, prompt-caching minimum,
  `StaticPool` for in-memory SQLite, citations-only-if-cited),
  interview talking points (no LangChain in Phase 1, Qdrant vs Milvus
  trade, test strategy), and explicit out-of-scope list for Phase 2-4.
  Commit + tag `v0.1.0-mvp` is the user's call — they haven't yet
  initialised git on this project. *Demo: see
  [`docs/retro.md`](../docs/retro.md).*

---

## Phase 2 — Tool use + model comparison (2–3 weeks)

Goal: Claude can use tools to answer questions that go beyond the
uploaded docs, and the UI lets you compare Claude vs GPT-4 on the
same query.

- [ ] **2.1 Tool use — web search.** Claude `tool_use` API,
  `web_search` tool (start with a free provider like DuckDuckGo).
  *Demo: ask a question requiring fresh info — Claude calls the tool,
  uses results in the answer.*
- [ ] **2.2 Tool use — calculator.** Trivial tool that evaluates a
  math expression. *Demo: "what's 12% of 3475?" → tool call → exact
  number in answer.*
- [ ] **2.3 Tool use — fetch URL.** Tool that downloads a page and
  returns its text. *Demo: "summarize https://…" works without prior
  ingestion.*
- [ ] **2.4 OpenAI service.** Parallel `services/openai.py` mirroring
  the Claude service interface. *Demo: same `/ask` works with
  `?model=gpt-4`.*
- [ ] **2.5 Side-by-side UI.** New UI mode: one question → two
  columns, Claude and GPT-4 answers rendered in parallel, with
  latency and token counts. *Demo: ask the same question, see both
  side by side.*
- [ ] **2.6 voyage-3 embeddings.** Optional embedding backend.
  Config switch `EMBEDDING_PROVIDER=voyage|sentence-transformers`.
  *Demo: re-index a doc with voyage-3, both indexes coexist.*
- [ ] **2.7 Retrieval quality experiment.** Script: 10 questions × 2
  embedding backends → compare recall@5 manually. Write up the
  result in `docs/retrieval-experiment.md`. *Demo: a markdown report
  with conclusions. Interview talking point #2.*

---

## Phase 3 — Knowledge graph (2–3 weeks)

Goal: extract entities and relations from uploaded docs into Neo4j,
visualize them as a force-directed graph.

- [ ] **3.1 Neo4j compose service.** Add Neo4j to `docker-compose.yml`,
  add `NEO4J_URL` / auth env vars, wire health-check into `dev.sh`.
  *Demo: Neo4j Browser at :7474 shows an empty graph.*
- [ ] **3.2 Entity extraction prompt.** Claude with structured output
  (JSON tool) — given a chunk, return entities + relations. Iterate
  on the prompt until results are usable. *Demo: feed a sample
  chunk, get clean JSON.*
- [ ] **3.3 Graph builder service.** `services/graph.py`: take
  extracted entities + relations, MERGE into Neo4j (de-duplicate by
  canonical name). Run during ingestion. *Demo: upload a doc, see
  nodes/edges appear in Neo4j Browser.*
- [ ] **3.4 Graph API.** `GET /graph?document_id=…` returns nodes +
  edges as JSON for the frontend. *Demo: hit the endpoint, get a
  graph JSON.*
- [ ] **3.5 Graph UI.** New tab in the frontend using
  `react-force-graph`. Hover a node → see source chunks. *Demo:
  click-around graph rendering of an uploaded doc.*

---

## Phase 4 — Tests, CI/CD, deploy (1–2 weeks)

Goal: production-shaped repo. CI runs on every push; one-command
deploy to Fly.io.

- [ ] **4.1 Coverage pass.** Raise pytest coverage to ≥70% for
  `app/services/` and `app/routers/`. *Demo: `uv run pytest --cov`
  shows the number.*
- [ ] **4.2 GitHub Actions — lint + test.** `.github/workflows/ci.yml`:
  `uv sync`, `ruff check`, `pytest`. Trigger on push + PR. *Demo:
  green badge on the README.*
- [ ] **4.3 Backend Dockerfile.** Multi-stage build, slim runtime
  image. *Demo: `docker build` produces an image, `docker run` boots
  uvicorn.*
- [ ] **4.4 Frontend Dockerfile.** Vite static build served by
  caddy/nginx. *Demo: same.*
- [ ] **4.5 `fly.toml` + deploy.** `fly launch`, env secrets via `fly
  secrets`, deploy. *Demo: public URL serves the app.*
- [ ] **4.6 Phase-4 commit + portfolio polish.** Tag `v1.0.0`,
  finalize README with screenshots and the Fly.io URL.

---

## Conventions

- A step is "done" when there's a **working demo** described next to it
  — not just code merged. If the demo doesn't run, the box stays
  unchecked.
- Update this file as the last action of each step, in the same commit
  as the code.
- Surprises and lessons land in `docs/retro.md` (created when first
  needed), not here.
