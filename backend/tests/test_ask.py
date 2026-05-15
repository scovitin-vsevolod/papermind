"""End-to-end tests for the /ask endpoint.

The real embedding model and in-memory Qdrant run; the Anthropic client
is replaced with a ``FakeClaude`` whose response we set per-test. This
lets us verify the *prompt shape* sent to Claude, the *citation
parsing*, and the *DB query log* without spending money or relying on
network availability.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Query
from tests.conftest import FakeClaude


def _upload(client: TestClient, name: str, body: bytes, mime: str = "text/plain"):
    return client.post("/documents", files={"file": (name, body, mime)})


def test_ask_returns_answer_with_parsed_citations(
    client: TestClient, fake_claude: FakeClaude
):
    _upload(
        client,
        "intro.md",
        b"PaperMind is a personal research companion built on Claude.",
    )
    fake_claude.response_text = "PaperMind is built on Claude [chunk:1]."

    r = client.post("/ask", json={"question": "What is PaperMind built on?"})
    assert r.status_code == 200, r.text

    body = r.json()
    assert "Claude" in body["answer"]
    assert body["model"] == "claude-sonnet-4-6"
    assert len(body["citations"]) == 1
    assert body["citations"][0]["chunk_id"] == 1
    assert "PaperMind" in body["citations"][0]["text"]


def test_ask_sends_correct_prompt_to_claude(
    client: TestClient, fake_claude: FakeClaude
):
    _upload(client, "ctx.txt", b"Reference fact about cats.")
    fake_claude.response_text = "Some answer [chunk:1]"

    client.post("/ask", json={"question": "Tell me about cats"})

    assert len(fake_claude.calls) == 1
    call = fake_claude.calls[0]

    # Model + system prompt go through unchanged.
    assert call["model"] == "claude-sonnet-4-6"
    assert "research assistant" in call["system"].lower()

    # Sampling params we explicitly do NOT send (Opus 4.7 would 400; Sonnet
    # accepts but we omit them so this code works on either model).
    assert "temperature" not in call
    assert "top_p" not in call
    assert "top_k" not in call
    assert "thinking" not in call

    # User message contains the question + tagged excerpts.
    user_msg = call["messages"][0]["content"]
    assert "Tell me about cats" in user_msg
    assert "[chunk:" in user_msg
    assert "Reference fact about cats" in user_msg


def test_ask_logs_query_with_cited_chunk_ids(
    client: TestClient, fake_claude: FakeClaude, db_session: Session
):
    _upload(client, "doc.txt", b"some content for ingestion")
    fake_claude.response_text = "Answer [chunk:1] [chunk:1]"  # dup → should dedupe

    client.post("/ask", json={"question": "Q1?"})

    rows = db_session.query(Query).all()
    assert len(rows) == 1
    assert rows[0].question == "Q1?"
    assert rows[0].model == "claude-sonnet-4-6"
    assert json.loads(rows[0].chunk_ids) == [1]


def test_ask_returns_only_chunks_the_model_actually_cited(
    client: TestClient, fake_claude: FakeClaude
):
    # A doc that produces multiple chunks.
    _upload(
        client,
        "multi.md",
        b"# First\n\n" + b"x " * 300 + b"\n\n# Second\n\n" + b"y " * 300,
    )
    # Even though multiple chunks may be retrieved, model only cites chunk 1.
    fake_claude.response_text = "I only need [chunk:1] here."

    r = client.post("/ask", json={"question": "Q?", "top_k": 5})
    citations = r.json()["citations"]
    assert len(citations) == 1
    assert citations[0]["chunk_id"] == 1


def test_ask_drops_hallucinated_chunk_ids_not_in_retrieved_hits(
    client: TestClient, fake_claude: FakeClaude
):
    _upload(client, "x.txt", b"single chunk of content")
    # Chunk 99 was never retrieved — must not appear in citations.
    fake_claude.response_text = "Answer [chunk:1] and also [chunk:99]"

    citations = client.post("/ask", json={"question": "Q?"}).json()["citations"]
    chunk_ids = [c["chunk_id"] for c in citations]
    assert 1 in chunk_ids
    assert 99 not in chunk_ids


def test_ask_filters_by_document_id(client: TestClient, fake_claude: FakeClaude):
    doc1 = _upload(client, "d1.txt", b"content of document one").json()
    _upload(client, "d2.txt", b"content of document two")

    fake_claude.response_text = "answer [chunk:1] [chunk:2] [chunk:3]"

    r = client.post(
        "/ask", json={"question": "Q?", "top_k": 10, "document_id": doc1["id"]}
    )
    assert r.status_code == 200
    for citation in r.json()["citations"]:
        assert citation["document_id"] == doc1["id"]


def test_ask_returns_404_for_unknown_document(
    client: TestClient, fake_claude: FakeClaude
):
    r = client.post("/ask", json={"question": "Q?", "document_id": 99999})
    assert r.status_code == 404


def test_ask_validation_rejects_empty_question(
    client: TestClient, fake_claude: FakeClaude
):
    r = client.post("/ask", json={"question": ""})
    assert r.status_code == 422
    # Real Claude must NOT have been invoked.
    assert fake_claude.calls == []


def test_ask_works_with_no_documents_in_corpus(
    client: TestClient, fake_claude: FakeClaude
):
    # Nothing ingested — search returns no hits, Claude gets the
    # "(no excerpts retrieved)" placeholder and answers accordingly.
    fake_claude.response_text = "I don't have enough information to answer."

    r = client.post("/ask", json={"question": "What do you know?"})
    assert r.status_code == 200
    assert r.json()["citations"] == []
