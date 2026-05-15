#!/usr/bin/env bash
#
# manage.sh — verb-based wrapper around the dev workflow.
#
# Unlike CareerAssistantAI (where everything runs in Docker), PaperMind
# is a hybrid: Qdrant in a container, backend (uvicorn) and frontend
# (Vite) as foreground processes. This script keeps the verbs familiar
# but adapts to the hybrid model.
#
# Usage:
#   ./manage.sh start    — same as ./scripts/dev.sh (foreground; logs in terminal)
#   ./manage.sh stop     — kill backend + frontend on the project's ports; Qdrant stays
#   ./manage.sh down     — stop + tear Qdrant down (pass --wipe to also delete vectors)
#   ./manage.sh restart  — stop + start (foreground)
#   ./manage.sh status   — show what's listening on each port + Qdrant health
#   ./manage.sh logs     — short note (we don't background-log; foreground prints them)

set -euo pipefail
cd "$(dirname "$0")"

# Project ports (kept in sync with PORTS.md).
FRONTEND_PORT=5209
BACKEND_PORT=8109
QDRANT_PORT=6333

kill_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti ":$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    echo "  ✓ killed PID(s) on :$port ($pids)"
  else
    echo "  · :$port already free"
  fi
}

status_port() {
  local port="$1" label="$2"
  local pid
  pid=$(lsof -ti ":$port" 2>/dev/null | head -1 || true)
  if [[ -n "$pid" ]]; then
    local cmd
    cmd=$(ps -p "$pid" -o command= 2>/dev/null | cut -c1-70)
    printf "  :%-5s %-10s PID %-6s %s\n" "$port" "$label" "$pid" "$cmd"
  else
    printf "  :%-5s %-10s (free)\n" "$port" "$label"
  fi
}

case "${1:-}" in
  start)
    exec ./scripts/dev.sh
    ;;

  stop)
    echo "▶ Stopping foreground dev servers…"
    kill_port "$BACKEND_PORT"
    kill_port "$FRONTEND_PORT"
    echo "  Qdrant left running — use './manage.sh down' to stop it too."
    ;;

  down)
    "$0" stop
    ./scripts/down.sh "${@:2}"
    ;;

  restart)
    "$0" stop
    sleep 1
    exec ./scripts/dev.sh
    ;;

  reset-db)
    # Phase 1 uses SQLAlchemy create_all() instead of Alembic — it only
    # creates new tables, it doesn't migrate dropped/renamed columns. When
    # the model schema changes during development the SQLite file ends up
    # out of sync (NOT NULL constraint failures, etc.). Cleanest fix:
    # delete the file and let create_all() rebuild from the current model.
    # Optionally wipe Qdrant too so orphan vectors don't linger.
    echo "▶ Removing backend/papermind.db…"
    rm -f backend/papermind.db backend/papermind.db-journal
    echo "  ✓ SQLite file removed."
    if [[ "${2:-}" == "--wipe-vectors" ]]; then
      echo "▶ Wiping Qdrant volume too…"
      ./scripts/down.sh --wipe
      echo "  ✓ Qdrant volume wiped."
    else
      echo "  ℹ Qdrant left as-is. Pass '--wipe-vectors' to also drop vectors:"
      echo "    ./manage.sh reset-db --wipe-vectors"
    fi
    echo "  Run './manage.sh start' to recreate the schema on the next boot."
    ;;

  status)
    echo "── Listening ports ──"
    status_port "$FRONTEND_PORT" "frontend"
    status_port "$BACKEND_PORT"  "backend"
    status_port "$QDRANT_PORT"   "qdrant"
    echo
    echo "── Qdrant readyz ──"
    if curl -fs --max-time 2 "http://localhost:${QDRANT_PORT}/readyz" >/dev/null 2>&1; then
      echo "  ✓ ok"
    else
      echo "  ✗ not responding"
    fi
    ;;

  logs)
    cat <<HINT
PaperMind runs backend and frontend in the foreground — their logs are
printed live in the terminal that launched 'start'. There's no separate
log file to tail.

For Qdrant container logs:
  docker logs -f papermind-qdrant
HINT
    ;;

  *)
    cat <<USAGE
Usage: $0 {start|stop|restart|down|reset-db|status|logs}

  start              foreground — Qdrant + backend + frontend (same as scripts/dev.sh)
  stop               kill backend + frontend by port; Qdrant keeps running
  restart            stop + start (foreground)
  down               stop + take Qdrant down (append --wipe to delete vectors)
  reset-db           delete papermind.db so create_all() rebuilds the schema
                     (append --wipe-vectors to also clear Qdrant)
  status             what's listening on $FRONTEND_PORT / $BACKEND_PORT / $QDRANT_PORT + Qdrant readyz
  logs               where to find logs
USAGE
    exit 1
    ;;
esac
