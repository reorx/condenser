# Condenser — Agent Overview

Self-hosted, single-user **Telegram channel aggregating reader** (Google Reader–style
timeline; source = Telegram channels). See `spec.md` for the full design and `draft.md`
for the original brief. **Backend (spec Parts A/B/C) is implemented. Frontend (Part D)
milestones 1 & 2 are done** — scaffold + auth/TG-login + timeline, plus full subscription
management, calendar date-filter, new-content polling, media lightbox, settings + theme,
channel avatars, a dedicated `/filters` page (global + per-channel keyword rules
with Gmail-style preview), a redesigned reading view (unified `PageHeader`, static
date dividers, bordered content column), and unified link previews (own URL-metadata
fetcher + click-to-open pane). **v1 is shipped**: multi-stage Docker build (frontend +
backend in one image), README, GitHub Actions → ghcr.io/reorx/condenser → webhook deploy
to https://condenser.reorx.com (Ansible role `condenser` in the deploy workspace, host
port 3459, SQLite bind-mounted at `/opt/apps/condenser/data/`).

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
  / `tg_session` / `app_meta` / `hn_stories` (the user's assets + app state).
  `subscriptions` is **multi-source since SCHEMA_VERSION 3** (2026-07-19): composite PK
  `(source, channel_id)`, `channel_id` is a `BareField` (TG rows store int, HN rows a feed
  key str — v1 only `'front'`), plus `name` / `config` columns; a shape-based migration in
  `db.init_db` rebuilds pre-v3 tables. All TG CRUD + timeline JOINs scope `source='telegram'`.

condenser's peewee models bind to telememo's `db` instance, so everything is one connection.
`condenser/db.py:init_db()` initializes telememo tables (+ `is_filtered`) then condenser tables.

## Key modules (`condenser/`)

| File | Role |
|---|---|
| `config.py` / `crypto.py` | env settings; Fernet session encryption + signed cookie from `CONDENSER_SECRET_KEY` |
| `db.py` | condenser tables (peewee, bound to telememo's db) + CRUD + shared `init_db` |
| `filters.py` | keyword-filter **materialization** into `messages.is_filtered` (on ingest + rule change) |
| `timeline.py` | timeline query: cursor pagination (+ `head_cursor` for new-content poll, + `end_cursor` — last-unit anchor present even when `next_cursor` is null, lets iOS resume paging after fetch-older), album merge, date/channel/unread filters, read/saved markers, `days`/`new`/`unread_counts` |
| `records.py` | source-decoupled snapshots into `raw_data`, rendered without telememo tables |
| `preview.py` | source-agnostic link previews: fetch a URL (async httpx) + extract metadata (`metadata_parser`), `link_previews` cache, per-message batch w/ Telegram-bonus fill, image fetch for the proxy |
| `hn.py` | `HNManager` (on `app.state.hn`, peer of `TgManager`): subscription-driven HN front-page sampling loop (`topstories` diff → `hn_stories`, sticky `first_seen_at`, peak_rank, 48h snapshot refresh) + serial rate-limited hckrnews history backfill w/ pending-day set in `app_meta` (`threading.Lock` + per-day read-modify-write — `schedule_backfill` runs on the threadpool while the loop rewrites the set); HTTP via injectable `fetch_json` (tests need no network). Hardened per `kb/plans/2026-07-19-hn-phase1-review-fixes.md`: `_loop` has a catch-all guard (DB errors outside `poll_once`'s try must not kill the task); **null item ≠ dead** — refresh only marks dead on explicit `dead`/`deleted` (Firebase transiently nulls live items), while a *never-seen* front-page id that fetches null gets a dead placeholder row so it isn't re-pulled every round; `kick()` marshals via `call_soon_threadsafe` (no-op before startup / when source disabled). `routers/hn.py` = `/api/sources/hn/subscriptions*` + `/api/hn/status` (incl. `source_enabled`); POST = subscribe-and-enable (re-enables a paused row, `schedule_backfill` only on first create), POST/PATCH-enable → 503 when `CONDENSER_HN_ENABLED=false`. Multi-source plan Phase 1: `kb/plans/2026-07-19-multi-source-hn.md` |
| `tg.py` | `TgManager`: lifecycle (C1), step-login→encrypted storage, realtime ingest, backfill scheduling, subscription orchestration |
| `auth.py` + `routers/*` | C2 endpoints behind `require_auth` = app-password cookie **or** device Bearer token (`devices` table, sha256 hash only, issued via the web `/authorize` page for the iOS app; management endpoints are cookie-only — see `kb/plans/2026-07-16-mobile-client-api-device-token.md`); `routers/channels.py` = avatar proxy, `routers/preview.py` = link-preview + image proxy; `/api/tg/status` carries `phone` |
| `app.py` / `__main__.py` | FastAPI factory + lifespan; uvicorn entry; serves a static frontend dir if present via `SPAStaticFiles` (index.html fallback for client routes — `/authorize` cold-load depends on it; unknown `/api/*` still 404) |

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

`service.py` (`TelegramService` facade; accepts `entity_cache=`; `subscribe` registers one
handler for **both** `NewMessage` and `MessageEdited` since 0.2.0, so edits update stored
text + re-dispatch), `db.py` (`init_db(optional_fields=...)` + forward columns + migration;
`save_message_smart` updates a row in place when `edit_date` changed), `telegram.py`
(module-level converters + `async resolve_forward_entity_names(md, client, cache, allow_network)`),
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
- **Link previews**: clicking a message's **time** opens `LinkPreviewPane` (shadcn `Sheet`, mounted
  once in `AppShell`, covers timeline + saved views) with previews for the message's URLs from
  `GET /api/messages/{cid}/{mid}/previews` + a pinned "Open original in Telegram" footer link
  (`tgMessageUrl`). The entry exists on **every** message (no whole-card click / previewable-links
  gate anymore). `lib/extractUrls.ts` is the shared URL source (linkify + pane).
  Thumbnails proxy via `/api/preview/image` (toggle with `CONDENSER_PREVIEW_IMAGE_PROXY`), falling
  back to the media proxy for Telegram-bonus images.

Remaining: Docker multi-stage frontend build + README (spec step 9).

## iOS app (`ios/`, monorepo)

Native SwiftUI read-only client (spec: `kb/plans/2026-07-16-ios-reader-app.md`; device-token
auth spec: `kb/plans/2026-07-16-mobile-client-api-device-token.md`). Pure-CLI workflow —
xcodegen `project.yml` (single source of truth, `.xcodeproj` gitignored) + Makefile
(`make build / test / run / gen / clean`, simulator via `simctl`). Two layers:
`CondenserKit/` local SPM package (pure logic + Swift Testing tests, no UIKit) and
`Condenser/` app target. See `ios/AGENTS.md` for commands and conventions.
Phases 1 (skeleton) + 2 (auth: `AuthFlow`/`TokenStore` in Kit, `AuthSession` + `LoginView`
via SwiftUI `webAuthenticationSession`) + 3 (core reading: Models mirrored from
`frontend/src/lib/types.ts` with real-JSON fixtures, `APIClient` (Bearer, 401 →
`APIError.unauthorized`), `CondenserAPI` protocol for test stubs, `TimelineStore` /
`ReadReporter` / `NewContentPoller` in Kit; app side: `ReaderSession` composition
root wiring 401 → `AuthSession.handleUnauthorized`, `TimelineScreen` with scroll-to-read via
`onGeometryChange`, infinite scroll, pull-to-refresh, new-content capsule, unread toggle,
`MessageCard` / `MessageDetailSheet` / authed `ImageLoader`; debug-token env injection for
simulator, see `ios/AGENTS.md`) + 4 (three-tab `TabView`: Timeline / channels / saved —
`MessageListView` extracted as the reusable list core, `ChannelsScreen` +
`ChannelTimelineScreen` (per-channel `TimelineStore`, no snapshot/poller), `SavedScreen` on
`RecordsStore` (optimistic unsave + positional rollback; records are self-contained via
`message.channel`), `SnapshotCache` (Caches-dir JSON; timeline page 1 + subscriptions render
before network on cold start), fullscreen `ImageViewerScreen` (paged album swipe, UIScrollView
pinch/double-tap zoom, drag-down dismiss), `SettingsScreen` (server/device name, sign-out),
`TokenStore.deviceName`; 79 Kit tests; DEBUG deep-link walkthrough via
`SIMCTL_CHILD_CONDENSER_DEBUG_ROUTE`, see `ios/AGENTS.md`) done. Reading-experience polish
(2026-07-18): default view is **unread** (eye / eye.slash toolbar toggle; both modes snapshot-
cached), Settings is a 4th tab (screen no longer wraps its own NavigationStack), nav + tab bars
auto-hide on scroll-down / reappear on scroll-up (`AutoHideBars` on the ScrollView; decision
logic lives in Kit's `BarsVisibilityModel` — bar toggles change safe-area insets which feed
back into scroll geometry, so direction detection runs only during user scroll phases plus a
post-toggle cooldown, else it self-oscillates into a main-thread relayout freeze), card links
+ photos + webpage cards are directly tappable (shared
`linkified` in `Linkify.swift`, list-level `openURL` env → in-app Safari, photo tap → fullscreen
viewer), 5-line truncated text shows a blue "more" (hidden measuring copy), photo thumbs render
in fixed aspect boxes (`Color.clear.aspectRatio` + overlay + clip — fixes album grid overflow;
tall single photos clamp to 3:4), and `MessageListView.refresh` flushes the ReadReporter queue
first so pull-to-refresh in unread mode actually drops just-read items. Settings has a 4-step
**font-size slider** (小/正常/略大/大 + live mock-card preview): Kit's `FontScale` enum
(ordered presets, stored-value fallback, slider-index clamp) maps to a fixed `DynamicTypeSize`
(small/large/xLarge/xxLarge — overrides system Dynamic Type on reading surfaces only) via
`.readingFontScale()` in `ReadingFontScale.swift`, persisted through
`@AppStorage("condenser.fontScale")` and applied on `MessageListView` / `SavedScreen` /
`MessageDetailSheet`. 2026-07-19: **pull-up-to-fetch-older** — in channel timelines, once
local history is exhausted (`hasMore == false`) a bottom footer appears and continuing to
pull up (overscroll ≥ 70pt while dragging, Kit's `PullToLoadOlderModel` + geometry helper)
triggers `POST /api/tg/fetch-older/{id}` then resumes paging via the new `end_cursor`
field (`TimelineStore.fetchOlderFromServer`; `fetched == 0` → `olderExhausted` sticky until
refresh). Aggregate All/Unread views don't get the gesture (no per-channel semantics).
**Forward-source-as-subject** — forwarded cards/detail render the origin (channel avatar via
`/api/channels/{id}/avatar` — works for unsubscribed public channels, 404 → letter fallback;
name from Kit's `DisplayMessage.forwardSource`: channel → user → post_author cascade) as the
header subject, with "Forwarded by <subscribed channel> · time" as the caption line; hidden
sources (no name) degrade to the old plain "转发" tag. `ChannelAvatarView.channelID` is now
optional (nil → letter avatar, no request). v1 spec complete;
remaining polish: end-to-end `ASWebAuthenticationSession` verify on device, video playback
(non-goal).

## Dev

```bash
uv sync --extra dev    # telememo comes from PyPI; no ../telememo checkout needed
cp .env.example .env   # fill TELEGRAM_API_ID/HASH, CONDENSER_APP_PASSWORD, CONDENSER_SECRET_KEY
uv run pytest          # backend tests — Telegram mocked, HN HTTP mocked via injectable fetch

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

Backend endpoints (spec C2) all exist and §7 scenarios are tested. Recently closed
(2026-06-24): SQLite WAL, `app_meta` wiring (schema version + runtime `backfill_days`
override via `PATCH /api/app/meta`), full channel info (`member_count`/`description` via
`GetFullChannelRequest` in `TgManager._enrich_channel`), runtime session-invalidation
(`_demote_session`), entity-cache warming on startup, and realtime **edit** handling
(telememo 0.2.0 `MessageEdited` — see below). Closed 2026-07-16: **device Bearer-token auth**
for the iOS app (devices table + web `/authorize` flow + SettingsDialog device management +
SPA fallback; spec `kb/plans/2026-07-16-mobile-client-api-device-token.md`). Closed 2026-07-19:
**multi-source Phase 1** — subscriptions table generalized (v3 migration), `hn_stories` +
`HNManager` sampling/backfill, `/api/sources/hn/*` endpoints, minimal Hacker News block on
`/subscriptions` (`HackerNewsSection`). Post-merge code review (10 findings: loop survival,
transient-null vs dead, pending-set race, re-subscribe re-enable, source-disabled 503 +
`source_enabled` status, thread-safe kick, migration `DEFAULT 'telegram'`, `channel_id` int
coercion) fixed via TDD — `kb/plans/2026-07-19-hn-phase1-review-fixes.md`. Deploy early so
the archive accumulates; Phases 2-4
(envelope API, federated timeline merge, web/iOS UI) are breaking and ship together — see
`kb/plans/2026-07-19-multi-source-hn.md`. Still open: subscription
"delete-with-messages" option (Q4 / `?purge=1`) and the backfill batch-interval sleep.
Full checklist: `kb/sessions/2026-06-09-backend-remaining-work.md`.

**Realtime edits (live on telememo 0.2.0):** `MessageEdited` handling lives in telememo's
`service.subscribe` (one handler registered for both `NewMessage` + `MessageEdited`). telememo
**0.2.0 is published to PyPI and pinned in `uv.lock`** (bumped 2026-06-25), so it's active.
condenser needs **no** code change — `_on_new_message` recomputes `is_filtered` for the
dispatched edit; `save_message_smart` updates the row's text/edit_date in place.

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
