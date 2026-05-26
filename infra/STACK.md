> Last updated: 2026-05-26

# Infrastructure

Local development infra only — production deploy is Phase 4 territory
(AWS, service TBD).

## Containers (docker-compose)

| Service | Image | Ports | Notes |
|---|---|---|---|
| Qdrant | `qdrant/qdrant:v1.12.4` | 6333 (REST + dashboard), 6334 (gRPC) | Standalone — no etcd/MinIO sidecars |
| Neo4j  | `neo4j:5.24-community`  | 7474 (HTTP browser), 7687 (Bolt)    | Single-node knowledge graph; default auth `neo4j/papermind-dev` |

Persistent storage (named volumes managed by Docker):
- `qdrant_storage` → `/qdrant/storage`
- `neo4j_data` → `/data`, `neo4j_logs` → `/logs`

Container names: `papermind-qdrant`, `papermind-neo4j`. Restart policy:
`unless-stopped` on both.

Neo4j memory settings (tuned for larger graphs without blowing up):
heap 512m → 1g, page cache 512m.

## Commands

```sh
./scripts/dev.sh           # bring stack up + wait for /readyz, then run backend + frontend
./scripts/down.sh          # stop, keep vectors + graph
./scripts/down.sh --wipe   # stop + delete the named volumes
```

## Why Qdrant (not Milvus)

Milvus standalone needs etcd + MinIO to boot — three containers, three
failure modes. Qdrant is one container with an embedded `:memory:`
mode that's also used in the test suite. For a single-developer
project, the operational simplicity is the right trade-off.
