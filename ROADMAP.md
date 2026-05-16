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

- [x] **2.1 Tool use — web search.** Anthropic's server-side
  `web_search_20260209` enabled when `AskRequest.use_tools=True`. Single
  API call from our side; Anthropic runs the search. `server_tool_use`
  blocks are recorded in the response as `tool_uses[]` for transparency.
- [x] **2.2 Tool use — calculator.** Custom client-side tool with a
  safe AST evaluator (whitelisted ops, rejects names/calls/imports).
  Exercises the multi-turn loop: Claude emits `tool_use` → we execute
  → feed `tool_result` back, capped at 5 iterations. 7 unit tests on
  the evaluator + 1 end-to-end loop test.
- [x] **2.3 Tool use — fetch URL.** Anthropic's server-side
  `web_fetch_20260209`, same shape as web_search. Enabled together
  with the other tools by the same `use_tools` flag.
- [x] **2.4 OpenAI service.** `services/openai_provider.py` mirrors the
  Claude service surface: same `ChunkContext` / `AskResult`, same RAG
  prompt (`SYSTEM_PROMPT` imported from claude.py — comparison shows
  *model* difference, not *prompt* difference), citation parser
  duplicated next to the provider so the two integrations stay
  independently swappable. `/ask` accepts `provider: "claude" | "openai"`
  (default `claude`); pydantic Literal rejects anything else with 422.
  `FakeOpenAI` test double in conftest. 5 new tests verify routing,
  isolation, citations, and validation.
- [x] **2.5 Side-by-side UI.** `App.tsx`: "Compare Claude vs GPT-4"
  checkbox fires both requests in parallel (`Promise.all`); each pane
  fills in independently as its response arrives (no waiting on the
  slow one). New `ResultPane` component handles idle / loading /
  error / ok states. Tool-call rows surface above citations when
  `use_tools` is enabled. *Demo: tick "Compare", ask a question — two
  columns rendered as soon as each provider responds.*
- [x] **2.6 voyage-3 embeddings.** Two backends behind one `embeddings`
  module API: `sentence-transformers/all-MiniLM-L6-v2` (384 dim, local,
  free) and `voyageai`'s `voyage-3` (1024 dim, API, paid). Switched via
  `EMBEDDING_PROVIDER` env var. Different dims → different collections:
  `qdrant.collection_name_for_backend()` builds `papermind_minilm` and
  `papermind_voyage` so both can coexist. All Qdrant service functions
  take an optional `backend=` override for the experiment path. Voyage
  embeddings use `input_type="document"` on upsert and `"query"` on
  search (model is asymmetric). Tests stay on the local backend.
- [x] **2.7 Retrieval quality experiment.**
  `backend/scripts/retrieval_experiment.py` runs the same 10-doc corpus
  and 10 hand-labelled queries through both backends and writes
  `docs/retrieval-experiment.md` (recall@5 per query + mean). Idempotent:
  drops + recreates the two experiment collections on each run. Needs
  `VOYAGE_API_KEY` + a running Qdrant; fails fast with a clear message
  if either is missing. *Demo: `uv run python scripts/retrieval_experiment.py`
  → updated `docs/retrieval-experiment.md`. Interview talking point #2.*

---

## Phase 3 — Knowledge graph (2–3 weeks)

Goal: extract entities and relations from uploaded docs into Neo4j,
visualize them as a force-directed graph.

- [x] **3.1 Neo4j compose service.** `neo4j:5.24-community` added to
  `infra/docker-compose.yml` with named volumes and tuned heap/page
  cache. `scripts/dev.sh` waits up to 60s for the HTTP browser (cold
  start is slow) but doesn't bail — non-graph endpoints stay usable if
  Neo4j is down. `manage.sh status` probes both 7474 (HTTP) and 7687
  (Bolt). `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` in settings.
