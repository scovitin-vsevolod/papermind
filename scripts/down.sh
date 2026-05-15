#!/usr/bin/env bash
# Stop the Qdrant container. Pass --wipe to also delete all vectors.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--wipe" ]]; then
  (cd infra && docker compose down -v)
  echo "✓ Qdrant stopped, vectors deleted."
else
  (cd infra && docker compose down)
  echo "✓ Qdrant stopped, vectors preserved."
fi
