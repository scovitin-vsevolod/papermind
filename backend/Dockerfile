# Multi-stage build for the PaperMind backend.
#
# Stage 1 (builder) — installs deps with uv into a venv we can copy to the
# slim runtime. This keeps the runtime image free of build tools (gcc,
# cargo, etc.) that some heavy deps pull in transiently.
#
# Stage 2 (runtime) — minimal: Python + the prebuilt .venv + the source.
# Final image ends up ~600 MB once sentence-transformers is in;
# alpine isn't worth the musl/torch headaches for a learning project.

# ── Builder ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Install uv. Pinning to a known-good version keeps Docker builds
# reproducible — `pip install uv` would silently pick up a new major.
COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /usr/local/bin/uv

WORKDIR /app

# Pre-copy ONLY the resolver inputs so layer caching works: dep changes
# bust the install step, source changes don't.
COPY pyproject.toml ./
# uv needs SOMETHING at the package root to run sync; ship an empty
# tree, the actual code arrives in stage 2.
RUN mkdir -p app && touch app/__init__.py

# Hatchling (our build backend) refuses to install in non-package dirs.
# `--frozen` would require a uv.lock; we don't ship one yet so use
# default resolve. `--no-dev` skips pytest, ruff, fpdf2, python-docx.
RUN uv sync --no-dev

# ── Runtime ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user — minor defence-in-depth. Numbers 1000:1000 match the
# default host UID on macOS/Linux, makes bind mounts behave when devs
# poke at logs.
RUN groupadd --gid 1000 papermind \
 && useradd --uid 1000 --gid papermind --create-home papermind

WORKDIR /app

# Copy the prebuilt venv from the builder. Symlink farm + bytecode all
# come along.
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Then the actual source. Doing it AFTER the venv means a code-only
# change rebuilds just this thin layer.
COPY app ./app

USER papermind

EXPOSE 8109

# uvicorn directly — no shell wrapper. Two workers is a sensible
# starting point for Fly.io's small machines; the document ingest
# is mostly I/O bound (Qdrant + Claude calls) so workers help.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8109", \
     "--workers", "2"]
