# Condenser — Agent Overview

Self-hosted, single-user **Telegram channel aggregating reader** (Google Reader–style
timeline; source = Telegram channels). See `spec.md` for the full design and `draft.md`
for the original brief. **Backend (spec Parts A/B/C) is implemented. Frontend (Part D) is
in progress — milestone 1 done (scaffold + auth/TG-login + timeline); milestone 2 pending
(full subscription mgmt, calendar, new-content poll, media lightbox).**

## Architecture

Single Python process: FastAPI + a Telethon MTProto **user-account** client on one asyncio
loop. Shares **one SQLite file** with [telememo](../telememo) (editable path dependency).

- telememo owns `channels` / `messages` / `comments` + the `messages.is_filtered` overlay
  column (a rebuildable cache).
- condenser owns `subscriptions` / `keyword_filters` / `read_messages` / `telegram_records`
  / `tg_session` / `app_meta` (the user's assets + app state).

condenser's peewee models bind to telememo's `db` instance, so everything is one connection.
`condenser/db.py:init_db()` initializes telememo tables (+ `is_filtered`) then condenser tables.

## Key modules (`condenser/`)

| File | Role |
|---|---|
| `config.py` / `crypto.py` | env settings; Fernet session encryption + signed cookie from `CONDENSER_SECRET_KEY` |
| `db.py` | condenser tables (peewee, bound to telememo's db) + CRUD + shared `init_db` |
| `filters.py` | keyword-filter **materialization** into `messages.is_filtered` (on ingest + rule change) |
| `timeline.py` | timeline query: cursor pagination, album merge, date/channel/unread filters, read/saved markers, `days`/`new`/`unread_counts` |
| `records.py` | source-decoupled snapshots into `raw_data`, rendered without telememo tables |
| `tg.py` | `TgManager`: lifecycle (C1), step-login→encrypted storage, realtime ingest, backfill scheduling, subscription orchestration |
| `auth.py` + `routers/*` | C2 endpoints behind the app-password cookie gate |
| `app.py` / `__main__.py` | FastAPI factory + lifespan; uvicorn entry; serves a static frontend dir if present |

## Conventions & gotchas

- **Extension-column contract**: telememo write paths only touch native columns, so
  `is_filtered` survives incremental edits. Never use full-row `INSERT OR REPLACE` in telememo.
- **Filtering is materialized**, not query-time: matching happens on the write side; the
  timeline query only reads the `is_filtered` boolean. Regex is reserved for later.
- **peewee connections are thread-local**: tests close the main-thread connection between
  cases (see `tests/conftest.py`) because TestClient runs the lifespan in a portal thread.
- **Cursor + albums**: album rows share date + adjacent ids; fetch `limit + buffer`, merge by
  `grouped_id`, anchor cursor on the unit's min id, conservative `has_more` to avoid data loss.
- A **PostToolUse formatter hook** rewrites files to single-quote style on save.
- **Telegram is a user account (MTProto)** — ToS gray area; StringSession is encrypted at rest;
  fetch layer backs off on `FloodWaitError` (spec D2).

## Part A in telememo (`../telememo`, separate git repo)

`service.py` (`TelegramService` facade), `db.py` (`init_db(optional_fields=...)` + forward
columns + migration), `telegram.py` (module-level converters), `utils.py`
(`group_messages_to_display(raw_messages_map=None)`), `types.py` (`SignInResult` + `fwd_*`),
`tests/test_part_a.py`.

## Frontend (`frontend/`, spec Part D)

React 19 + Vite 6 + TS(strict) + Tailwind v4 + shadcn/ui (new-york) + TanStack Query v5 +
React Router v7, **pnpm**. Backend `app.py` auto-serves `frontend/dist` at `/` if present.

- `lib/api.ts` typed fetch client + `ApiError`; `lib/types.ts` mirrors the backend JSON.
- **Auth gate** = the `tg-status` query: 401 → AppLogin, else `status` drives TgLogin/main
  (`App.tsx`, `useTgStatus`). Global 401 handler re-runs tg-status but **must skip tg-status
  itself** or the gate refetch-loops (`lib/queryClient.ts`).
- **Scroll-past-to-read** via IntersectionObserver + debounced batch `POST /api/read` +
  optimistic cache (`useScrollToRead`); window is the scroll container (IO root = viewport).
- Timeline items carry only `channel_id` → joined to titles client-side (`useChannelLabels`).
- Dates are naive-UTC ISO → `lib/format.ts:parseDate` appends `Z`. Media: try thumbnail,
  `<img onError>` → file chip (video/file both report `media_type='document'`). entities not
  rendered (backend doesn't persist them) — plain text + autolinked URLs only.

Milestone 2 TODO: subscription mgmt actions, calendar (`/api/timeline/days`), new-content
poll (`/api/timeline/new`), media lightbox, Docker multi-stage frontend build.

## Dev

```bash
uv sync --extra dev
cp .env.example .env   # fill TELEGRAM_API_ID/HASH, CONDENSER_APP_PASSWORD, CONDENSER_SECRET_KEY
uv run pytest          # 13 backend tests, Telegram mocked
uv run python -m condenser

cd frontend && pnpm install && pnpm dev   # proxies /api -> :8000 (CONDENSER_BACKEND overrides)
pnpm build                                # -> frontend/dist (served by backend in prod)
```

## Status / known gaps

Backend endpoints (spec C2) all exist and §7 scenarios are tested, but some v1 work
remains: subscription "delete-with-messages" option (Q4), global keyword-rule API,
full channel info (`member_count`/`description`) on resolve, wiring `app_meta`, plus
SQLite WAL and realtime edit handling. Full checklist:
`kb/sessions/2026-06-09-backend-remaining-work.md` — read before picking up backend work.

## Documentation

- `kb/sessions/` — dated session summaries (history). Read the latest to catch up on recent work.
