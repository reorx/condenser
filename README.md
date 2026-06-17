# Condenser

Self-hosted, single-user **Telegram channel aggregating reader** — a Google Reader–style
timeline where the information source is Telegram channels instead of RSS. See
[`spec.md`](./spec.md) for the full design.

This repository currently implements the **backend** (spec Parts A/B/C). The React SPA
(Part D) is not built yet.

## Architecture

A single Python process runs FastAPI and a Telethon (MTProto user-account) client on one
asyncio loop. It shares **one SQLite file** with [telememo](../telememo):

- telememo owns `channels` / `messages` / `comments` (a rebuildable cache).
- condenser owns `subscriptions` / `keyword_filters` / `read_messages` /
  `telegram_records` / `tg_session` / `app_meta`, plus the `messages.is_filtered`
  overlay column.

Keyword filtering is **materialized** into `is_filtered` on ingest and on rule change, so
the timeline query only reads a boolean. Saved records snapshot full message data into
`telegram_records.raw_data` so they render even if the telememo cache is cleared.

## Development

Requires [uv](https://docs.astral.dev/uv/) and a local `../telememo` checkout.

```bash
uv sync --extra dev          # installs condenser + editable telememo
cp .env.example .env         # fill in the values below
uv run python -m condenser   # serves http://localhost:8792
uv run pytest                # backend test suite (Telegram fully mocked)
```

### Configuration (env vars)

| Variable | Description |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | from https://my.telegram.org |
| `CONDENSER_APP_PASSWORD` | single password gating the web UI |
| `CONDENSER_SECRET_KEY` | signs the session cookie and encrypts the stored Telegram session |
| `CONDENSER_DB_PATH` | SQLite path (default `condenser.db`) |
| `CONDENSER_BACKFILL_DAYS` | days to backfill when subscribing (default `7`) |

## Deployment (Docker)

```bash
docker compose up --build    # from condenser/
```

The build context is the parent directory so the `../telememo` path dependency resolves;
arrange a workspace containing only `telememo/` and `condenser/` to keep the context small.
SQLite is persisted to the `condenser-data` volume.

## ⚠️ Risk notice (spec D2)

Condenser logs in with a **Telegram user account** over MTProto (not a bot), which is the
only way to read channel history. Automating a user account is a **ToS gray area**; for
personal self-hosted use the risk is low, but be aware:

- The exported **StringSession is equivalent to your account credentials**. It is encrypted
  at rest with a key derived from `CONDENSER_SECRET_KEY` — keep that secret safe.
- The fetch layer backs off on `FloodWaitError`; avoid subscribing to a large number of
  channels at once.
- Telegram may rate-limit or, in abusive cases, restrict accounts. Use responsibly.
