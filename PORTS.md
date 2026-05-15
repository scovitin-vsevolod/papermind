# Ports — PaperMind

> Last updated: 2026-05-15
> Project ID: 09

| Port  | Service           | Source                       | Notes                            |
|-------|-------------------|------------------------------|----------------------------------|
| 5209  | Frontend (Vite)   | frontend/vite.config.ts      | strictPort:true                  |
| 6333  | Qdrant REST       | infra/docker-compose.yml     | sole user — canonical port       |
| 6334  | Qdrant gRPC       | infra/docker-compose.yml     | sole user — canonical port       |
| 8109  | Backend (FastAPI) | scripts/dev.sh               | uvicorn --port                   |

## Reservations

None yet. If Phase 3 brings Neo4j, expect to claim **7474** (HTTP) and **7687** (Bolt) from `infra/docker-compose.yml`.
