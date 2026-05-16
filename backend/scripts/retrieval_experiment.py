"""Retrieval-quality A/B between local MiniLM and Voyage AI's voyage-3.

Both backends are run against the same small literal corpus and the same
queries with hand-labelled "gold" relevant docs, then recall@5 is computed
per query and as a mean. Output goes to `docs/retrieval-experiment.md`.

Run from the backend dir:

    cd backend && uv run python scripts/retrieval_experiment.py

Prerequisites:
- Qdrant container up (`docker compose -f infra/docker-compose.yml up -d`).
- `VOYAGE_API_KEY` set in `.env` (otherwise the voyage side fails fast).

Why a script and not a pytest:
- Slow: real API calls, not a tight inner loop you'd want to run on every
  commit.
- Side-effect heavy: writes to Qdrant collections, expects a running
  container, costs cents per run.
- Output is *documentation*, not a green/red signal.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Make the package importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.config import settings  # noqa: E402
from app.services import embeddings  # noqa: E402
from app.services import qdrant as qdrant_service

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs" / "retrieval-experiment.md"
TOP_K = 5


# ── Corpus ────────────────────────────────────────────────────────────────────
# Ten short snippets — eight on tech topics, two off-topic controls. The
# off-topic ones are there to verify both backends *don't* retrieve them on
# tech queries.


@dataclass(frozen=True)
class Doc:
    id: int
    title: str
    text: str


CORPUS: list[Doc] = [
    Doc(
        1,
        "RAG architecture",
        "Retrieval-augmented generation (RAG) combines an embedding-based "
        "retrieval step with a large language model. The pipeline: parse "
        "documents, split into chunks, embed each chunk, store the vectors. "
        "At query time, embed the question, find the nearest chunks, and "
        "pass them as context to the LLM. This grounds answers in source "
        "material instead of relying purely on model parameters.",
    ),
    Doc(
        2,
        "Vector databases",
        "A vector database stores high-dimensional embeddings and supports "
        "approximate nearest-neighbour search. Qdrant, Milvus, Weaviate, "
        "and pgvector are common open-source options. Qdrant runs in a "
        "single container; Milvus needs etcd and MinIO sidecars. The choice "
        "is mostly about operational complexity for small projects.",
    ),
    Doc(
        3,
        "Embedding models",
        "Embedding models map text to dense vectors so semantically similar "
        "text lands near each other in vector space. sentence-transformers "
        "models like all-MiniLM-L6-v2 run locally and produce 384-dim "
        "vectors. Voyage AI's voyage-3 is an API-served model with 1024 "
        "dims and stronger retrieval quality in published benchmarks.",
    ),
    Doc(
        4,
        "Python async",
        "Python's asyncio runtime lets you write concurrent code with "
        "async/await syntax. An async function returns a coroutine; you "
        "await it inside another async function or run it with asyncio.run "
        "at the top level. The event loop runs one coroutine at a time; "
        "I/O waits yield control so other coroutines can progress.",
    ),
    Doc(
        5,
        "SQL injection",
        "SQL injection happens when user input is concatenated into a SQL "
        "query string, letting attackers smuggle in their own SQL. The "
        "defence is parameterised queries: the driver sends the SQL "
        "template and the parameters separately, so user input is treated "
        "as data, not code. ORMs like SQLAlchemy do this by default.",
    ),
    Doc(
        6,
        "JavaScript promises",
        "A Promise represents the eventual result of an asynchronous "
        "operation. You can chain promises with .then(), but modern code "
        "uses async/await which reads like synchronous code while still "
        "running asynchronously. Errors propagate through .catch() or a "
        "try/catch block around await.",
    ),
    Doc(
        7,
        "React hooks",
        "React hooks let function components manage state and side effects. "
        "useState holds local state across re-renders. useEffect runs side "
        "effects after render and can clean up when dependencies change. "
        "useMemo memoises a value, useCallback memoises a function — both "
        "skip recomputation when their dependencies are unchanged.",
    ),
    Doc(
        8,
        "Docker compose",
        "Docker Compose describes a multi-container application in a single "
        "YAML file. Each service has an image, environment, ports, volumes, "
        "and networks. `docker compose up` brings the whole stack up; "
        "`docker compose down` stops it. Volumes persist data between runs; "
        "networks let services talk to each other by service name.",
    ),
    Doc(
        9,
        "Cooking pasta",  # off-topic control
        "To cook pasta well, bring a large pot of water to a rolling boil, "
        "salt it heavily, and add the pasta. Stir for the first minute to "
        "prevent sticking. Cook until al dente — usually one minute less "
        "than the box says. Reserve a cup of starchy water before draining "
        "to loosen the sauce later.",
    ),
    Doc(
        10,
        "Tax filing",  # off-topic control
        "Filing taxes in the US starts with gathering W-2s and 1099s, then "
        "deciding between the standard deduction and itemising. Tax "
        "software walks you through each form. The federal deadline is "
        "April 15 in most years. Self-employed filers pay quarterly "
        "estimated taxes throughout the year.",
    ),
]


# ── Queries with hand-labelled gold relevant doc IDs ─────────────────────────


@dataclass(frozen=True)
class Query:
    text: str
    gold: set[int]


QUERIES: list[Query] = [
    Query("How does retrieval-augmented generation work?", {1}),
    Query("Which vector databases are open source?", {2}),
    Query("Difference between local and API embedding models?", {3}),
    Query("How do I write concurrent code in Python?", {4}),
    Query("How to prevent SQL injection in a web app?", {5}),
    Query("Should I use Promise chains or async/await in JavaScript?", {6}),
    Query("When does useEffect run in a React component?", {7}),
    Query("How do containers in docker-compose communicate?", {8}),
    # Paraphrase / hard cases
    Query("What does RAG mean and why is it useful?", {1}),
    Query("Tell me about voyage-3 versus MiniLM", {3}),
]


# ── Experiment runner ────────────────────────────────────────────────────────


@dataclass
class BackendResult:
    backend: str
    dim: int
    upsert_seconds: float
    per_query: list[dict[str, object]]
    mean_recall_at_5: float


def run_for_backend(backend: str) -> BackendResult:
    """Re-index the corpus with the given backend, run all queries, return metrics."""
    print(f"\n── Backend: {backend} ──")
    settings.embedding_provider = backend  # type: ignore[assignment]
    embeddings.reset_caches_for_tests()

    # Fresh collection — drop if it exists from a previous run.
    collection = qdrant_service.collection_name_for_backend(backend)
    client = qdrant_service._client()  # noqa: SLF001 — internal but stable
    if client.collection_exists(collection):
        client.delete_collection(collection)
    qdrant_service.ensure_collection(backend=backend)

    # Index the corpus.
    t0 = time.time()
    vectors = embeddings.embed([d.text for d in CORPUS], is_query=False)
    items = [
        qdrant_service.UpsertItem(
            point_id=d.id,
            vector=vectors[i],
            document_id=d.id,  # one chunk per "doc" in this experiment
            position=0,
            text=d.text,
        )
        for i, d in enumerate(CORPUS)
    ]
    qdrant_service.upsert_chunks(items, backend=backend)
    upsert_seconds = time.time() - t0
    print(f"  indexed {len(CORPUS)} docs in {upsert_seconds:.2f}s")

    # Query each.
    per_query: list[dict[str, object]] = []
    recall_sum = 0.0
    for q in QUERIES:
        qv = embeddings.embed([q.text], is_query=True)[0]
        hits = qdrant_service.search(qv, top_k=TOP_K, backend=backend)
        retrieved_ids = [h.chunk_id for h in hits]
        hit_set = set(retrieved_ids)
        recall = len(hit_set & q.gold) / max(1, len(q.gold))
        recall_sum += recall
        per_query.append(
            {
                "query": q.text,
                "gold": sorted(q.gold),
                "retrieved": retrieved_ids,
                "recall_at_5": recall,
            }
        )
        marker = "✓" if recall == 1.0 else "✗"
        print(f"  {marker} '{q.text[:55]}…'  gold={sorted(q.gold)}  top={retrieved_ids}")

    mean_recall = recall_sum / len(QUERIES)
    print(f"  mean recall@5 = {mean_recall:.3f}")
    return BackendResult(
        backend=backend,
        dim=embeddings.embedding_dim(),
        upsert_seconds=upsert_seconds,
        per_query=per_query,
        mean_recall_at_5=mean_recall,
    )


# ── Markdown report ──────────────────────────────────────────────────────────


def write_report(local: BackendResult, voyage: BackendResult) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Retrieval experiment — MiniLM vs voyage-3")
    lines.append("")
    lines.append(f"> Generated: {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(
        f"- Corpus: **{len(CORPUS)} short documents** (8 on tech topics, 2 "
        "off-topic controls)."
    )
    lines.append(f"- Queries: **{len(QUERIES)}**, each with a hand-labelled gold doc id.")
    lines.append(f"- top_k = **{TOP_K}**, metric = **recall@5**.")
    lines.append(f"- Local backend: `{settings.embedding_model}` (dim {local.dim}).")
    lines.append(f"- API backend: `{settings.voyage_model}` (dim {voyage.dim}).")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("| Backend | Dim | Index time | Mean recall@5 |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| MiniLM (local) | {local.dim} | {local.upsert_seconds:.2f}s | "
        f"**{local.mean_recall_at_5:.3f}** |"
    )
    lines.append(
        f"| voyage-3 (API) | {voyage.dim} | {voyage.upsert_seconds:.2f}s | "
        f"**{voyage.mean_recall_at_5:.3f}** |"
    )
    lines.append("")
    lines.append("## Per-query")
    lines.append("")
    lines.append("| Query | Gold | MiniLM top-5 | voyage-3 top-5 | MiniLM @5 | voyage @5 |")
    lines.append("|---|---|---|---|---|---|")
    for lq, vq in zip(local.per_query, voyage.per_query, strict=True):
        gold = ", ".join(str(g) for g in lq["gold"])  # type: ignore[arg-type]
        local_top = ", ".join(str(x) for x in lq["retrieved"])  # type: ignore[arg-type]
        voyage_top = ", ".join(str(x) for x in vq["retrieved"])  # type: ignore[arg-type]
        lines.append(
            f"| {lq['query']} | {gold} | {local_top} | {voyage_top} | "
            f"{lq['recall_at_5']:.2f} | {vq['recall_at_5']:.2f} |"
        )
    lines.append("")
    lines.append("## Raw")
    lines.append("")
    lines.append("```json")
    lines.append(
        json.dumps(
            {
                "minilm": local.per_query,
                "voyage": voyage.per_query,
            },
            indent=2,
        )
    )
    lines.append("```")
    REPORT_PATH.write_text("\n".join(lines))
    print(f"\n✓ wrote {REPORT_PATH.relative_to(REPO_ROOT)}")


def main() -> int:
    if not os.environ.get("VOYAGE_API_KEY") and not settings.voyage_api_key:
        print(
            "✗ VOYAGE_API_KEY is not set. The experiment requires both backends.\n"
            "  Add VOYAGE_API_KEY=... to backend/.env or export it in your shell.",
            file=sys.stderr,
        )
        return 1

    local = run_for_backend("sentence-transformers")
    voyage = run_for_backend("voyage")
    write_report(local, voyage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
