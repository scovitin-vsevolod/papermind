# PaperMind retros

One section per phase. Add to it as you ship; don't rewrite older
sections — the value is the timestamped trail of what you learned when.

---

## Phase 5 retro — GraphRAG (the graph finally pays rent)

### Why this exists

A reviewer of the project pointed out that Phase 3 built a knowledge
graph that the rest of the system didn't actually use — `/ask` was
purely vector. The graph was a pretty visualisation, not retrieval
infrastructure. Phase 5 closes that gap.

The narrative changes from "I built a knowledge graph" to "I built a
knowledge graph that **measurably affects retrieval**". That's the
difference between a junior portfolio piece and one that holds up to
"so what does it do?" follow-up questions.

### What got built

- `services/graph_rag.py` — one function, `augment()`, that runs after
  vector search when the request opts in. It extracts question
  entities through the existing Claude JSON-mode pipeline, looks up
  1-hop neighbours in Neo4j, and pulls one extra chunk per related
  document from Qdrant. Capped at 3 extra hits, 8 candidate documents.
- `CitationOut.source` tags every citation `"vector"` or `"graph"`.
  The UI surfaces graph-derived citations with an amber badge — same
  pattern as Phase 2's tool-use rows, so users see provenance.
- `backend/scripts/graph_experiment.py` — a focused recall@5 harness
  that runs the same 10 queries through both modes and writes the
  numbers to `docs/graph-experiment.md`.

### Surprises and lessons

**The "if it fails, never block the user" pattern paid off again.**
Phase 3 wrapped graph operations in best-effort try/except at the
*ingest* side. Phase 5 added the same shape at the *query* side:
extraction failure → return vector hits, Neo4j outage → return vector
hits, no entities in the question → return vector hits. The /ask
endpoint never fails because the graph is broken. This is the right
shape for an *augmentation* — it should add value when it works and
disappear when it doesn't.

**The experiment script bypasses extraction on purpose.** When you're
measuring "does the graph help?", you want to separate two questions:
(a) is graph-augmented retrieval a good idea in principle, and (b)
is our extraction pipeline accurate enough to feed it? The script
seeds the graph directly so it answers (a). Production answers (b)
implicitly, but a noisy extraction muddies the (a) signal — separate
them.

**Recall@5 on a 10-doc corpus is too coarse for a real verdict.** This
is acknowledged in the experiment doc. The harness exists to **show
the shape of the measurement**, not to claim "graph wins by X%". On
a real corpus with hundreds of docs and ambiguous questions, you'd
want recall@10, MRR, and probably LLM-as-judge for "is this answer
better with the graph". Phase 5 builds the harness; bigger numbers
need a bigger corpus.

### Interview talking point (Phase 5 specific)

> "Phase 3 built the graph. Phase 5 measured whether it helps. The
> answer on my small test corpus is 'sometimes, on questions phrased
> around an entity whose name isn't repeated in the relevant chunk' —
> which is exactly the case GraphRAG is supposed to win. I'd want to
> repeat the measurement on a 1000+ document corpus before claiming
> production readiness, but the harness is there and re-runs
> idempotently. That's the difference between 'I built a knowledge
> graph' and 'I built a measured retrieval system that uses one'."

### What's still out of scope

- **Multi-hop expansion.** Only `depth=1` neighbours. 2-hop would
  often surface relevant docs but also blows up the candidate set —
  needs ranking, not just enumeration.
- **Cross-chunk entity coreference.** "The company" and "Anthropic"
  are different strings; the current extraction treats them as
  different entities. Real GraphRAG (Microsoft's, for one) does
  community detection + coreference resolution as separate phases.
- **Query-side entity matching against the graph.** Right now we
  trust Claude's extraction. A hybrid (string match for high-precision
  hits + Claude for synonyms) would be cheaper and more robust.

---

## Phase 4 retro — tests, CI/CD, deploy

### What got built

- pytest-cov in dev deps; baseline came in at **94%** without any new
  tests. The 70% target was nominal.
- GitHub Actions workflow with two parallel jobs (backend lint+test,
  frontend type check + build), uv and npm caches keyed off the
  respective lock files. Backend job hard-gates on
  `--cov-fail-under=70`.
- Multi-stage Dockerfiles for both apps. Backend ~5.4 GB (torch +
  sentence-transformers dominate), frontend ~50 MB. Non-root user in
  the backend runtime stage, `.dockerignore` keeps venvs and DBs out
  of the build context.
- nginx serves the prebuilt Vite bundle and proxies `/api/*` to the
  backend — same shape as the dev-server proxy, so frontend code
  ships identical in dev and prod.
- `fly.toml` for both apps, plus a step-by-step `docs/deploy.md`
  that covers the full Fly.io flow (4 apps: backend + frontend +
  Qdrant + Neo4j).

