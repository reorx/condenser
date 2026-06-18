# syntax=docker/dockerfile:1
#
# Build context is the `condenser/` directory itself. telememo is pulled from PyPI
# (declared in pyproject.toml, pinned in uv.lock), so no sibling `../telememo`
# checkout or parent build context is needed.
#
# NOTE: the React build (spec step 8) is not wired yet. When it lands, prepend a
# `node` stage that builds `frontend/` and COPY its dist into the image, then point
# CONDENSER_STATIC_DIR at it — the backend already serves a static dir if present.

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    CONDENSER_DB_PATH=/data/condenser.db \
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

VOLUME /data
EXPOSE 8792
CMD ["/app/.venv/bin/python", "-m", "condenser"]
