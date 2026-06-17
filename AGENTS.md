# Condenser — Agent Overview

Self-hosted, single-user **Telegram channel aggregating reader** (Google Reader–style
timeline; source = Telegram channels). See `spec.md` for the full design and `draft.md`
for the original brief. **Backend (spec Parts A/B/C) is implemented. Frontend (Part D)
milestones 1 & 2 are done** — scaffold + auth/TG-login + timeline, plus full subscription
management, calendar date-filter, new-content polling, media lightbox, settings + theme,
and channel avatars. Remaining v1 work: Docker multi-stage frontend build + README.

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
| `timeline.py` | timeline query: cursor pagination (+ `head_cursor` for new-content poll), album merge, date/channel/unread filters, read/saved markers, `days`/`new`/`unread_counts` |
| `records.py` | source-decoupled snapshots into `raw_data`, rendered without telememo tables |
| `tg.py` | `TgManager`: lifecycle (C1), step-login→encrypted storage, realtime ingest, backfill scheduling, subscription orchestration |
| `auth.py` + `routers/*` | C2 endpoints behind the app-password cookie gate; `routers/channels.py` = avatar proxy; `/api/tg/status` carries `phone` |
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
- Dates are UTC (Telegram native); `lib/format.ts:parseDate` handles both tz-aware (`+00:00`)
  and naive forms (appends `Z`). Day grouping/calendar use the UTC day key. Media: try
  thumbnail, `<img onError>` → file chip (video/file both report `media_type='document'`);
  thumbnails open `Lightbox`. entities not rendered (backend doesn't persist them).
- **Optimistic mutation pattern** (M1+M2): timeline-wide via `setQueriesData({queryKey:['timeline']})`,
  subscriptions via `setQueryData(['subscriptions'])`. Keyword CRUD invalidates `['timeline']`
  + `['subscriptions']` (backend recomputes `is_filtered`). Errors surface via `sonner` toasts
  (`api.errorMessage`). shadcn primitives in `components/ui/` use individual `@radix-ui/react-*`
  packages (not the unified `radix-ui`), button from `@/components/ui/button`.
- **Theme**: `lib/theme.tsx` ThemeProvider (light/dark/system, default system, localStorage
  `condenser-theme`); no-FOUC inline script in `index.html` sets the class pre-mount.
- **New-content poll**: `useNewContent` polls `/api/timeline/new?after=head_cursor` (from page-1
  `head_cursor`) every 30s, paused when hidden → floating banner → refetch + scroll-to-top.
- **Avatars**: `ChannelAvatar` hits `/api/channels/{id}/avatar`, falls back to a colored initial.

Remaining: Docker multi-stage frontend build + README (spec step 9).

## Dev

```bash
uv sync --extra dev
cp .env.example .env   # fill TELEGRAM_API_ID/HASH, CONDENSER_APP_PASSWORD, CONDENSER_SECRET_KEY
uv run pytest          # 18 backend tests, Telegram mocked

# Local dev backend (auto-reload; watcher scoped to the Python sources + editable telememo):
uv run uvicorn condenser.app:create_app --factory --reload \
  --reload-dir condenser --reload-dir ../telememo/telememo --port 8792
# No-reload / prod-style run (binds 0.0.0.0): uv run python -m condenser

cd frontend && pnpm install && pnpm dev   # proxies /api -> :8792 (CONDENSER_BACKEND overrides)
pnpm build                                # -> frontend/dist (served by backend in prod)

# Or launch both backend + frontend panes at once: tmuxp load .tmuxp.yaml
```

## Status / known gaps

Backend endpoints (spec C2) all exist and §7 scenarios are tested, but some v1 work
remains: subscription "delete-with-messages" option (Q4), global keyword-rule API (M2
deliberately ships channel-level only), full channel info (`member_count`/`description`)
on resolve, wiring `app_meta`, plus SQLite WAL and realtime edit handling. Full checklist:
`kb/sessions/2026-06-09-backend-remaining-work.md` — read before picking up backend work.

**Known bug (album unread count):** marking an album read only inserts its primary
message id, but `timeline.unread_counts` counts by `COALESCE(grouped_id, id)` so an album's
other rows keep it counted as unread — albums never clear from the unread badge. Fix by
marking all `raw_message_ids` read or counting by display unit (see the M2 session).

## Documentation

- `kb/docs/content-update-mechanism.md` — Read before touching ingest/sync: realtime push,
  backfill, the manual refresh / fetch-older / reset triggers, the enable toggle, and how
  fetch-older's id-anchored cursor paging works.
- `kb/sessions/` — dated session summaries (history). Read the latest to catch up on recent work.