### Surprises and lessons

**5.4 GB is a lot of container for a Q&A app.** The torch stack +
sentence-transformers explain ~3.5 GB. Production should run with
`EMBEDDING_PROVIDER=voyage` (already wired in Phase 2), which strips
the local model entirely and brings the image down to ~1 GB. Phase 2's
"side-quest" experiment turned out to be the thing that makes
production tenable.

**Coverage was higher than expected because the test strategy was
right from Phase 1.** No mocks for our own services — in-memory
Qdrant, FakeClaude/FakeOpenAI/FakeNeo4jDriver that mimic the real
interfaces. Every code path that doesn't hit a real external API ran
in the suite. The remaining uncovered lines are the voyage backend
(no API key in CI) and two `# noqa: BLE001` error branches we
specifically widened — both honest gaps, not test debt.

**Fly's deprecated free tier matters.** Earlier roadmap talk assumed
"deploy is free for a personal project". It isn't anymore: ~$3-8/month
idle, more under load. The deploy doc is honest about this — better to
surface the bill in the README than hand-wave it.

**SQLite + Fly volumes works fine for single-user.** The temptation
is to immediately reach for Postgres in prod. We don't need to. SQLite
on an attached volume survives deploys and lives perfectly within the
1-user assumption that's spelled out in the deploy doc.

### Interview talking points (Phase 4 specific)

- **"I treated CI as a contract with the future me."** The pipeline
  enforces 70% coverage *and* type-checks the frontend through `npm
  run build`. A green CI means a deploy is safe to push.
- **"The Docker image is honestly fat — and there's a documented fix."**
  Voyage embeddings remove ~3.5 GB. The retro names the trade-off
  instead of pretending the image is small.
- **"I picked Fly.io over Vercel/Render because the project has a
  Docker-shaped stack."** Vector DB + graph DB + Python service don't
  fit serverless platforms cleanly; Fly's per-app machines give every
  service its own predictable home.

### What stays out of scope

- **Auth.** Single-user, URL-only access today. Cloudflare Access or
  an OAuth proxy is the right next step before sharing the URL.
- **Backups.** Volumes survive deploys; they don't survive data
  corruption. A weekly `sqlite3 .backup` + Qdrant snapshot to S3 would
  close that gap.
- **Async ingestion.** Upload blocks while extraction runs. A queue
  (Fly Machines, RQ) would let the UI return immediately and a worker
  finish the slow part — only worth it once there are multiple users.

---

# Phase 1 Retro — MVP RAG

Written at the end of Phase 1, before opening Phase 2. The goal of
this file is to capture what was *surprising* or *non-obvious*, so the
same lessons don't have to be re-discovered in Phase 2.

## What got built

A working RAG over arbitrary documents:

- Backend: FastAPI + SQLite + Qdrant + Claude API + `sentence-transformers`
- 50 tests, lint clean
- Frontend: Vite + React + TS + Tailwind 4, single-file UI
- One-command dev launcher (`./scripts/dev.sh`)
- Stack rationale, model docs, and a step-level roadmap committed
  alongside the code

End-to-end flow: upload PDF/DOCX/MD/TXT → it gets parsed,
chunked, embedded, stored in Qdrant. Ask a question → it gets
embedded, matched, sent to Claude with retrieved chunks, answer comes
back with citations.

## Surprises and lessons

### `:memory:` mode is the right call for tests, almost everywhere

Both Qdrant and SQLite support in-process modes that mimic the real
thing without network or filesystem state. We used both:

- `QdrantClient(":memory:")` — fully functional Qdrant, just in-process.
- `sqlite:///:memory:` with `StaticPool` — in-memory DB, one
  connection across all sessions (default pool gives every session a
  fresh empty DB and you lose your hour figuring out "no such table").

Default-mocking is a temptation in Python testing. For external
services that ship an in-process mode, **the in-process mode wins**.
Contract drift in `qdrant-client` or SQLAlchemy fails our tests
loudly; a hand-written mock would silently pass while production
breaks. The 4-second test runtime is worth it.

`FakeClaude` is the exception: Anthropic doesn't ship an offline
mode, so we built a tiny double with the same interface as
`client.messages.create()`. Same idea — mimic the interface, not the
behavior.

### The embedding model is the binding constraint, not the LLM

The original chunker plan said "~800-token chunks with ~100-token
overlap". That's the wrong sizing — `all-MiniLM-L6-v2` has a
**256-token window**. An 800-token chunk gets truncated; you'd embed
the first third of the text and silently lose the rest. After
correction: 200 words / 30 overlap (~250 / 40 tokens).

