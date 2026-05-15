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

echo "▶ Starting backend on :8109…"
( cd backend && uv run uvicorn app.main:app --reload --port 8109 2>&1 \
    | prefix "backend " ) &
PIDS+=($!)

if [[ -d "$ROOT/frontend/node_modules" ]]; then
  echo "▶ Starting frontend (vite pinned to 5209, strictPort)…"
  ( cd frontend && npm run dev --silent 2>&1 \
      | prefix "frontend" ) &
  PIDS+=($!)
fi

# ── App URL (Valet-aware) ─────────────────────────────────────────────────────
# Try to detect a Valet proxy named "papermind" pointing at 5209 and surface
# its .test URL in the banner. Falls back to the raw localhost URL with a
# one-line hint for setting up the proxy.

VALET_DOMAIN="papermind"
VITE_PORT="5209"
APP_URL="http://localhost:${VITE_PORT}"
APP_HINT=""

if command -v valet >/dev/null 2>&1; then
  proxy_row=$(valet proxies 2>/dev/null | grep -E "^\|[[:space:]]+${VALET_DOMAIN}[[:space:]]+\|" || true)
  if [[ -n "$proxy_row" ]] && echo "$proxy_row" | grep -qE "127\.0\.0\.1:${VITE_PORT}|localhost:${VITE_PORT}"; then
    # 3rd "|"-separated column is the .test URL. Trim whitespace.
    APP_URL=$(echo "$proxy_row" | awk -F'|' '{ gsub(/^[[:space:]]+|[[:space:]]+$/, "", $4); print $4 }')
    if [[ "$APP_URL" == http://* ]]; then
      # Proxy exists but on plain HTTP. NOTE: `valet secure <domain>` on an
      # existing proxy REGENERATES the nginx config from a PHP template and
      # silently drops `proxy_pass` — recreate the proxy with --secure to
      # get HTTPS + proxy together.
      APP_HINT="(via Valet → :${VITE_PORT}) — ⚠ plain HTTP; upgrade:  valet unproxy ${VALET_DOMAIN} && valet proxy ${VALET_DOMAIN} http://localhost:${VITE_PORT} --secure"
    else
      APP_HINT="(via Valet → :${VITE_PORT}, HTTPS)"
    fi
  else
    APP_HINT="⚠ no Valet proxy — run:  valet proxy ${VALET_DOMAIN} http://localhost:${VITE_PORT} --secure"
  fi
fi

cat <<EOF

── URLs ─────────────────────────────────────────────
  App:        ${APP_URL}
              ${APP_HINT}
  Backend:    http://localhost:8109
              http://localhost:8109/docs   (OpenAPI)
              http://localhost:8109/health
  Qdrant:     http://localhost:6333
              http://localhost:6333/dashboard  (UI)
─────────────────────────────────────────────────────

  Ctrl+C to stop dev servers (Qdrant stays up).

EOF

wait
