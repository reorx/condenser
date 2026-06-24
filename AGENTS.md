# Condenser — Agent Overview

Self-hosted, single-user **Telegram channel aggregating reader** (Google Reader–style
timeline; source = Telegram channels). See `spec.md` for the full design and `draft.md`
for the original brief. **Backend (spec Parts A/B/C) is implemented. Frontend (Part D)
milestones 1 & 2 are done** — scaffold + auth/TG-login + timeline, plus full subscription
management, calendar date-filter, new-content polling, media lightbox, settings + theme,
channel avatars, a dedicated `/filters` page (global + per-channel keyword rules
with Gmail-style preview), a redesigned reading view (unified `PageHeader`, static
date dividers, bordered content column), and unified link previews (own URL-metadata
fetcher + click-to-open pane). Remaining v1 work: Docker multi-stage frontend
build + README.

## Architecture

Single Python process: FastAPI + a Telethon MTProto **user-account** client on one asyncio
loop. Shares **one SQLite file** with [telememo](https://pypi.org/project/telememo/)
(a **PyPI dependency**; co-develop a local `../telememo` checkout via an editable overlay
— see the README "Co-developing telememo locally" section).

- telememo owns `channels` / `messages` / `comments` + the `messages.is_filtered` overlay
  column (a rebuildable cache). `messages.media_width` / `media_height` are telememo-native
  (filled on ingest via `message.file.width/height`, used by the frontend to reserve image
  placeholder space; NULL on historical rows pre-2026-06-18).
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
| `preview.py` | source-agnostic link previews: fetch a URL (async httpx) + extract metadata (`metadata_parser`), `link_previews` cache, per-message batch w/ Telegram-bonus fill, image fetch for the proxy |
| `tg.py` | `TgManager`: lifecycle (C1), step-login→encrypted storage, realtime ingest, backfill scheduling, subscription orchestration |
| `auth.py` + `routers/*` | C2 endpoints behind the app-password cookie gate; `routers/channels.py` = avatar proxy, `routers/preview.py` = link-preview + image proxy; `/api/tg/status` carries `phone` |
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
- **Telethon `StringSession` does NOT persist its entity cache** (only auth_key + DC). After a
  restart, `client.get_entity(int)` for a peer Telethon hasn't met yet in the current process
  fails with `Could not find input entity for PeerUser`. Always prefer `@username` over a bare
  id when one is available — see `tg.py:_channel_handle`. The media + avatar proxies
  (`routers/media.py`, `routers/channels.py`) route through it too (since 2026-06-24) so image
  thumbnails and avatars survive restarts. Private channels (no username) fall through to the
  int, but `TgManager._warm_entity_cache` (spawned in `startup`) iterates dialogs once on boot
  to re-register every joined peer's access_hash, so the bare-id fallback resolves them for the
  process lifetime. Persisting access_hash ourselves is the remaining durable alternative.
- **Forward source names** (`fwd_from_channel_name` / `fwd_from_user_name`) are filled on
  ingest by a three-tier cascade: (1) `message.forward.chat.title` / `forward.sender` —
  Telethon-resolved entities, no API call; (2) persistent `EntityNameCache` JSON file at
  `CONDENSER_ENTITY_CACHE_PATH`; (3) `await client.get_entity(id)` — backfill path only.
  Realtime ingest passes `allow_network=False` so the event handler never blocks on Telegram
  or risks FloodWait crashes. Backfill (`_iter_backfill`) passes True; outer FloodWait retry
  covers it. Wired in `telememo/telegram.py:resolve_forward_entity_names`.

## Part A in telememo (`../telememo`, separate git repo)

`service.py` (`TelegramService` facade; accepts `entity_cache=`), `db.py`
(`init_db(optional_fields=...)` + forward columns + migration), `telegram.py` (module-level
converters + `async resolve_forward_entity_names(md, client, cache, allow_network)`),
`utils.py` (`group_messages_to_display(raw_messages_map=None)`, `extract_forward_info` reads
`message.forward.chat`/`sender`), `entity_cache.py` (`EntityNameCache` JSON-backed
id→name map), `types.py` (`SignInResult` + `fwd_*`), `tests/test_part_a.py`,
`tests/test_forward_resolver.py`.

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
- **Reading-view shell**: `PageHeader` (`components/PageHeader.tsx`) is the unified top bar for
  TimelineView + RecordsView — leading icon (`ChannelAvatar` for a channel, `IconBadge`-wrapped
  lucide for All/Unread/Saved) + title + unread-count line on the left, icon-only actions
  (native `title` tooltips, not shadcn Tooltip — avoids Radix `asChild` nesting on Popover
  triggers) pinned right. The timeline `useInfiniteQuery` lives in `useTimeline` (lifted to
  TimelineView) so the header can build the channel-filter control from loaded items;
  `useChannelFilter` is owned by TimelineView and `Timeline` is presentational (props:
  `query`/`items`/`visible`/`onClearFilter`/`emptyLabel`). Unread count = `sub.unread` (channel)
  or sum over enabled subs (All/Unread); **total message count is not exposed by the backend**.
- **Date dividers, not a sticky bar**: `Timeline` renders a static left-aligned day label
  between day groups (no floating `sticky` header). The channel filter moved into `PageHeader`
  (multi-channel views only). Content column has desktop-only `md:border-x` (`AppShell`).
  Caveat: do NOT add the whole `query` object to the infinite-scroll `useEffect` deps — it's a
  new ref every render and rebuilds the IntersectionObserver each time; list only the fields used.
- Dates are UTC (Telegram native); `lib/format.ts:parseDate` handles both tz-aware (`+00:00`)
  and naive forms (appends `Z`). Day grouping/calendar use the UTC day key. Media: try
  thumbnail, `<img onError>` → file chip (video/file both report `media_type='document'`);
  thumbnails open `Lightbox`. entities not rendered (backend doesn't persist them).
- **Media skeleton + aspect-ratio transition**: `MessageMedia` `Thumb` reserves space with
  inline `style={{ aspectRatio }}` (API `width/height` → exact; else 4/3 single / 1/1 grid),
  shows `<Skeleton />` (in `components/ui/skeleton.tsx`) until `<img>.onLoad`, then fades the
  image in via `opacity` and — for single images without API dimensions — overwrites the
  aspect with `naturalWidth/naturalHeight`. `lockAspect` keeps multi-grid cells square.
  WebPagePreview thumbs use the same skeleton+fade pattern (fixed-size, no aspect change).
- **Forwarded messages**: `MessageCard` renders `↪ Forwarded` above the box, source name
  (`from_channel_name` → `from_user_name` → `post_author`) as the first line inside the
  box. The box is a rounded, soft-bg card (`rounded-lg border bg-muted/30 p-3`) indented
  `ml-8` (2rem); the "Forwarded" label stays outside the indent. `forwardSourceName(msg)`
  returns the name or null; null means just show "Forwarded" with no name line (private
  source / cache miss / unresolvable peer). The save/bookmark icon is **always visible**
  (no longer hover-only); amber when saved. Cards have `px-4 sm:px-5` inset.
- **Optimistic mutation pattern** (M1+M2): timeline-wide via `setQueriesData({queryKey:['timeline']})`,
  subscriptions via `setQueryData(['subscriptions'])`. Keyword CRUD invalidates `['filters-all']`
  + `['timeline']` + `['subscriptions']` (backend recomputes `is_filtered`). Errors surface via `sonner` toasts
  (`api.errorMessage`). shadcn primitives in `components/ui/` use individual `@radix-ui/react-*`
  packages (not the unified `radix-ui`), button from `@/components/ui/button`.
- **Theme**: `lib/theme.tsx` ThemeProvider (light/dark/system, default system, localStorage
  `condenser-theme`); no-FOUC inline script in `index.html` sets the class pre-mount.
- **New-content poll**: `useNewContent` polls `/api/timeline/new?after=head_cursor` (from page-1
  `head_cursor`) every 30s, paused when hidden → floating banner → refetch + scroll-to-top.
- **Avatars**: `ChannelAvatar` hits `/api/channels/{id}/avatar`, falls back to a colored initial.
- **Link previews**: clicking a message opens `LinkPreviewPane` (shadcn `Sheet`, mounted once in
  `AppShell`, covers timeline + saved views) with previews for the message's URLs from
  `GET /api/messages/{cid}/{mid}/previews`. Whole-card click in `MessageCard`; the listener drops
  once that card's pane is open so text selects normally; offered only when the inline Telegram card
  doesn't already cover the links. `lib/extractUrls.ts` is the shared URL source (linkify + pane).
  Thumbnails proxy via `/api/preview/image` (toggle with `CONDENSER_PREVIEW_IMAGE_PROXY`), falling
  back to the media proxy for Telegram-bonus images.

Remaining: Docker multi-stage frontend build + README (spec step 9).

## Dev

```bash
uv sync --extra dev    # telememo comes from PyPI; no ../telememo checkout needed
cp .env.example .env   # fill TELEGRAM_API_ID/HASH, CONDENSER_APP_PASSWORD, CONDENSER_SECRET_KEY
uv run pytest          # 31 backend tests, Telegram mocked

# Local dev backend (auto-reload; watcher scoped to the Python sources):
uv run uvicorn condenser.app:create_app --factory --reload --reload-dir condenser --port 8792
# No-reload / prod-style run (binds 0.0.0.0): uv run python -m condenser

# Co-developing telememo (npm-link style): overlay an editable install, then keep it
# alive across `uv run` (which otherwise re-syncs to the lock and restores PyPI):
#   uv pip install -e ../telememo && export UV_NO_SYNC=1
# then add `--reload-dir ../telememo/telememo` above. Unlink with `uv sync`.

cd frontend && pnpm install && pnpm dev   # proxies /api -> :8792 (CONDENSER_BACKEND overrides)
pnpm build                                # -> frontend/dist (served by backend in prod)

# Or launch both backend + frontend panes at once: tmuxp load .tmuxp.yaml
```

## Status / known gaps

Backend endpoints (spec C2) all exist and §7 scenarios are tested, but some v1 work
remains: subscription "delete-with-messages" option (Q4), full channel info
(`member_count`/`description`) on resolve, wiring `app_meta`, plus SQLite WAL and
realtime edit handling. Full checklist:
`kb/sessions/2026-06-09-backend-remaining-work.md` — read before picking up backend work.

**Album unread count (fixed):** `unread_counts` counts display units by
`COALESCE(grouped_id, id)`, so marking only an album's primary id used to leave its sibling
rows unread and the badge stuck. `db.mark_read` now expands each pair to its album siblings
via `_expand_album_siblings` (and `mark_read_bulk` already selects every raw row), so albums
clear fully. Locked by `test_read_album_clears_unread_count` + `test_read_bulk_clears_album_unread_count`.

**`backfill_done` semantics:** since 2026-06-18, this flag means "a backfill attempt
finished", success or failure. `_backfill_channel` marks it `True` in a `finally`, so the
"backfilling…" badge clears either way. Don't repurpose the boolean to mean "succeeded" —
add a new column if errors need to be surfaced.

**Private channels + entity cache:** `_channel_handle` routes around the StringSession
entity-cache limitation by preferring `@username` — used by ingest and (since 2026-06-24) the
media + avatar proxies, so username channels survive restarts. For channels with **no** username,
`TgManager._warm_entity_cache` (spawned in `startup`, reuses the FloodWait-bounded
`list_joined_channels`) iterates dialogs once on boot to re-register every joined peer's
access_hash, so the bare-id fallback resolves for the process lifetime. Remaining durable
alternative: persist access_hash / `InputPeerChannel` ourselves (covers peers not in dialogs,
e.g. a private channel you've left but still have cached messages for).

## Documentation

- `kb/docs/content-update-mechanism.md` — Read before touching ingest/sync: realtime push,
  backfill, the manual refresh / fetch-older / reset triggers, the enable toggle, and how
  fetch-older's id-anchored cursor paging works.
- `kb/sessions/` — dated session summaries (history). Read the latest to catch up on recent work.