The lesson generalizes: when you have N components in a pipeline,
size everything for the **smallest window**, not the model you think
of as "the main one". In Phase 2 when we swap to `voyage-3`
(32k-token window), chunk sizing should be re-evaluated as a
deliberate experiment, not a copy-paste.

### `chunk.id` IS the Qdrant point_id — no UUIDs

The first design had a `qdrant_point_id: String(64)` field on the
Chunk model, intended to hold a UUID. Then: why? SQLite already
hands us a unique integer ID on `flush()`. Use that as the Qdrant
point_id. One ID space, no synchronization, no UUID library.

This is a tiny decision but it's a pattern: **resist plurals when a
singular will do**. Multiple IDs for the same thing means at least
one is redundant, and probably eventually inconsistent.

### Prompt caching has a minimum, and 150 tokens isn't it

I almost added `cache_control: {"type": "ephemeral"}` to the system
prompt for `/ask` reflexively. The `claude-api` skill caught it:
Opus 4.7 has a **4096-token minimum** for caching to activate.
Smaller prefixes silently no-op — `cache_creation_input_tokens: 0`,
no error, just wasted ceremony.

The broader lesson: prompt caching is "free" only when the cached
prefix is both **stable** and **large enough**. Hot tips:
- Don't interpolate `datetime.now()` into the system prompt.
- Don't switch models mid-conversation.
- Don't reorder a tool list non-deterministically.
- Don't cache a 150-token system prompt.

### Citations: only return chunks the model *actually* cited

It's tempting to return all retrieved chunks as "the context Claude
used". That's misleading. Claude might cite 1 of 5; the other 4 are
just things we showed it. Returning all 5 implies the answer rests on
them.

Fix: parse `[chunk:N]` out of the answer, return only those.
Hallucinated IDs (`[chunk:99]` when 99 wasn't retrieved) get
filtered. The test `test_ask_drops_hallucinated_chunk_ids_not_in_retrieved_hits`
stands guard.

### `StaticPool` for in-memory SQLite is non-obvious

In a single line: in-memory SQLite makes a fresh DB **per
connection**. With SQLAlchemy's default pool, the test client opens a
new connection for each request — and gets an empty database.
Tables you created during fixture setup were on a different
connection.

`poolclass=StaticPool` pins all sessions to one connection. This is
also the answer to ~80% of "I created the table, why does the test
say it doesn't exist" Stack Overflow questions.

### Vite's auto-port-jump bit us once

`localhost:5173` is taken by Sherpa's dev server in this workspace.
Vite happily moved to 5175 and we hit the page expecting it to be on
5173 — got Sherpa's UI instead. Two fixes:

1. CORS allowlist now covers 5173-5175.
2. Always read the actual URL from Vite's startup banner before
   testing.

This will keep biting if more sibling projects come online. A more
robust pattern in Phase 4 deploys: pin Vite's port explicitly per
project (`--port 5176`), or run dev servers in their own
docker-compose so each has a stable port mapping.

## Interview talking points (Phase 1 specific)

When the time comes to talk about this on a Junior AI Developer
interview, three honest threads:

1. **"I deliberately didn't use LangChain or LlamaIndex in Phase 1."**
   Hand-rolling the pipeline means I can answer "what does
   chunking/embedding/retrieval *actually* do?" with code I wrote. A
   framework would have hidden it.

2. **"I picked Qdrant over Milvus on operational grounds."** Sibling
   project Sherpa runs Milvus — three containers (Milvus + etcd +
   MinIO), three failure modes. Qdrant is one container. For a
   single-developer learning project, the right trade-off is the
   simpler one.

3. **"Tests use real Qdrant in-memory + a `FakeClaude` double."**
   Different services need different test strategies. The reasoning
   for each is explicit. The full suite is hermetic — no network,
   no Docker — but exercises the real client APIs.

## What's in scope for Phase 2

Per [ROADMAP.md](../ROADMAP.md):

- Claude tool use (web search, calculator, fetch URL)
- OpenAI integration + side-by-side comparison UI
- `voyage-3` embeddings swap with retrieval-quality measurement
- A small `docs/retrieval-experiment.md` writeup of the comparison

The natural first sub-task is tool use, because it doesn't touch the
RAG pipeline — it's a separate Claude capability layered on top.
Phase 2 tests can use the same `FakeClaude` pattern, just with
richer fake responses (multi-turn tool_use blocks).

## What's NOT in scope until Phase 4

- Real auth / multi-user
- Production deploy (Fly.io)
- Persistent uploads beyond the local `papermind.db`
- Background ingest workers (current path is synchronous in-request)
- Streaming responses (`/ask` is non-streaming for now)

Each of those is justified on its own; collectively they'd have
tripled Phase 1's scope. Phase 1's job was "prove the RAG loop
works"; it does.
