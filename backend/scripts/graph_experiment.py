"""GraphRAG lift measurement — vector-only vs vector + graph augmentation.

The retrieval_experiment.py script compares EMBEDDING backends (MiniLM vs
voyage-3). This one isolates the **graph** variable: same MiniLM
embedding throughout, but compares plain Qdrant top-K against the
graph-augmented top-(K+N).

Run from the backend dir:

    cd backend && uv run python scripts/graph_experiment.py

Prerequisites:
- Qdrant + Neo4j running (`./manage.sh start`).
- ANTHROPIC_API_KEY in .env (extraction is real Claude calls).

Output: docs/graph-experiment.md, overwritten on each run.

Caveats baked in
----------------
Corpus is intentionally tiny (10 docs, 10 queries, 1 gold doc each) —
graphRAG's value scales with corpus size and entity density. Numbers
here should be read as "does the harness work end-to-end?" rather
than "is GraphRAG worth it in general?". That bigger answer needs a
real corpus and the time to label it.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Make the package importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services import embeddings, graph_rag  # noqa: E402  # noqa: E402
from app.services import graph as graph_service  # noqa: E402
from app.services import qdrant as qdrant_service

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs" / "graph-experiment.md"
TOP_K = 5


# ── Tiny corpus designed for graph value ─────────────────────────────────────
# Each fact uses entities that connect via edges, so a question about
# entity A can plausibly need a chunk that only mentions entity B.


@dataclass(frozen=True)
class Doc:
    id: int
    title: str
    text: str


CORPUS: list[Doc] = [
    Doc(1, "Anthropic", "Anthropic is an AI safety company headquartered in San Francisco."),
    Doc(2, "Claude", "Claude is an AI assistant. The current generation is Claude Sonnet 4.6."),
    Doc(3, "Dario", "Dario Amodei is the CEO of Anthropic and previously worked at OpenAI."),
    Doc(4, "Constitutional AI", "Constitutional AI is a training technique used by Anthropic."),
    Doc(5, "RLHF", "Reinforcement learning from human feedback aligns large language models."),
    Doc(
        6,
        "Python",
        "Python is a general-purpose programming language used in scientific computing.",
    ),
    Doc(7, "Anthropic SDK", "The anthropic Python SDK exposes Claude through messages.create()."),
    Doc(8, "FastAPI", "FastAPI is a Python web framework that pairs well with Pydantic."),
    Doc(9, "Off-topic", "Recipes for sourdough usually call for a warm oven."),
    Doc(10, "Off-topic", "The Pomodoro technique alternates 25-minute work intervals with breaks."),
]


@dataclass(frozen=True)
class Query:
    text: str
    gold: set[int]


# Queries deliberately phrased so the gold doc may not be the obvious
# top-1 for vector search. The graph edges (Anthropic→Claude→Dario, etc.)
# are what should bring the right doc in.
QUERIES: list[Query] = [
    Query("Who runs Anthropic?", {3}),                  # gold mentions Anthropic only via edge
    Query("What does Anthropic make?", {2}),            # gold is "Claude", linked via develops
    Query("Tell me about Claude Sonnet", {2}),          # direct hit
    Query("What is Constitutional AI?", {4}),           # direct hit
    Query("How are LLMs aligned?", {5}),                # direct hit (RLHF)
    Query("What language is the Anthropic SDK in?", {7}),  # the SDK doc mentions Python explicitly
    Query("Who founded Anthropic?", {3}),               # paraphrase of "Who runs"
    Query("How do I call Claude from code?", {7}),      # direct hit (SDK)
    Query("Which framework pairs with Pydantic?", {8}), # direct hit (FastAPI)
    Query("What's a good way to focus?", {10}),         # direct hit (Pomodoro)
]


# Edges that connect the tech entities. Kept tiny + hand-curated so we
# control exactly what graph augmentation can do.
SEED_EDGES: list[tuple[str, str, str, int]] = [
    # (head, label, tail, owning_doc)
    ("Anthropic",        "develops",     "Claude",                2),
    ("Anthropic",        "led by",       "Dario Amodei",          3),
    ("Anthropic",        "uses technique", "Constitutional AI",   4),
    ("Anthropic SDK",    "language",     "Python",                7),
    ("FastAPI",          "pairs with",   "Pydantic",              8),
    ("Claude",           "alignment",    "RLHF",                  5),
]

SEED_ENTITIES: list[tuple[str, str, list[int]]] = [
    ("Anthropic",          "Organization",  [1, 3, 4]),
    ("Claude",             "Product",       [2]),
    ("Dario Amodei",       "Person",        [3]),
    ("Constitutional AI",  "Concept",       [4]),
    ("RLHF",               "Concept",       [5]),
    ("Python",             "Technology",    [6, 7]),
    ("Anthropic SDK",      "Technology",    [7]),
    ("FastAPI",            "Technology",    [8]),
    ("Pydantic",           "Technology",    [8]),
]


# ── Experiment runner ────────────────────────────────────────────────────────


@dataclass
class Result:
    mode: str
    per_query: list[dict]
    mean_recall_at_5: float


def reset_collection(backend: str = "sentence-transformers") -> None:
    name = qdrant_service.collection_name_for_backend(backend)
    client = qdrant_service._client()  # noqa: SLF001
    if client.collection_exists(name):
        client.delete_collection(name)
    qdrant_service.ensure_collection(backend=backend)


def index_corpus() -> None:
    vectors = embeddings.embed([d.text for d in CORPUS], is_query=False)
    qdrant_service.upsert_chunks(
        [
            qdrant_service.UpsertItem(
                point_id=d.id,
                vector=vectors[i],
                document_id=d.id,
                position=0,
                text=d.text,
            )
            for i, d in enumerate(CORPUS)
        ]
    )


def seed_graph() -> None:
    """Plant the curated entities + edges directly in Neo4j.

    Bypasses extraction so the experiment isolates retrieval — the
    graph is "ground truth" relative to what the embedding can do.
    """
    graph_service.ensure_schema()
    with graph_service._driver().session() as session:  # noqa: SLF001
        # Wipe whatever's there from previous runs.
        session.run("MATCH (n) DETACH DELETE n")
        for name, etype, doc_ids in SEED_ENTITIES:
            session.run(
                "MERGE (e:Entity {name: $name}) "
                "SET e.type = $type, e.document_ids = $doc_ids",
                name=name,
                type=etype,
                doc_ids=doc_ids,
            )
        for head, label, tail, doc_id in SEED_EDGES:
            session.run(
                "MATCH (h:Entity {name: $head}), (t:Entity {name: $tail}) "
                "MERGE (h)-[r:RELATES {label: $label}]->(t) "
                "SET r.document_ids = [$doc_id]",
                head=head,
                tail=tail,
                label=label,
                doc_id=doc_id,
            )


def run(mode: str, *, use_graph: bool) -> Result:
    print(f"\n── Mode: {mode} ──")
    per_query: list[dict] = []
    recall_sum = 0.0
    for q in QUERIES:
        qv = embeddings.embed([q.text], is_query=True)[0]
        vector_hits = qdrant_service.search(qv, top_k=TOP_K)
        if use_graph:
            augmented = graph_rag.augment(
                question=q.text, question_vector=qv, vector_hits=vector_hits
            )
            retrieved = [a.hit.chunk_id for a in augmented]
        else:
            retrieved = [h.chunk_id for h in vector_hits]
        recall = len(set(retrieved) & q.gold) / max(1, len(q.gold))
        recall_sum += recall
        per_query.append(
            {
                "query": q.text,
                "gold": sorted(q.gold),
                "retrieved": retrieved,
                "recall_at_5": recall,
            }
        )
        marker = "✓" if recall == 1.0 else "✗"
        print(f"  {marker} '{q.text[:55]}…' gold={sorted(q.gold)} → {retrieved}")
    mean = recall_sum / len(QUERIES)
    print(f"  mean recall@5 = {mean:.3f}")
    return Result(mode=mode, per_query=per_query, mean_recall_at_5=mean)


def write_report(baseline: Result, with_graph: Result) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    delta = with_graph.mean_recall_at_5 - baseline.mean_recall_at_5
    lines: list[str] = []
    lines.append("# GraphRAG experiment — vector vs vector+graph")
    lines.append("")
    lines.append(f"> Generated: {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(
        f"- Corpus: **{len(CORPUS)} docs**, hand-curated entities and "
        f"{len(SEED_EDGES)} edges seeded directly into Neo4j (extraction "
        "is bypassed so the graph is ground truth)."
    )
    lines.append(f"- Queries: **{len(QUERIES)}**, each with a single gold doc id.")
    lines.append(f"- Embedding: `{settings.embedding_model}` ({embeddings.embedding_dim()}-dim).")
    lines.append(f"- top_k = **{TOP_K}**, metric = **recall@5**.")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("| Mode | Mean recall@5 |")
    lines.append("|---|---|")
    lines.append(f"| vector only        | **{baseline.mean_recall_at_5:.3f}** |")
    lines.append(f"| vector + graph     | **{with_graph.mean_recall_at_5:.3f}** |")
    lines.append(f"| Δ (graph lift)     | **{delta:+.3f}** |")
    lines.append("")
    lines.append("## Per-query")
    lines.append("")
    lines.append("| Query | Gold | Vector top-K | Vector+Graph top-K | V @5 | V+G @5 |")
    lines.append("|---|---|---|---|---|---|")
    for vb, vg in zip(baseline.per_query, with_graph.per_query, strict=True):
        gold = ", ".join(str(g) for g in vb["gold"])  # type: ignore[arg-type]
        v_top = ", ".join(str(x) for x in vb["retrieved"])  # type: ignore[arg-type]
        g_top = ", ".join(str(x) for x in vg["retrieved"])  # type: ignore[arg-type]
        lines.append(
            f"| {vb['query']} | {gold} | {v_top} | {g_top} "
            f"| {vb['recall_at_5']:.2f} | {vg['recall_at_5']:.2f} |"
        )
    lines.append("")
    lines.append("## Raw")
    lines.append("")
    lines.append("```json")
    lines.append(
        json.dumps(
            {"baseline": baseline.per_query, "with_graph": with_graph.per_query},
            indent=2,
        )
    )
    lines.append("```")
    REPORT_PATH.write_text("\n".join(lines))
    print(f"\n✓ wrote {REPORT_PATH.relative_to(REPO_ROOT)}  (Δ recall@5 = {delta:+.3f})")


def main() -> int:
    if not settings.anthropic_api_key:
        print("✗ ANTHROPIC_API_KEY missing — entity extraction will fail.", file=sys.stderr)
        return 1
    reset_collection()
    index_corpus()
    seed_graph()
    baseline = run("vector only", use_graph=False)
    with_graph = run("vector + graph", use_graph=True)
    write_report(baseline, with_graph)
    return 0


if __name__ == "__main__":
    sys.exit(main())
