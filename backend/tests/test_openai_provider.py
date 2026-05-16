"""Tests for the OpenAI provider path on /ask."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import FakeClaude, FakeOpenAI


def _upload(client: TestClient, name: str, body: bytes):
    return client.post("/documents", files={"file": (name, body, "text/plain")})


def test_provider_openai_routes_to_openai_client(
    client: TestClient, fake_claude: FakeClaude, fake_openai: FakeOpenAI
):
    _upload(client, "doc.txt", b"PaperMind ingests documents.")
    # Drop extraction calls from upload — this test asserts /ask routes
    # past Claude entirely when provider=openai.
    fake_claude.calls.clear()
    fake_openai.response_text = "PaperMind ingests documents [chunk:1]."

    r = client.post(
        "/ask",
        json={"question": "What does PaperMind do?", "provider": "openai"},
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["model"] == "gpt-4o"
    assert "PaperMind" in body["answer"]
    # Claude must NOT have been called when provider=openai.
    assert fake_claude.calls == []
    # OpenAI was called once with the OpenAI message shape.
    assert len(fake_openai.calls) == 1
    call = fake_openai.calls[0]
    assert call["model"] == "gpt-4o"
    msgs = call["messages"]
    assert msgs[0]["role"] == "system"
    assert "research assistant" in msgs[0]["content"].lower()
    assert msgs[1]["role"] == "user"
    assert "What does PaperMind do?" in msgs[1]["content"]


def test_provider_claude_is_default_and_does_not_call_openai(
    client: TestClient, fake_claude: FakeClaude, fake_openai: FakeOpenAI
):
    _upload(client, "doc.txt", b"some content")
    fake_claude.calls.clear()  # ignore extraction calls during upload
    fake_claude.response_text = "claude answer [chunk:1]"

    client.post("/ask", json={"question": "q?"})

    assert len(fake_claude.calls) == 1
    assert fake_openai.calls == []


def test_provider_openai_response_omits_tool_uses(
    client: TestClient, fake_claude: FakeClaude, fake_openai: FakeOpenAI
):
    # OpenAI path intentionally doesn't expose tool use yet (Phase 2 scope).
    _upload(client, "doc.txt", b"content")
    fake_openai.response_text = "answer [chunk:1]"

    r = client.post(
        "/ask",
        json={"question": "q?", "provider": "openai", "use_tools": True},
    )
    body = r.json()
    assert body["tool_uses"] == []


def test_provider_openai_parses_citations(
    client: TestClient, fake_claude: FakeClaude, fake_openai: FakeOpenAI
):
    _upload(client, "doc.txt", b"first chunk only")
    fake_openai.response_text = "Two refs: [chunk:1] and [chunk:1]"  # duplicate

    r = client.post(
        "/ask", json={"question": "q?", "provider": "openai"}
    )
    citations = r.json()["citations"]
    # Dedup happens in _extract_citations.
    chunk_ids = [c["chunk_id"] for c in citations]
    assert chunk_ids == [1]


def test_provider_validation_rejects_unknown_value(
    client: TestClient, fake_claude: FakeClaude, fake_openai: FakeOpenAI
):
    r = client.post(
        "/ask", json={"question": "q?", "provider": "gemini"}
    )
    assert r.status_code == 422
    assert fake_claude.calls == []
    assert fake_openai.calls == []
