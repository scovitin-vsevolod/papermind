"""Deep health endpoint — checks every dependency the app actually uses.

Why this exists separately from ``GET /health``:
    * ``/health`` is the systemd / nginx liveness probe — it must return
      200 the moment uvicorn is up, regardless of whether downstream
      dependencies are healthy. Block it on Qdrant/Neo4j and a brief
      outage in either takes the backend down too.
    * ``/health/deep`` is the *readiness* probe — it actually pokes the
      SQLite DB, Qdrant, Neo4j, and config. Used by ``manage.sh status``
      to give a one-glance dashboard, and by humans curling from SSH
      when something feels off (cf. the Neo4j-not-running incident
      that motivated this endpoint).

Each check returns ``{"ok": bool, ...extras}`` and never raises — a
failing check just shows up in the response with ``ok: false`` and the
error message. The top-level ``ok`` is the AND of all checks.

Public endpoint: no auth required. Doesn't leak anything an attacker
can use (no DB rows, no api_key values) — just structural health and
which dependency is broken.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, engine, get_db
from app.models import User
from app.services import graph as graph_service
from app.services import qdrant as qdrant_service
from app.services.embeddings import current_backend

router = APIRouter(tags=["health"])

DbSession = Annotated[Session, Depends(get_db)]


def _check_db_connect(db: Session) -> dict:
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "url": settings.database_url}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _check_db_schema_present() -> dict:
    """Verify every model-declared table exists in SQLite.

    Phase 1 uses ``Base.metadata.create_all()`` instead of Alembic, so
    there's no ``alembic_version`` row to check against a HEAD revision.
    The structural equivalent is: compare the table names declared in
    code (``Base.metadata.tables``) against what actually exists in the
    database (``inspect(engine).get_table_names()``). If the SQLite file
    was deleted or never bootstrapped, this surfaces it.
    """
    try:
        expected = set(Base.metadata.tables.keys())
        actual = set(inspect(engine).get_table_names())
        missing = sorted(expected - actual)
        return {
            "ok": not missing,
            "expected": len(expected),
            "present": len(expected & actual),
            **({"missing": missing} if missing else {}),
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _check_qdrant_connect() -> dict:
    try:
        qdrant_service._client().get_collections()
        return {"ok": True, "url": settings.qdrant_url}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _check_qdrant_collection() -> dict:
    """Report the active-backend collection's existence and point count.

    Unlike Sherpa we DON'T call ``ensure_collection()`` here — that would
    require loading the embedding model just to learn the vector
    dimension, which is too expensive for a health probe. Non-existence
    is not a failure: collections are created lazily on the first
    upload. We just surface ``exists`` and ``points`` so the dashboard
    can show whether anything has been ingested yet.
    """
    try:
        name = qdrant_service.collection_name_for_backend()
        client = qdrant_service._client()
        if not client.collection_exists(name):
            return {"ok": True, "name": name, "exists": False, "points": 0}
        info = client.get_collection(name)
        return {
            "ok": True,
            "name": name,
            "exists": True,
            "points": info.points_count,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _check_neo4j_connect() -> dict:
    """Verify Bolt connectivity. The graph router 503s loudly when this
    fails — the readiness probe surfaces it BEFORE a user hits /graph.
    """
    try:
        driver = graph_service._driver()
        driver.verify_connectivity()
        return {"ok": True, "uri": settings.neo4j_uri}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _check_anthropic_key() -> dict:
    """No live API call — that costs money and adds latency. Just confirm
    the env var is non-empty; an actually-bad key surfaces on the first
    /ask call."""
    return {"ok": bool(settings.anthropic_api_key)}


def _check_users_present(db: Session) -> dict:
    """PaperMind is single-tenant but still gated behind login. Zero
    users == no way to use the UI. Common post-fresh-install gotcha:
    schema is ready but `python -m app.cli.create_user` was never run.
    """
    try:
        count = db.scalar(select(func.count(User.id))) or 0
        return {"ok": count > 0, "count": count}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@router.get("/health")
def health() -> dict[str, str]:
    """Cheap liveness probe — returns 200 as soon as uvicorn is up.

    Kept in the same shape as the original inline endpoint for backward
    compatibility (the frontend banner reads `claude_model` from here).
    """
    return {
        "status": "ok",
        "claude_model": settings.claude_model,
        "embedding_model": settings.embedding_model,
    }


@router.get("/health/deep")
def deep_health(db: DbSession) -> dict:
    checks = {
        "db_connect": _check_db_connect(db),
        "db_schema_present": _check_db_schema_present(),
        "qdrant_connect": _check_qdrant_connect(),
        "qdrant_collection": _check_qdrant_collection(),
        "neo4j_connect": _check_neo4j_connect(),
        "anthropic_key_set": _check_anthropic_key(),
        "users_present": _check_users_present(db),
    }
    return {
        "ok": all(c["ok"] for c in checks.values()),
        "backend": current_backend(),
        "checks": checks,
    }
