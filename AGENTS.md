# Condenser — Agent Overview

Self-hosted, single-user **timeline reader** in the Google Reader mold. It started as a
Telegram-channel aggregator (`spec.md` is that original design, `draft.md` the brief) and
now federates **four sources** — Telegram channels, Hacker News, X (via a local probe),
and RSS — into one timeline, with a web frontend and an iOS app. **v1 is shipped**:
multi-stage Docker build (frontend + backend in one image), GitHub Actions →
ghcr.io/reorx/condenser → webhook deploy to https://condenser.reorx.com (Ansible role
`condenser` in the deploy workspace, host port 3459, SQLite bind-mounted at
`/opt/apps/condenser/data/`) — **a push to master is a production deploy**.

## Architecture

Single Python process: FastAPI + a Telethon MTProto **user-account** client on one asyncio
loop. Shares **one SQLite file** with [telememo](https://pypi.org/project/telememo/)
(a **PyPI dependency**; co-develop a local `../telememo` checkout via an editable overlay
— see the README "Co-developing telememo locally" section).

- **telememo** owns `channels` / `messages` / `comments`, including the telememo-native
  `messages.media_width` / `media_height` (filled on ingest, used by the frontend to
  reserve image placeholder space; NULL pre-2026-06-18). condenser adds one **overlay
  column**, `messages.is_filtered` — a rebuildable keyword-filter cache.
- **condenser** owns everything else (`SCHEMA_VERSION` 16): reader state (`read_items` /
  `saved_items` / `hidden_items` / `item_feedback`, all triple-keyed
  `(source, ref1, ref2)`), `subscriptions` (multi-source composite PK) +
  `keyword_filters`, the source archives (`hn_stories`; `x_tweets` + `x_feed_items` +
  `x_following`; `rss_feeds` + `rss_entries`), the verdict layer (`x_embeddings`,
  `x_attributes`, `x_vec_labeled` — a sqlite-vec `vec0` virtual table), full-text
  `search_index` (FTS5), and app state (`tg_session`, `devices`, `app_meta`,
  `link_previews`).

condenser's peewee models bind to telememo's `db` instance, so everything is one
connection. `condenser/db.py:init_db()` initializes telememo tables (+ `is_filtered`)
then condenser tables. ⚠️ Two ordering constraints in `init_db` are load-bearing
(`vectors.load()` before the migrations; shape-based `ADD COLUMN`s before
`create_tables`) — get either wrong and SQLite reports `database disk image is
malformed`.

**The schema changelog (v3–v15), table details and migration conventions live in
`kb/docs/database.md`** — read it before adding tables/columns, writing a migration, or
touching `init_db`.

## Key modules (`condenser/`)

| File | Role |
|---|---|
| `config.py` / `crypto.py` | env settings; Fernet session encryption + signed cookie from `CONDENSER_SECRET_KEY` |
| `db.py` | condenser tables (peewee, bound to telememo's db) + CRUD + shared `init_db`. Also the retention SQL `cleanup.py` calls (`sweep_x_retention` + `sqlite_freelist_ratio` / `vacuum`) — all SQL lives here, the `delete_channel_messages` precedent, including the docstring convention of naming what is *intentionally preserved* |
| `filters.py` | keyword-filter **materialization** into `messages.is_filtered` (on ingest + rule change) |
| `items.py` | item keys (`tg:{cid}:{mid}` / `hn:{sid}` / `x:{tweet_id}` / `rss:{entry_id}` ↔ the stored `(source, ref1, ref2)` triple) + the item **envelope** (`{source, key, datetime, is_read, is_saved, <source payload>}`, plus `feedback` on X) shared by timeline + records. The per-source payload rules — X snowflake ids as **strings**, feed-dependent X `datetime`, RSS `sort_at` beside the unclamped `published_at`, `_json_field` tolerance — are commented at the relevant functions. RSS's payload is the one that comes in **two sizes**: the list carries `content_excerpt` (+ `content_truncated`) and the article only arrives under `with_content=True`, which is `GET /api/rss/entries/{id}` and the saved snapshot |
| `timeline.py` + `sources/` | **federated timeline merge** (Phase 2): each provider in `sources/` (telegram / hn / x / rss) returns `SourceUnit` pages; `timeline.py` k-way merges them by timestamp under a **composite cursor** `base64(json {source: pos})` — a source absent from the map restarts from its top, bad/legacy cursors → 422. The per-source merge **floor**, `query_new`'s synthetic "now" anchors and the rest of the cursor semantics are in the module docstring + inline comments; each provider's own rules live in its module (see the source rows below) |
| `verdict.py` | the **For You verdict pipeline** on `app.state.verdict`, kicked by ingest: ensemble of enabled + shadow channels (`CONDENSER_VERDICT_CHANNELS`, default `b`), cold-start + OOD gates, training set read live from `item_feedback` ∪ `saved_items`, KNN index reconciled (not written through). **Pipeline, channel designs and evaluation: `kb/docs/x-verdict.md`** — read it before touching any verdict module |
| `channels.py` | the vocabulary the channels share (`ChannelScore`, verdict constants) + the combiners; production `resolve` is a per-channel **vote** (attributable, scale-free), abstain = `None` never 0.0 |
| `authors.py` | verdict **channel A** — the author prior: a Beta-smoothed tally over the reader's own labels; no API call, no table, reads no text; abstains below a minimum evidence mass |
| `attributes.py` | verdict **channel C** — LLM-extracted `topics` / `STYLE_FLAGS` (closed taxonomy, definitions shipped in the prompt) + attributed flag scoring in code; the project's first per-item billed component, fenced by its **own API key** (`CONDENSER_ATTR_API_KEY` = the on switch) |
| `ngram.py` | verdict **channel D** — naive Bayes over the words of labeled tweets ("how it talks"); no API call, refit per round, names its evidence; **not wired into the running verdict** |
| `vectors.py` | the **only** module that knows sqlite-vec exists: extension load, float32 BLOB pack/unpack, vec0 `upsert`/`knn`; degrades to no-op when the extension is unavailable, so an unsupported host loses only the verdict |
| `embedding.py` | OpenAI-compatible embeddings (`CONDENSER_EMBEDDING_*`, default DashScope `text-embedding-v4@256`); `available()` is false without an API key → the whole verdict pipeline stays inert; `model_tag` = `name@dims` (a model/dimension change re-embeds, never migrates) |
| `prospective.py` | the verdict's **online** evidence: precision measured only on tweets judged *before* the reader labeled them (selection-bias-free by construction); per-channel attribution + shadow replay at unrun thresholds |
| `records.py` | source-decoupled snapshots into `saved_items.raw_data` keyed by item key: TG = album rows + channel info, HN = story JSON, X and RSS = the envelope payload itself (X's quote already nested; RSS's computed `sort_at` included, since it does not survive the entry row, **and its article body**, which the list payload stopped carrying on 2026-08-23 — a snapshot is this module's promise that a record renders without its source tables); rendered back into envelopes without source tables. `rss_article` serves that stored body back to the detail endpoint |
| `forward.py` | renders a **non-Telegram** item into a message for the user's own channel (a TG item forwards natively — that path stays in `tg.py`). Three shapes: **HN** = title line → article + source line → discussion (Telegram builds its card from the *first* URL), **X** = a bare `fixupx.com` link (FixTweet embeds where x.com serves none), **RSS** = HN's shape minus the discussion line. The why of each shape is the module docstring; everything interpolated is `html.escape`d |
| `search.py` | the **only** module that knows FTS5 exists (`vectors.py`'s arrangement, same rationale): tokenizer, index maintenance, the per-source documents, the query, and hits → envelopes. Core design: CJK runs are **bigram-indexed in Python** and phrase-queried (substring semantics), with a deliberately **asymmetric** single-character rule, every token quoted (the whole injection story), and `TOKENIZER_VERSION` triggering a full rebuild on tokenizer edits **and** new sources alike. The full story is the module docstring + comments, pinned by tests |
| `preview.py` | source-agnostic link previews: fetch a URL (async httpx) + extract metadata (`metadata_parser`), `link_previews` cache, per-message batch w/ Telegram-bonus fill, image fetch for the proxy |
| `hn.py` | `HNManager` (on `app.state.hn`, peer of `TgManager`): subscription-driven front-page sampling (`topstories` diff → `hn_stories`, sticky `first_seen_at`), serial rate-limited hckrnews history backfill, link-preview prefetch, then `_qualify` (admission, v14) as the round's deliberate last step — the rule itself lives in `sources/hn.py:qualify`. The hardening rules (**null item ≠ dead**, catch-all loop guard, threadsafe `kick()`, preview attempt accounting) are documented at each function. `routers/hn.py` = subscriptions + status; its config PATCH **merges** into `hn.sub_config` (three admission knobs share the column — a whole-value write would disarm two). HTTP via injectable `fetch_json`/`fetch_preview` (tests need no network). Plans: `kb/plans/2026-07-19-multi-source-hn.md`, `…-hn-phase1-review-fixes.md` |
| `x.py` | X (Twitter) source, **push model** — the server never talks to X; the local probe (`probe/`, `kb/docs/probe.md`) reads the logged-in session via `xbird` and pushes JSON. Owns tolerant `parse_tweet` + idempotent `ingest_tweets` (raw archived for re-parse after format drift), the Following feed's **ad + age filters** and the For You **language filter** (all fail-open — rationale at each function), `probe_config` and `status`. `sources/x.py` is the timeline provider: feed-dependent `SORT_AT_SQL`, an **explicit `ROW_NUMBER()` dedup priority** (account subscription > following > For You), and per-feed `aggregate` admission (`none` \| `positive` \| `all`; **For You is opt-in** — a capacity decision) that `bulk_read_scope` shares, so "mark all read" burns exactly what the view showed. `routers/x.py` adds ingest / following (refuses an empty push over a non-empty list) / avatar-proxy endpoints; 503 when `CONDENSER_X_ENABLED=false`. Design history: `kb/plans/2026-07-24-x-source-local-probe.md`, `kb/plans/2026-07-30-x-following-feed.md` |
| `rss.py` | **RSS source** — the simplest here, deliberately: a published standard, so no probe, no reverse-engineered API, nothing to judge. `RssManager` (on `app.state.rss`) polls enabled feeds through an injectable `fetch_feed` (parsing is deliberately **not** injectable — real-world XML is the whole risk surface); three failure modes are told apart (**304 = hit**, bozo-with-entries = warning, `NotAFeedError` for clean-parsing HTML), and ingest applies the **unread window** so an import does not land as unread backlog. A warning is written with the `''`-clears / `None`-keeps convention, so a 304 (which parsed no document) cannot erase the previous round's complaint. An all-301/308 redirect chain **moves the key**: `db.migrate_rss_feed_url` walks the URL across its three tables in one transaction, but only at the tail of a round that was 200 + parsed + ingested, and never onto a URL already subscribed — the reason to follow it at all is that the forwarding expires with the old domain (plan `kb/plans/2026-08-22-rss-post-launch-fixes.md` §4). `sources/rss.py` (the provider)'s one real decision is the clamped `sort_at` — computed in SQL, never written to the stored row, carried in the envelope for snapshot replay. `routers/rss.py` follows the HN/X shape except PATCH/DELETE key the feed by `?url=`, plus `GET /rss/entries/{id}` — the **article half** of the 2026-08-23 payload split: the timeline ships a 500-char `content_excerpt` (materialized at ingest, schema v16) and the body is fetched by whoever opens one. The provider keeps **two selects** for it, and the list one names its columns precisely so the body cannot creep back into `e.*`. Rationale: the two module docstrings + plans `kb/plans/2026-08-20-rss-source-opml-llm-summary.md`, `…-2026-08-23-rss-list-excerpt-detail-endpoint.md` |
| `summary.py` | the **LLM summary pipeline** for RSS entries — the card shows 2-3 Chinese sentences instead of somebody else's HTML. The project's second per-item billed component, fenced like the first (channel C): a switch, its **own** key `CONDENSER_SUMMARY_API_KEY` (= the on switch, no fallback), a per-round batch cap, and counts on `/api/rss/status`. Hangs off `poll_once`'s tail (no loop of its own — RSS content only arrives with a round), summarizes **unread entries of enabled feeds only**, one request per entry, newest first. Two rules to know before touching it: a failure is charged to whoever caused it (a provider that never answered burns no retry and ends the round; a rejected input costs the entry one of three attempts), and `summary_model` is **provenance, not a re-do contract** — it also carries the `skip:short` sentinel, which is what stops a markup-heavy one-liner re-entering every batch forever. Thinking is turned **off** by default (measured: 1274 reasoning tokens against 99 of answer, and `max_tokens` does not bound them) |
| `text.py` | feed HTML → prose (`plain_text`) + the list payload's cut (`excerpt`, `EXCERPT_CHARS` = 500). A module of its own because two unrelated things share the stripping — the summariser's billed input and the unbilled `content_excerpt` — and because `items.py` needs it while `summary.py` imports `db`, which imports `items`. No package imports of its own; that is the point. ⚠️ `_drop_noise` (script/style removal) is a **hand-written scan, not a substitution** — the obvious `<(script|style)\b.*?</\1\s*>` is quadratic on a page whose openers never close (measured 1MB = 97s), and this now runs at every ingest and over the whole archive in the v16 backfill |
| `cleanup.py` | **daily retention sweep** (on `app.state.cleanup`): wakes hourly against a **database breakpoint** (not a timer — deploys restart the process too often), runs rounds on a worker thread (VACUUM's exclusive lock), rules duck-typed + isolated per rule (`DEFAULT_RULES`: X and RSS retention). Rationale, including the deliberate absence of `kick()`, is the module docstring. ⚠️ a test module with a fixed clock in the past must disable the retention rules or the startup round deletes its fixtures (see Conventions & gotchas). `GET /api/cleanup/status` exists so "ran, found nothing" does not look like "never ran" |
| `tg.py` | `TgManager`: lifecycle (C1), step-login→encrypted storage, realtime ingest, backfill scheduling, subscription orchestration |
| `auth.py` + `routers/*` | C2 endpoints behind `require_auth` = app-password cookie **or** device Bearer token (`devices` table, sha256 hash only, issued via the web `/authorize` page for the iOS app; management endpoints are cookie-only — see `kb/plans/2026-07-16-mobile-client-api-device-token.md`); `routers/channels.py` = avatar proxy, `routers/preview.py` = link-preview + image proxy; `routers/common.py` = `parse_key_or_422`, shared by every key-driven endpoint; `/api/tg/status` carries `phone` |
| `app.py` / `__main__.py` | FastAPI factory + lifespan; uvicorn entry; serves a static frontend dir if present via `SPAStaticFiles` (index.html fallback for client routes — `/authorize` cold-load depends on it; unknown `/api/*` still 404) |

## Conventions & gotchas

- **Extension-column contract**: telememo write paths only touch native columns, so
  `is_filtered` survives incremental edits. Never use full-row `INSERT OR REPLACE` in telememo.
- **Filtering is materialized**, not query-time: matching happens on the write side; the
  timeline query only reads the `is_filtered` boolean. Regex is reserved for later.
- **peewee connections are thread-local**: tests close the main-thread connection between
  cases (see `tests/conftest.py`) because TestClient runs the lifespan in a portal thread.
- **A transaction that reads before it writes must be `atomic(lock_type='IMMEDIATE')`**, and
  must not be nested (nesting turns it into a savepoint and drops the lock_type). A deferred
  read-then-write transaction whose snapshot another connection has written past dies with an
  *immediate* `database is locked` — SQLite skips the busy handler on the upgrade, so no
  timeout or in-transaction retry saves it. Verified + pinned by `tests/test_db_locking.py`
  (2026-08-23); write-first `atomic()` blocks and bare `get_or_create` are fine as they are.
- **Fixed-clock tests vs the cleanup sweep**: a test module that seeds fixtures with old
  timestamps must disable the retention rules (e.g. `CONDENSER_CLEANUP_RSS_ENABLED=false`),
  or the cleanup round at app startup deletes them out from under the assertions — the trap
  `test_x_verdict` hit on 2026-08-09; `tests/test_rss_timeline.py` shows the pattern.
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
  itself** or the gate refetch-loops (`lib/queryClient.ts`). Since 2026-08-15 the Telegram
  login is a wall **only for a Telegram-only install**: if `GET /api/sources` reports any
  non-Telegram subscription, an unauthorized Telegram session no longer blocks the app. The
  app went multi-source two sources ago, and an HN- or X-only install has content to show —
  a phone-number form in front of it is a lock, not onboarding. That is exactly the shape of
  the App Store review demo server (`kb.private/condenser/kb/docs/demo-server.md`), which is
  what surfaced it.
  Three details are load-bearing: the gate **waits** for the sources query instead of
  deciding early (else the wall flashes at an install that has other sources), a failed
  sources request falls back to walling (the pre-multi-source behavior), and
  `/connect-telegram` renders `TgLogin` from inside the app — `SettingsDialog`'s Telegram row
  links there when disconnected, and it is now the only way to reach the Telegram login at
  all. `useSources` is `enabled`-gated in the gate so it never fires behind `AppLogin`.
- **Scroll-past-to-read** via IntersectionObserver + debounced batch `POST /api/read`
  (`useScrollToRead`); window is the scroll container (IO root = viewport). Since 2026-08-05
  ("看过即读", both platforms): a card is judged read once the user has scrolled in the view
  (armed) AND its **bottom edge is at/above the viewport bottom** — fully seen, not scrolled
  away. Three states: unread = sky dot / **pending sync = emerald dot** (`pendingKeys`, also
  the divider-mode border colors) / read = none. The cache flip + badge decrement run only on
  server confirmation; a failed batch stays green and retries at debounce×5 (the lit green dot
  IS the "sync is stuck" signal). Arming does a one-shot manual `getBoundingClientRect` sweep
  of observed elements (IO won't re-fire without an intersection change), and the IO uses a
  dense 0→1/0.05 threshold ladder so cards taller than the viewport still fire on the
  bottom-edge crossing. `disarm()` re-gates after `jumpToNewest`; a page unload drops the
  unsynced queue — honest by design, those items reload as unread. iOS mirrors the semantics
  (Kit `ScrollReadModel` + `ReadReporter.unsyncedKeys`).
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

The **X block** on the Subscriptions page (`components/subscriptions/XSection.tsx` +
`XSubscriptionRow.tsx`, `XGlyph.tsx`) manages the source: add For You / an account by
handle, pause, unsubscribe, plus a status line whose job is to reveal that a silent feed is
the *probe's* fault, not the server's (`last push` / `parse errors`). A user feed's `name`
stays NULL until the first push teaches it the real display name, so the row falls back to
`@handle` instead of rendering a placeholder next to the same handle.

**X reading surfaces (Phase 2, 2026-07-25)**: `XCard` (+ `XQuoteCard` / `XMedia` /
`XMediaThumb` / `XLightbox` / `XAvatar`, see `frontend/AGENTS.md`), a `/s/:source/:feed`
route so each X feed has its own view, and `SidebarXFeedLink` rows. `feed` threads through
`useTimeline` / `useTimelineDays` / `useNewContent` / `useBulkRead` and the matching
endpoints. **For You is not in the aggregate timeline** (capacity decision — see the `x.py`
row above); its sidebar row is the only way in. Tweet media and author avatars both route
through backend proxies, so reading a tweet never contacts X from the browser.

**X feedback (Phase 3, 2026-07-25) + down-reason chips (schema v9)**:
`POST /api/feedback {key, verdict, reason?}` / `DELETE /api/feedback/{key}`
(`routers/reading.py`) write `item_feedback`; the envelope carries the label back as
`feedback` plus the **sibling** field `feedback_reason` (never nested — shipped iOS
builds decode `feedback` as a bare string). Phase 3 only records labels; acting on them
is the verdict's job. `FEEDBACK_REASONS` (`topic` / `promo` / `ai_slop` /
`engagement_farming`「博眼球」 / `author`) is pinned across `db.py` / `lib/sources.ts` /
Kit by a test. **API rules, chip UX (web `XFeedbackButtons` + iOS) and the taxonomy
decisions live in `kb/docs/x-feedback.md`** — read it before changing the feedback
endpoints, the chip UI, or the reason set.

## Local probe (`probe/`, monorepo)

Independent uv package (`condenser-probe`) that runs on the user's own machine — the X
source's **fetch half**, since X data only exists inside a logged-in browser session.
Each round: `GET probe-config` → one X read per feed through the `xbird` library →
`POST ingest`; the server decides when the follow list re-syncs, so the probe keeps no
schedule of its own. Configless beyond a server URL + device token; the one piece of
local state is `SeenCache`. `watch` (APScheduler, staggered cadences) is the
long-running mode a launchd agent keeps alive — **deploys are `launchctl kickstart`,
not `git push`**.

Details in `kb/docs/probe.md`: the xbird migration and its four kept invariants (wire
shape, per-feed failures, all-or-nothing follow crawl, page pacing), credential
resolution, the stale-code kickstart trap, SeenCache semantics, and the schedule. Read
it before touching `probe/` or debugging a silent X feed.

## iOS app (`ios/`, monorepo)

Native SwiftUI read-only client, pure-CLI workflow (xcodegen `project.yml` + Makefile,
simulator via `simctl`). Two layers: `CondenserKit/` local SPM package (pure logic +
Swift Testing) and `Condenser/` app target. Device-token auth, envelope-based
multi-source timeline (TG / HN / X / RSS cards), scroll-to-read, saved / subscriptions /
settings tabs, share-as-image from every detail sheet, DEBUG deep-link walkthroughs.
**1.0.0 submitted for App Store review 2026-08-16** (paid USD 2.00, manual release);
the RSS card landed after that submission and rides the next build — a shipped client that meets an unknown source draws blank
rows, which is why `CONDENSER_RSS_ENABLED` still ships false.

Details in `kb/docs/ios.md`: the phase-by-phase feature history with the design
decisions behind each surface, and the signing / App Store 发布 record (素材、提审、
demo server). Read it before iOS feature work; `ios/AGENTS.md` has the build commands
and conventions; release 操作前先读私密 KB 的 ios-app-store-release.md.

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

# Log a browser session into the running dev app (the auth gate blocks walkthroughs):
scripts/dev-browser-login.sh [session] [--backend URL] [--frontend URL]
```

### `scripts/`

| Script | What it does |
|---|---|
| `x_verdict_backtest.py` | leave-one-out backtest of the For You verdict on your real labels — the tool that turns constants into decisions and picks the channels (`--channels a,b,d` on the same folds, `--sweep` per-channel grids). Read-only on the DB except the KNN index (trashed per fold, rebuilt at the end); `--embed-missing` is the only mode that calls an API. How to read its output: `kb/docs/x-verdict.md` |
| `x_verdict_prospective.py` | the online counterpart: scores only tweets judged *before* they were labeled, so nothing here can be tuned against. Fully read-only (never touches the KNN index — safe on a live copy). Output order + shadow replay: `kb/docs/x-verdict.md` |
| `dev-browser-login.sh` | Puts a logged-in session cookie into an `agent-browser` profile so a UI walkthrough can run behind the auth gate. The app password stays on stdin the whole way (envops → curl → cookie jar → cookie file → agent-browser), so it never reaches a command line or an agent transcript; the temp files are deleted on exit. Encodes two traps: agent-browser's cookie file must be bare `k=v; k2=v2` (a `Cookie: k=v` header line silently becomes a cookie *named* `Cookie: k`, stored but never sent), and a backend-issued cookie works on the Vite origin because cookies ignore ports. **Check the dev backend was started with `--reload`** (`ps -o command -p $(lsof -ti :8792 -sTCP:LISTEN)`) or the walkthrough verifies stale code |
| `opml_picker.py` | trims an OPML down to a chosen subset: `uv run scripts/opml_picker.py feeds.opml` serves a checkbox page on localhost, opens a browser, and the 生成 button downloads the picked feeds as a new OPML. A **PEP 723 stdlib-only** script (nothing to install, no network of its own) and the only thing here that never touches the DB — a 203-feed Miniflux export is what it was built against. Removing feeds is the *only* edit it makes: outline attributes (including namespaced `miniflux:*` ones, whose prefix it re-registers) and the group nesting carry through untouched, and a group is emitted only when a feed of it survived. Pinned by `tests/test_opml_picker.py` |

## Status / known gaps

The dated work log lives in `kb/docs/status-and-gaps.md`: every feature landing since
2026-06 with its measurements, test counts, deploy state and the traps found along the
way — the project's memory of *why* things are the way they are. Chronological, oldest
first, so **read from the tail to catch up on the current state**. Consult it when you
need the history or evidence behind a feature (backtest numbers, deploy incidents,
rejected designs); for "what is true right now", this file and the other `kb/docs/`
pages are the authority.

## Documentation

- `kb/docs/database.md` — table ownership, `init_db` ordering traps, migration
  conventions, and the full schema changelog (v3–v15, newest first). Read before adding
  tables/columns, writing a migration, or touching `db.init_db`.
- `kb/docs/x-verdict.md` — the X For You verdict: pipeline (`verdict.py`), channels A–D
  (`authors` / kNN / `attributes` / `ngram`), shared vocabulary (`channels.py`), vector
  infra (`vectors.py` / `embedding.py`), and the two evaluation tools. Read before
  touching any of these modules or the verdict scripts.
- `kb/docs/x-feedback.md` — X up/down labels + down-reason chips: feedback API rules,
  web/iOS chip UX, and the reason-taxonomy decisions. Read before changing the feedback
  endpoints or `FEEDBACK_REASONS`.
- `kb/docs/probe.md` — the local X probe: xbird invariants, credentials, SeenCache,
  scheduling, the kickstart deploy trap. Read before touching `probe/` or debugging a
  silent X feed.
- `kb/docs/ios.md` — iOS feature history + signing / App Store release record. Read
  before iOS feature work (build commands are in `ios/AGENTS.md`).
- `kb/docs/status-and-gaps.md` — the dated work log (oldest first; read from the tail).
  Consult for the history and evidence behind a feature: measurements, deploy
  incidents, rejected designs.
- `kb/docs/content-update-mechanism.md` — Read before touching ingest/sync: realtime push,
  backfill, the manual refresh / fetch-older / reset triggers, the enable toggle, and how
  fetch-older's id-anchored cursor paging works.
- ⚠️ **凡是 app 审核/发布，或服务器部署/运维相关的文档，一律写进私密 KB 仓库
  `../kb.private/condenser/kb/<docs|plans|sessions>/`，不进本库。** 本库是公开仓库
  （<https://github.com/reorx/condenser>），而这类文档的价值恰恰在于它记着具体值——
  Apple 账号标识、生产主机与端口、Caddy/DNS、审核表单。抹掉这些就没有文档了，所以整份
  挪走、本库只留一行指针（判断标准见 `../kb.private/README.md`）。已经这样处理的：
- `kb.private/condenser/kb/docs/ios-app-store-release.md` — iOS 首次发布全流程记录：
  关键资产（app id / bundle ID / API keys）、已跑通的签名与出包链路、上传 build 与
  提审前的剩余步骤、审核 demo 服务方案。做发布操作（传 build / 提审 / 出新版本）前读它。
  同理 `kb.private/condenser/kb/sessions/2026-08-12-ios-signing-and-app-store-ready.md`。
- `kb.private/condenser/kb/docs/demo-server.md` — `condenser-demo.reorx.com`，App Store
  审核用的第二实例（只开 HN、无 Telegram 会话、不接 hookploy）。**提审前必读**：
  `scripts/demo_bootstrap.py`（脚本本身在本库 `scripts/`）既是初始化也是健康检查，
  外加审核表单怎么填、备注话术、每次提审前的 checklist。密码实值与 ASC 表单在同目录的
  `ios-app-store-release.md`。决策记录是
  `kb.private/condenser/kb/plans/2026-08-15-app-review-demo-server.md`。
  （2026-08-16 从本库 `kb/docs/` + `kb/plans/` 整体挪过去。）
- `kb/sessions/` — dated session summaries (history). Read the latest to catch up on recent work.
