#!/usr/bin/env bash
# Single-command dev launcher for PaperMind.
#
# Brings up Qdrant (docker compose), bootstraps DB tables, then starts
# the backend (and frontend, once it exists) in the same terminal with
# prefixed log streams. Ctrl+C stops the dev servers; the Qdrant
# container stays up so vectors persist between sessions.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# ── pre-flight ────────────────────────────────────────────────────────────────

if [[ ! -d "$ROOT/backend/.venv" ]]; then
  echo "✗ backend/.venv missing — run:"
  echo "    cd backend && uv sync"
  exit 1
fi

if [[ ! -f "$ROOT/backend/.env" ]]; then
  echo "⚠ backend/.env missing — Q&A endpoints will fail without ANTHROPIC_API_KEY."
  echo "   cp backend/.env.example backend/.env  and fill in the key."
fi

# ── Qdrant ────────────────────────────────────────────────────────────────────

echo "▶ Starting Qdrant…"
(cd infra && docker compose up -d) > /dev/null

echo "▶ Waiting for Qdrant to become healthy…"
for _ in $(seq 1 30); do
  if curl -fs --max-time 2 http://localhost:6333/readyz > /dev/null 2>&1; then
    echo "  ✓ Qdrant is up"
    break
  fi
  sleep 1
done
if ! curl -fs --max-time 2 http://localhost:6333/readyz > /dev/null 2>&1; then
  echo "  ✗ Qdrant didn't come up in 30s. Inspect: cd infra && docker compose logs qdrant"
  exit 1
fi

# ── DB bootstrap ──────────────────────────────────────────────────────────────
# Phase 1 uses create_all() for simplicity. Alembic migrations replace this
# in a later phase.

echo "▶ Creating DB tables…"
( cd backend && uv run python -c \
    "from app.db import Base, engine; import app.models; Base.metadata.create_all(engine); print('  ✓ tables ready')" )

# ── backend (+ frontend if present) ───────────────────────────────────────────

PIDS=()
cleanup() {
  echo
  echo "▶ Stopping dev servers…"
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "  ✓ Stopped. Qdrant is still up — \`./scripts/down.sh\` to stop it too."
}
trap cleanup INT TERM EXIT

prefix() {
  local tag="$1"
  while IFS= read -r line; do
    printf '[%s] %s\n' "$tag" "$line"
  done
}

echo "▶ Starting backend on :8130…"
( cd backend && uv run uvicorn app.main:app --reload --port 8130 2>&1 \
    | prefix "backend " ) &
PIDS+=($!)

if [[ -d "$ROOT/frontend/node_modules" ]]; then
  echo "▶ Starting frontend (vite picks 5173 or next free)…"
  ( cd frontend && npm run dev --silent 2>&1 \
      | prefix "frontend" ) &
  PIDS+=($!)
fi

cat <<EOF

── URLs ─────────────────────────────────────────────
  Backend:    http://localhost:8130
              http://localhost:8130/docs   (OpenAPI)
              http://localhost:8130/health
  Qdrant:     http://localhost:6333
              http://localhost:6333/dashboard  (UI)
─────────────────────────────────────────────────────

  Ctrl+C to stop dev servers (Qdrant stays up).

EOF

wait
