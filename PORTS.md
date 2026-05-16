# Ports — PaperMind

> Last updated: 2026-05-15
> Project ID: 09

| Port  | Service           | Source                       | Notes                            |
|-------|-------------------|------------------------------|----------------------------------|
| 5209  | Frontend (Vite)   | frontend/vite.config.ts      | strictPort:true                  |
| 6333  | Qdrant REST       | infra/docker-compose.yml     | sole user — canonical port       |
| 6334  | Qdrant gRPC       | infra/docker-compose.yml     | sole user — canonical port       |
| 7474  | Neo4j HTTP        | infra/docker-compose.yml     | browser UI                       |
| 7687  | Neo4j Bolt        | infra/docker-compose.yml     | Python driver protocol           |
| 8109  | Backend (FastAPI) | scripts/dev.sh               | uvicorn --port                   |

## Reservations

None.
