# Deploy to Fly.io

This is the Phase 4 deployment recipe. PaperMind isn't on the public
internet yet — this doc is the step-by-step that gets it there.

> **Cost note.** A single-user deployment on Fly.io's smallest paid
> machines runs roughly **$3–8 / month** when idle (auto-stop kicks
> in). Heavy use during a single day can easily double that. The free
> tier is gone as of 2024; everything below assumes a paid account.

## What gets deployed

Four Fly apps in one organisation:

| App | Purpose | Volume |
|---|---|---|
| `papermind-backend` | FastAPI + uvicorn | 1 GB SQLite |
| `papermind-frontend` | nginx serving Vite bundle + proxying `/api/*` | none |
| `papermind-qdrant` | Vector DB | 10 GB |
| `papermind-neo4j` | Knowledge graph | 10 GB |

Backend and frontend live in this repo's `backend/` and `frontend/`
dirs and have their own `fly.toml`. The two databases run as
single-container Fly apps using upstream images — neither needs a
custom Dockerfile.

## One-time setup

```bash
# 1. Install flyctl + log in once
brew install flyctl
fly auth login

# 2. Pick a unique app prefix. Fly app names are globally unique;
#    "papermind-*" is almost certainly taken — use your handle.
export PM=papermind-yourname  # used below
```

## Databases first (so the backend has somewhere to write)

### Qdrant

```bash
fly apps create "${PM}-qdrant"
fly volumes create qdrant_data --size 10 --app "${PM}-qdrant" --region ams
fly deploy --app "${PM}-qdrant" --image qdrant/qdrant:v1.12.4 \
  --vm-memory 1024 \
  --internal-port 6333
```

### Neo4j

```bash
fly apps create "${PM}-neo4j"
fly volumes create neo4j_data --size 10 --app "${PM}-neo4j" --region ams
fly secrets set NEO4J_AUTH="neo4j/$(openssl rand -hex 16)" --app "${PM}-neo4j"
fly deploy --app "${PM}-neo4j" --image neo4j:5.24-community \
  --vm-memory 2048 \
  --internal-port 7687

# Grab the password you just set — you'll feed it to the backend below.
fly secrets list --app "${PM}-neo4j"  # value isn't shown; check your shell history
```

## Backend

```bash
cd backend

# 1. Edit fly.toml: change `app = "papermind-backend"` to ${PM}-backend
#    and update the *.internal hostnames to point at the database apps:
#      QDRANT_URL = "http://${PM}-qdrant.internal:6333"
#      NEO4J_URI = "bolt://${PM}-neo4j.internal:7687"
#    (Fly's internal DNS resolves `<app>.internal` within the same org.)

fly apps create "${PM}-backend"
fly volumes create papermind_data --size 1 --app "${PM}-backend" --region ams

# 2. Set the real secrets. NEVER commit these.
fly secrets set \
  ANTHROPIC_API_KEY="sk-ant-..." \
  OPENAI_API_KEY="sk-..." \
  VOYAGE_API_KEY="..." \
  NEO4J_PASSWORD="<the password from the neo4j step>" \
  --app "${PM}-backend"

# 3. Deploy. First build pushes ~5 GB of layers — coffee break.
fly deploy --app "${PM}-backend"

# 4. JWT secret for the session cookie. MUST be set in prod — the
#    default in config.py is intentionally a placeholder.
fly secrets set JWT_SECRET="$(openssl rand -hex 32)" --app "${PM}-backend"

# 5. Smoke test
curl https://${PM}-backend.fly.dev/health
```

## Create the first user (one-time)

PaperMind has no public signup — login is gated on a user row that
must exist before anyone can use the app. Create it with the CLI:

```bash
# Interactive (prompts for email + password):
fly ssh console --app "${PM}-backend" \
  --command "uv run python -m app.cli.create_user"

# Or non-interactive (handy for scripts / first deploy):
fly ssh console --app "${PM}-backend" --command \
  "PAPERMIND_EMAIL=you@example.com PAPERMIND_PASSWORD='your-strong-pass' \
   uv run python -m app.cli.create_user --non-interactive"
```

Re-run any time to add another user. The CLI refuses to overwrite an
existing email — change the password by deleting and recreating the
row (`sqlite3 papermind.db "DELETE FROM users WHERE email='…';"`).

## Frontend

The frontend's `nginx.conf` has `proxy_pass http://backend:8109` hard-
coded for docker-compose. Before the first prod deploy, change it to
the backend's Fly internal hostname:

```nginx
proxy_pass http://${PM}-backend.internal:8109;
```

Then:

```bash
cd ../frontend
fly apps create "${PM}-frontend"
# Edit fly.toml: app = "${PM}-frontend"
fly deploy --app "${PM}-frontend"
```

Visit `https://${PM}-frontend.fly.dev` — that's the live UI.

## Day-to-day after the first deploy

```bash
# Push a backend change
fly deploy --app "${PM}-backend"

# Roll back if a deploy broke prod
fly releases --app "${PM}-backend"
fly deploy --app "${PM}-backend" --image registry.fly.io/${PM}-backend:deployment-XXXXX

# Tail logs while debugging
fly logs --app "${PM}-backend"

# Open a shell on the running machine (handy for one-off SQLite queries)
fly ssh console --app "${PM}-backend"
```

## Things this deploy doesn't yet do

- **No HTTPS frontend → backend isolation.** The frontend nginx proxies
  `/api/*` over plain HTTP using Fly's internal network. That's fine
  within Fly (private) but means TLS terminates at the frontend.
- **No background workers.** Document ingestion is synchronous inside
  the upload request — fine for single-user use, would need a queue
  (Celery, RQ, Fly Machines) for multi-user.
- **Auth is single-tenant by design.** Phase 6 added password login
  with a server-side CLI as the only user-creation path — see the
  "Create the first user" section above. No public `/register`, no
  password reset flow. If you forget your password, SSH in and
  recreate the row.
- **No backups.** SQLite + Qdrant + Neo4j volumes survive deploys but
  not data loss. `fly ssh console` + `sqlite3 .backup` is a manual
  start; long-term, schedule snapshot exports somewhere off-platform.
