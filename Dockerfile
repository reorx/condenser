# syntax=docker/dockerfile:1
#
# Build context must be a directory that contains BOTH `telememo/` and `condenser/`
# (condenser depends on telememo via the `../telememo` path source). With docker
# compose this is set via `build.context: ..` (see docker-compose.yml).
#
# NOTE: the React build (spec step 8) is not wired yet. When it lands, prepend a
# `node` stage that builds `frontend/` and COPY its dist into the image, then point
# CONDENSER_STATIC_DIR at it — the backend already serves a static dir if present.

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    CONDENSER_DB_PATH=/data/condenser.db \
    CONDENSER_HOST=0.0.0.0 \
    CONDENSER_PORT=8792

WORKDIR /app
COPY telememo /app/telememo
COPY condenser /app/condenser

WORKDIR /app/condenser
RUN uv sync --frozen

VOLUME /data
EXPOSE 8792
CMD ["/app/condenser/.venv/bin/python", "-m", "condenser"]
