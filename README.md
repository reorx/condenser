# Condenser

Self-hosted, single-user **Telegram channel aggregating reader** — a Google Reader–style
timeline where the information source is Telegram channels instead of RSS. See
[`spec.md`](./spec.md) for the full design.

The repository contains the **backend** (spec Parts A/B/C, FastAPI + Telethon) and the
**React SPA** (Part D, in `frontend/`). In production a single Docker image serves both.

## Architecture

A single Python process runs FastAPI and a Telethon (MTProto user-account) client on one
asyncio loop. It shares **one SQLite file** with [telememo](https://pypi.org/project/telememo/):

- telememo owns `channels` / `messages` / `comments` (a rebuildable cache).
- condenser owns `subscriptions` / `keyword_filters` / `read_messages` /
  `telegram_records` / `tg_session` / `app_meta`, plus the `messages.is_filtered`
  overlay column.

Keyword filtering is **materialized** into `is_filtered` on ingest and on rule change, so
the timeline query only reads a boolean. Saved records snapshot full message data into
`telegram_records.raw_data` so they render even if the telememo cache is cleared.

## Development

Requires [uv](https://docs.astral.dev/uv/). [telememo](https://pypi.org/project/telememo/)
is pulled from PyPI, so no sibling checkout is needed for a normal install.

```bash
uv sync --extra dev          # installs condenser + deps (telememo from PyPI)
cp .env.example .env         # fill in the values below
uv run python -m condenser   # serves http://localhost:8792
uv run pytest                # backend test suite (Telegram fully mocked)
```

The frontend ([`frontend/`](./frontend)) is React 19 + Vite + Tailwind, managed with pnpm:

```bash
cd frontend
pnpm install
pnpm dev                     # dev server, proxies /api -> :8792
pnpm build                   # production build -> frontend/dist
```

The backend serves `frontend/dist` at `/` when it exists (override the location with
`CONDENSER_STATIC_DIR`), so a production deployment is a single process. To launch
backend + frontend dev servers together in tmux panes: `tmuxp load .tmuxp.yaml`.

### Co-developing telememo locally (like `npm link`)

To run condenser against a local `../telememo` checkout instead of the PyPI release —
e.g. when changing the shared DB schema — overlay an **editable install** of it:

```bash
uv pip install -e ../telememo   # link the local checkout into the venv
```

`uv run` re-syncs the venv to the lockfile on every invocation, which would silently
restore the PyPI version, so disable that sync while the link is active:

```bash
export UV_NO_SYNC=1             # for the session (or pass --no-sync to each `uv run`)
uv run uvicorn condenser.app:create_app --factory --reload \
  --reload-dir condenser --reload-dir ../telememo/telememo --port 8792
uv run pytest
```

To **unlink**, restore the locked PyPI version:

```bash
uv sync --extra dev
```

This overlay is preferred over editing `pyproject.toml` because it never risks
committing a local path dependency. (If you'd rather have a persistent link,
`uv add --editable ../telememo` works too — just don't commit the resulting
`pyproject.toml` / `uv.lock` changes.)

### Configuration (env vars)

| Variable | Description |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | from https://my.telegram.org |
| `CONDENSER_APP_PASSWORD` | single password gating the web UI |
| `CONDENSER_SECRET_KEY` | signs the session cookie and encrypts the stored Telegram session |
| `CONDENSER_DB_PATH` | SQLite path (default `condenser.db`) |
| `CONDENSER_BACKFILL_DAYS` | days to backfill when subscribing (default `7`) |
| `CONDENSER_ENTITY_CACHE_PATH` | JSON cache for forward-source names (default `condenser_entity_cache.json`) |
| `CONDENSER_STATIC_DIR` | frontend build to serve at `/` (default `frontend/dist`) |

## Deployment (Docker)

The image is a multi-stage build: a `node` stage builds the SPA (`pnpm build`), then the
Python stage installs the backend with uv and serves the SPA from `CONDENSER_STATIC_DIR`.
telememo is installed from PyPI during the build, so the build context is just the
`condenser/` directory — no sibling checkout required.

```bash
docker compose up --build    # from condenser/; builds frontend + backend in the image
```

SQLite and the entity cache are persisted to the `condenser-data` volume (`/data`).

Pushes to `master` also build and publish `ghcr.io/reorx/condenser:latest` via GitHub
Actions (`.github/workflows/deploy.yml`) and trigger a webhook-based deploy, so a server
can run the prebuilt image instead of building locally:

```yaml
services:
  condenser:
    image: ghcr.io/reorx/condenser:latest
    env_file: .env
    ports:
      - '127.0.0.1:8792:8792'
    volumes:
      - ./data:/data
    restart: unless-stopped
```

## ⚠️ Risk notice (spec D2)

Condenser logs in with a **Telegram user account** over MTProto (not a bot), which is the
only way to read channel history. Automating a user account is a **ToS gray area**; for
personal self-hosted use the risk is low, but be aware:

- The exported **StringSession is equivalent to your account credentials**. It is encrypted
  at rest with a key derived from `CONDENSER_SECRET_KEY` — keep that secret safe.
- The fetch layer backs off on `FloodWaitError`; avoid subscribing to a large number of
  channels at once.
- Telegram may rate-limit or, in abusive cases, restrict accounts. Use responsibly.