- [x] **3.2 Entity extraction prompt.** `services/extraction.py`: Claude
  with `output_config.format` JSON-schema mode — entity-type enum
  constrained to 8 categories, schema enforces both arrays and
  required fields. Defends in depth: drops entities with unknown
  types, drops relations whose endpoints aren't in the entity list,
  returns empty result on JSON-decode failure (don't crash ingestion).
- [x] **3.3 Graph builder service.** `services/graph.py`: `MERGE`
  Cypher with uniqueness constraint on `Entity.name` (set on first
  `ensure_schema()`). Both entities and edges accumulate
  `document_ids` so re-ingesting the same doc doesn't duplicate, and
  `delete_for_document` removes the doc's contribution — dropping
  entities/edges that become orphans. Hooked into the upload pipeline
  as best-effort: per-chunk failures are logged and skipped, and a
  Neo4j outage doesn't fail the whole upload. 8 graph + 6 extraction
  tests use `FakeNeo4jDriver` (small in-memory Cypher interpreter).
- [x] **3.4 Graph API.** `GET /graph` returns nodes + edges as JSON;
  optional `?document_id=N` query filters to a subgraph. Returns 503
  with the underlying exception class + message when Neo4j is
  unreachable so the frontend can fall back gracefully. 4 router tests
  cover full graph, document filter, empty state, and the 503 path.
- [x] **3.5 Graph UI.** `react-force-graph-2d` in `frontend/src/GraphView.tsx`
  as a third section under Documents and Ask. Per-type colour legend
  (8 entity types, same enum as the backend), scope selector
  (all-docs / per-doc), hover tooltip with type and document
  membership. `ResizeObserver` adjusts canvas width to the container.
  Empty state explains how to populate the graph (upload a doc with
  named entities).

---

## Phase 4 — Tests, CI/CD, deploy (1–2 weeks)

Goal: production-shaped repo. CI runs on every push; one-command
deploy to Fly.io.

- [x] **4.1 Coverage pass.** Added `pytest-cov`, `[tool.coverage]` config
  in `pyproject.toml`. Baseline came in at 94% — well above the 70%
  target. Filled two of the remaining holes worth real tests: the
  5-iteration safety cap in the tool-use loop (`_MAX_TOOL_ITERATIONS`)
  and the best-effort error paths in upload (broken Neo4j, exploding
  extraction). 98 tests; `app/services/` and `app/routers/` are all
  ≥88%. *Demo: `uv run pytest --cov=app --cov-report=term-missing`.*
- [x] **4.2 GitHub Actions — lint + test.** `.github/workflows/ci.yml`
  runs two parallel jobs:
  - **backend** — `uv sync` (cached), `ruff check`, `pytest` with
    `--cov-fail-under=70`. Hard-gates merges if coverage regresses.
  - **frontend** — `npm ci` (cached) + `npm run build` (which does
    `tsc -b && vite build`, so green CI implies green type check).
  Triggers on push to `main` and on PRs targeting `main`.
- [x] **4.3 Backend Dockerfile.** Multi-stage: `python:3.11-slim`
  builder runs `uv sync --no-dev` into a venv, runtime stage copies
  just the venv + `app/`, drops to a non-root user, runs uvicorn with
  2 workers. `.dockerignore` keeps venvs, caches, `.env`, and the
  local SQLite out of the build context. Image weighs ~5.4 GB —
  torch + sentence-transformers dominate; switching the production
  embedding provider to `voyage` (Phase 2.6) would strip ~3.5 GB.
- [x] **4.4 Frontend Dockerfile.** Multi-stage: `node:22-alpine` runs
  `npm ci && npm run build` (which is `tsc -b && vite build`, so type
  errors fail the docker build), `nginx:1.27-alpine` runtime serves
  the static `dist/`. Custom `nginx.conf` does SPA history-API
  fallback, gzip for text assets, immutable cache on hashed `/assets/`,
  and proxies `/api/*` to `http://backend:8109` (matching the dev
  proxy so the frontend code is identical in dev and prod). Image
  weighs ~50 MB. *Demo: `docker build -t papermind-frontend frontend/`
  and `docker build -t papermind-backend backend/` both green.*
- [x] **4.5 `fly.toml` + deploy.** `backend/fly.toml` and
  `frontend/fly.toml`, both with auto-stop machines (idle → $0),
  Fly internal DNS (`*.internal`) wiring, and a 1 GB mounted volume
  for the backend's SQLite. `docs/deploy.md` walks the full setup —
  four Fly apps (backend, frontend, Qdrant, Neo4j), explicit `fly
  secrets set` for every credential, smoke-test curl. Production
  switches the embedding provider to `voyage` to skip the 3.5 GB
  torch stack. *Demo (manual, requires a Fly account): follow the
  recipe → `curl https://<app>.fly.dev/health` returns the model
  badges.*
- [x] **4.6 Phase-4 commit + portfolio polish.** README gets a CI
  badge stub, a feature list, an updated stack table, and links to
  every doc in `docs/`. `docs/retro.md` now leads with a Phase 4
  section (5.4 GB image trade-off, why coverage was already 94%, the
  Fly free-tier-is-gone reality, interview talking points). Tagging
  `v1.0.0` is the user's call once Phase 4 is committed —
  `git tag v1.0.0` after `/my-commit-message`.

---

---

## Phase 5 — GraphRAG (added after Phase 4)

Phase 3 built the graph; Phase 5 makes it pull its weight. The
knowledge graph stops being a visualisation and starts contributing
chunks to the `/ask` retrieval set.

- [x] **5.1 Graph-augmented retrieval.** `services/graph_rag.py:augment()`
  runs after vector search when `AskRequest.use_graph=True`: extract
  entities from the question (same Claude JSON-mode pipeline used at
  ingest), find 1-hop neighbours via `graph.find_neighbours()`, pull
  the best chunk per candidate document from Qdrant. Caps:
  `_MAX_RELATED_DOCS=8`, `_MAX_EXTRA_HITS=3`. Failures in extraction
  or Neo4j degrade silently to vector-only — `/ask` never fails on
  graph problems. `CitationOut.source` tags each citation `"vector"`
  or `"graph"` so the UI can show provenance. 7 new tests, including
  Neo4j-outage and extraction-failure paths.
- [x] **5.2 Frontend "GraphRAG" toggle + provenance badge.** Third
  checkbox in the Ask section; graph-derived citations get an
  amber `via graph` badge so the user can see which chunks vector
  alone would have missed.
- [x] **5.3 Measurement harness.** `backend/scripts/graph_experiment.py`:
  same 10-doc corpus + 10 queries, two runs (vector only vs vector+
  graph), recall@5 per query and mean. Seeds the graph directly into
  Neo4j to isolate retrieval from extraction quality — answers
  "would a perfect graph help?" rather than the noisier "does our
  extraction pipeline help?". Output → `docs/graph-experiment.md`.

---

## Phase 6 — Closed system: auth (added after Phase 5)

PaperMind is a single-tenant personal app. The deliberate non-feature
here is the absence of a public `/auth/register` endpoint — users come
into existence ONLY through a server-side CLI tool. That's the entire
access-control story: if you control the box, you control who logs in.

- [x] **6.1 Backend auth primitives.** `services/auth.py` — bcrypt
  (cost 12) for password storage, JWT HS256 for session tokens.
  `app/models.py` adds a `User` row (email unique-indexed, password
  hash, `is_active`, `created_at`). `app/schemas.py` adds
  `LoginRequest` / `UserOut` / `LoginResponse`. Config picks up
  `JWT_SECRET` and `JWT_SESSION_DAYS` from env with safe dev defaults.
- [x] **6.2 Login / logout / whoami.** `routers/auth.py`:
  `POST /auth/login` returns the user and sets a `papermind_session`
  httpOnly cookie (Secure, SameSite=lax, JWT inside). Verifies the
  password unconditionally — even when the user doesn't exist — so the
  timing of "no such user" vs "wrong password" matches (small win
  against email enumeration). `POST /auth/logout` clears the cookie.
  `GET /auth/me` returns the current user so the frontend can decide
  login vs main UI on page load.
- [x] **6.3 Protect-by-default.** `app/auth_deps.py:get_current_user`
  reads the cookie OR `Authorization: Bearer …` (so curl/scripts
  still work), decodes the JWT, loads the row. Routers `documents`,
  `ask`, `graph` now declare `dependencies=[Depends(get_current_user)]`
  at the router level — opt-in to public is the new default, the
  opposite of opt-in to auth.
- [x] **6.4 CLI: create_user.** `backend/app/cli/create_user.py` —
  interactive prompts for email (Pydantic `EmailStr`) and password
  (`getpass`, 8+ chars, confirmed). Also accepts a `--non-interactive`
  flag taking `PAPERMIND_EMAIL` / `PAPERMIND_PASSWORD` env vars so it
  can be driven from CI / Ansible. Refuses to overwrite an existing
  email. Calls `Base.metadata.create_all(engine)` defensively so a
  fresh DB Just Works.
  Run on the server with: `uv run python -m app.cli.create_user`.
- [x] **6.5 Frontend gate.** `App.tsx` probes `GET /auth/me` on mount.
  401 → `LoginScreen`, 200 → main UI with the user's email + a
  "Sign out" button in the header. Any subsequent API call that
  returns 401 (token expired, user deleted, secret rotated) drops the
  user back to the login screen. `api.ts` ships an `ApiError` class so
  callers can branch on `.status === 401` without parsing strings.
- [x] **6.6 Tests.** 23 new tests in `tests/test_auth.py` covering the
  login success path, wrong-password / missing-user / inactive paths,
  payload validation, logout cookie clearing, `/auth/me` via cookie
  AND bearer header, expired / tampered / deleted-user tokens, and a
  401 sweep across `/documents` `/ask` `/graph`. The existing 105
  tests keep passing because `conftest.py` adds a
  `dependency_overrides[get_current_user]` for the standard `client`
  fixture and a separate `unauthenticated_client` for tests that need
  to exercise the real auth flow.

Trade-offs picked here:

- **JWT in httpOnly cookie, not localStorage.** JS can't read it, so
  XSS can't lift the token. Cookies auto-replay on same-origin fetch,
  so the React code doesn't have to thread tokens through every call.
- **Stateless sessions, no server-side store.** Logout doesn't
  invalidate the token on the server — it just clears the cookie. A
  stolen token stays valid until its `exp`. Acceptable for a
  single-tenant app; the escape hatch is rotating `JWT_SECRET`, which
  kills every active session immediately.
- **No `/register` endpoint at all.** Not even with an admin gate.
  CLI-only is simpler, has no surface to attack, and matches the
  threat model (one user, ever).

## Conventions

- A step is "done" when there's a **working demo** described next to it
  — not just code merged. If the demo doesn't run, the box stays
  unchecked.
- Update this file as the last action of each step, in the same commit
  as the code.
- Surprises and lessons land in `docs/retro.md` (created when first
  needed), not here.
