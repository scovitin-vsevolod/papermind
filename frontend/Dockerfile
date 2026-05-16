# Multi-stage: Node builds the static bundle, nginx serves it.
# Final image is ~50 MB — most of that is nginx + alpine base, plus
# the gzipped JS/CSS that Vite spat out. No Node in production.

# ── Builder ──────────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

# Lock-file copy first so deps are cached separately from source changes.
COPY package.json package-lock.json ./

# `npm ci` (not `install`) — strict, lockfile-driven, refuses if
# package.json drifted from the lock. Same command CI uses.
RUN npm ci

# Source — touched files invalidate just this layer + the build.
COPY . .

# Vite outputs to dist/. `tsc -b` runs first thanks to the package
# script chain, so a type error fails the docker build loudly.
RUN npm run build

# ── Runtime ──────────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Custom nginx config: serve static files, fall through to index.html
# for any unknown path (SPA history-API support), proxy /api/* to the
# backend so the frontend can keep its same-origin assumption from dev.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx:alpine's default CMD already runs nginx in the foreground.
