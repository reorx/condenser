# syntax=docker/dockerfile:1
#
# Build context is the `condenser/` directory itself. telememo is pulled from PyPI
# (declared in pyproject.toml, pinned in uv.lock), so no sibling `../telememo`
# checkout or parent build context is needed.

# --- Stage 1: build the React SPA -------------------------------------------
FROM node:24-alpine AS frontend
RUN npm install -g pnpm@10
WORKDIR /fe

# Resolve dependencies first so this layer is cached across source-only changes.
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build

# --- Stage 2: the Python backend (serves the SPA from CONDENSER_STATIC_DIR) --
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    CONDENSER_DB_PATH=/data/condenser.db \
    CONDENSER_ENTITY_CACHE_PATH=/data/entity_cache.json \
    CONDENSER_STATIC_DIR=/app/static \
    CONDENSER_HOST=0.0.0.0 \
    CONDENSER_PORT=8792

WORKDIR /app

# Resolve dependencies first (telememo + the rest from PyPI) so this layer is
# cached across source-only changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Then add the application code and install the project itself.
COPY condenser /app/condenser
RUN uv sync --frozen

COPY --from=frontend /fe/dist /app/static

VOLUME /data
EXPOSE 8792
CMD ["/app/.venv/bin/python", "-m", "condenser"]
