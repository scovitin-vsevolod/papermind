#!/usr/bin/env bash
# scripts/deploy.sh — runs ON THE SERVER, invoked from GitHub Actions over SSH.
#
# This script lives in the repo (so it's reviewable + versioned), but it's
# meant to be executed on the EC2 box: GH Actions logs in, runs
# `cd /var/www/pm && bash scripts/deploy.sh`.
#
# What it does (in order):
#   1. Pull the latest main into /var/www/pm (hard reset — server has no
#      business carrying local edits; any drift is overwritten).
#   2. uv sync — installs/updates backend dependencies (prod only, no dev).
#   3. Run Base.metadata.create_all() so new tables (Phase 6's `users`)
#      come into existence on a fresh server without Alembic.
#   4. npm ci + vite build for the frontend; nginx serves the rebuilt
#      `frontend/dist/` from disk so no nginx reload is needed.
#   5. systemctl restart papermind-backend (reads the new code + .env).
#   6. Smoke-test /health — fail the deploy if the backend doesn't come up.
#
# Failure handling: `set -euo pipefail` aborts on the first non-zero exit,
# so a failing pytest in CI never gets here, and a failing step here makes
# the GH Actions job red — easy to spot in the Actions tab.
#
# Idempotency: every step is safe to re-run. Re-deploying the same commit
# is a no-op (git fetch is mostly cached, uv sync sees no diffs, npm ci is
# a no-op when the lockfile is unchanged) — useful for "did it actually
# pick up?" sanity checks.

set -euo pipefail

PROJECT_DIR="/var/www/pm"
BACKEND_PORT=8109
SERVICE="papermind-backend"

cd "$PROJECT_DIR"

echo "── 1. git: fetch + reset to origin/main ────────────────────────────"
# --depth=1 keeps the on-disk .git tiny — we never need history on prod,
# and disk is 80% full already (server-audit).
git fetch --depth=1 origin main
git reset --hard origin/main
echo "  now at: $(git log -1 --oneline)"
echo

echo "── 2. backend deps (uv sync, prod only) ────────────────────────────"
cd "$PROJECT_DIR/backend"
# No --extra dev → skips pytest/ruff/coverage/etc. Smaller venv on disk.
uv sync
echo

echo "── 3. db schema (create_all — handles Phase 6 users table) ─────────"
# Phase 1 chose SQLAlchemy create_all() over Alembic — fine for a
# single-tenant app where the schema only grows. create_all is idempotent:
# existing tables stay, new ones (like Phase 6's `users`) get created.
# This step is a no-op once the schema is up to date.
uv run python -c "from app.db import Base, engine; Base.metadata.create_all(engine)"
echo "  ✓ schema ensured"
echo

echo "── 4. frontend build (npm ci + vite build) ─────────────────────────"
cd "$PROJECT_DIR/frontend"
# `ci` (not `install`) — strict against package-lock, fails on drift.
# Matches the CI workflow and what's documented in CLAUDE.md.
npm ci
npm run build
echo "  ✓ frontend/dist regenerated"
echo

echo "── 5. restart backend service ──────────────────────────────────────"
# sudoers gives ec2-user NOPASSWD: ALL (per server audit). For tighter
# blast radius we can later restrict to a single command, but for now
# this is the simplest thing that works.
sudo systemctl restart "$SERVICE"
echo "  ✓ $SERVICE restarted"
echo

echo "── 6. smoke test /health ───────────────────────────────────────────"
# Give uvicorn a moment to bind. With cold model loading (sentence-
# transformers) the first /health after restart can be slow, so we
# retry up to 10 times with a 2s gap.
for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS --max-time 5 "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null; then
        echo "  ✓ /health OK after ${i} attempt(s)"
        break
    fi
    if [[ $i -eq 10 ]]; then
        echo "  ✗ /health failed after 10 attempts" >&2
        echo "  --- last ${SERVICE} logs:" >&2
        sudo journalctl -u "$SERVICE" -n 30 --no-pager >&2 || true
        exit 1
    fi
    sleep 2
done

echo
echo "✓ deploy complete: $(git log -1 --format='%h %s')"
