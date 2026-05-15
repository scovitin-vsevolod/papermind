> Last updated: 2026-05-15

# Infrastructure

Local development infra only — production deploy is Phase 4 territory.

## Containers (docker-compose)

| Service | Image | Ports | Notes |
|---|---|---|---|
| Qdrant | `qdrant/qdrant:v1.12.4` | 6333 (REST + dashboard), 6334 (gRPC) | Standalone — no etcd/MinIO sidecars |

Persistent storage: named volume `qdrant_storage` (managed by Docker).
Container name: `papermind-qdrant`. Restart policy: `unless-stopped`.

## Commands

```sh
./scripts/dev.sh           # brings the stack up + waits for /readyz, then runs backend + frontend
./scripts/down.sh          # stop, keep vectors
./scripts/down.sh --wipe   # stop + delete the named volume
```

## Why Qdrant (not Milvus)

Milvus standalone needs etcd + MinIO to boot — three containers, three
failure modes. Qdrant is one container with an embedded `:memory:`
mode that's also used in the test suite. For a single-developer
project, the operational simplicity is the right trade-off.
