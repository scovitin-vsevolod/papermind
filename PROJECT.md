---
status: active
description: Personal research companion built on the Claude API. Upload documents (PDF, DOCX, MD, TXT, HTML, …), ask questions grounded in their content with citations, compare Claude vs GPT-4 side-by-side, and visualise the entities extracted from your corpus as a force-directed knowledge g…
goal: 

stack:
  - Anthropic SDK
  - Docker
  - Docker Compose
  - FastAPI
  - Neo4j
  - Node.js
  - OpenAI SDK
  - Python
  - Qdrant
  - React
  - SQLAlchemy
  - Tailwind
  - TypeScript
  - Vite
  - sentence-transformers
  - uv

ports:
  - 5209  # frontend/vite.config
  - 6333  # infra/docker-compose
  - 6334  # infra/docker-compose
  - 7687  # infra/docker-compose
  - 8109  # frontend/vite.config

links:
  repo: https://github.com/scovitin-vsevolod/papermind

env:
  - ANTHROPIC_API_KEY
  - CLAUDE_MODEL
  - DATABASE_URL
  - EMBEDDING_MODEL
  - EMBEDDING_PROVIDER
  - JWT_SECRET
  - JWT_SESSION_DAYS
  - NEO4J_PASSWORD
  - NEO4J_URI
  - NEO4J_USER
  - OPENAI_API_KEY
  - OPENAI_MODEL
  - QDRANT_COLLECTION
  - QDRANT_URL
  - VOYAGE_API_KEY
  - VOYAGE_MODEL
---

Notes go here. Edit freely.
