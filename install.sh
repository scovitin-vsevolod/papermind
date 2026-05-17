#!/bin/bash
set -e

# install.sh — one-shot setup for PaperMind.
#
# Installs backend (uv) and frontend (npm) dependencies, seeds
# backend/.env from the example, and pre-pulls infra images so the
# first `./manage.sh start` is fast. Idempotent — safe to re-run.
#
# Runtime orchestration lives in manage.sh / scripts/dev.sh; this
# script only prepares the environment.

cd "$(dirname "$0")"
ROOT="$(pwd)"

# ── prerequisites ─────────────────────────────────────────────────────────────

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "✗ Missing prerequisite: $1"
    echo "  $2"
    exit 1
  fi
}

echo "▶ Checking prerequisites…"
need uv     "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
need node   "Install Node 20+ (e.g. via nvm or 'brew install node')"
need npm    "npm ships with Node — reinstall Node if missing"
need docker "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
echo "  ✓ uv, node, npm, docker present"

# ── backend ───────────────────────────────────────────────────────────────────

echo "▶ Syncing backend dependencies (uv sync)…"
( cd "$ROOT/backend" && uv sync )

if [ ! -f "$ROOT/backend/.env" ]; then
  echo "▶ Seeding backend/.env from .env.example…"
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
  echo "  ⚠ Fill in ANTHROPIC_API_KEY in backend/.env before running the app."
else
  echo "  · backend/.env already exists — leaving it untouched"
fi

# ── frontend ──────────────────────────────────────────────────────────────────

echo "▶ Installing frontend dependencies (npm install)…"
( cd "$ROOT/frontend" && npm install )

# ── infra (warm the Docker cache) ─────────────────────────────────────────────

echo "▶ Pulling infra images (Qdrant + Neo4j)…"
( cd "$ROOT/infra" && docker compose pull )

# ── next steps ────────────────────────────────────────────────────────────────

cat <<DONE

✓ Install complete.

Next steps:
  1. Edit backend/.env and set ANTHROPIC_API_KEY.
  2. Start the dev stack:  ./manage.sh start
  3. App will be at:       http://localhost:5209
     Backend docs:         http://localhost:8109/docs

DONE
