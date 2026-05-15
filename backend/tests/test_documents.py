"""End-to-end tests for the documents API.

These tests exercise the full ingest pipeline: upload → markitdown
parse → chunk → embed → Qdrant upsert → SQLite rows. The real
sentence-transformers model is loaded (cached after the first run).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services import qdrant as qdrant_service
from app.services.embeddings import embed


def _upload(client: TestClient, name: str, body: bytes, mime: str = "text/plain"):
    return client.post("/documents", files={"file": (name, body, mime)})


def test_upload_txt_returns_ready_document(client: TestClient):
    payload = b"PaperMind is a personal research companion.\n\nIt uses Claude and Qdrant."
    r = _upload(client, "intro.txt", payload)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["filename"] == "intro.txt"
    assert data["status"] == "ready"
    assert data["chunk_count"] >= 1
    assert data["error"] is None
    assert data["size_bytes"] == len(payload)


def test_upload_persists_chunks_to_qdrant(client: TestClient):
    r = _upload(
        client,
        "intro.md",
        b"# Title\n\nPaperMind ingests documents and answers questions about them.",
    )
    doc_id = r.json()["id"]

    # Search Qdrant with a related query — the chunk we just ingested
    # must score above an unrelated one.
    related = embed(["What does PaperMind do?"])[0]
    hits = qdrant_service.search(related, top_k=5, document_id=doc_id)
    assert hits, "expected at least one hit for the uploaded document"
    assert hits[0].document_id == doc_id
    assert "PaperMind" in hits[0].text


def test_list_returns_documents_newest_first(client: TestClient):
    _upload(client, "first.txt", b"first document body")
    _upload(client, "second.txt", b"second document body")

    r = client.get("/documents")
    assert r.status_code == 200
    docs = r.json()
    assert [d["filename"] for d in docs] == ["second.txt", "first.txt"]


def test_get_by_id_returns_document(client: TestClient):
    created = _upload(client, "a.txt", b"hello there").json()
    r = client.get(f"/documents/{created['id']}")
    assert r.status_code == 200
    assert r.json()["filename"] == "a.txt"


def test_get_missing_returns_404(client: TestClient):
    assert client.get("/documents/99999").status_code == 404


def test_delete_removes_from_both_stores(client: TestClient):
    doc = _upload(client, "ephemeral.txt", b"this will be deleted").json()
    doc_id = doc["id"]

    # Verify it's in Qdrant first.
    pre = qdrant_service.search(embed(["deleted"])[0], top_k=10, document_id=doc_id)
    assert pre, "expected chunks in Qdrant before delete"

    r = client.delete(f"/documents/{doc_id}")
    assert r.status_code == 204

    # SQLite: gone.
    assert client.get(f"/documents/{doc_id}").status_code == 404
    # Qdrant: gone.
    post = qdrant_service.search(embed(["deleted"])[0], top_k=10, document_id=doc_id)
    assert post == []


def test_delete_missing_returns_404(client: TestClient):
    assert client.delete("/documents/99999").status_code == 404


def test_upload_unsupported_extension_returns_400(client: TestClient):
    r = _upload(client, "noext", b"some content")
    assert r.status_code == 400
    assert "extension" in r.json()["detail"]


def test_upload_empty_file_returns_400(client: TestClient):
    r = _upload(client, "empty.txt", b"")
    assert r.status_code == 400


def test_upload_markdown_preserves_content(client: TestClient):
    md = b"# Heading\n\nA paragraph about **PaperMind** and its features."
    r = _upload(client, "doc.md", md)
    assert r.status_code == 201
    doc_id = r.json()["id"]

    hits = qdrant_service.search(embed(["features of PaperMind"])[0], top_k=3, document_id=doc_id)
    assert hits
    assert any("PaperMind" in h.text for h in hits)
