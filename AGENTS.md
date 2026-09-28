# Condenser — Agent Overview

Self-hosted, single-user **timeline reader** in the Google Reader mold. It federates
**four sources** — Telegram channels, Hacker News, X (through a local probe) and RSS —
into one timeline, read from a web frontend and a native iOS / Mac Catalyst app.
`spec.md` and `draft.md` are the original Telegram-only design; treat them as history.

**A push to master is a production deploy** when it touches what the image consumes:
`condenser/`, `frontend/` (minus tests, preview and docs), `pyproject.toml`, `uv.lock`,
`Dockerfile`. GitHub Actions builds `ghcr.io/reorx/condenser` and a webhook deploys it to
<https://condenser.reorx.com>. Pushes that only touch `kb/`, `ios/`, `probe/`, `tests/`
or docs skip the build; `workflow_dispatch` is the manual rebuild. Host-side details live
in the deploy workspace (Ansible role `condenser`).

## Architecture

One Python process: FastAPI plus a Telethon MTProto **user-account** client on one asyncio
loop, with the managers on `app.state` (`tg` / `hn` / `rss` / `verdict` / `cleanup`). It
shares **one SQLite file** with [telememo](https://pypi.org/project/telememo/), a PyPI
dependency. condenser's peewee models bind to telememo's `db`, so everything is one
connection.

- **telememo** owns `channels` / `messages` / `comments`. condenser adds one overlay
  column, `messages.is_filtered`, a rebuildable keyword-filter cache.
- **condenser** owns the rest (`SCHEMA_VERSION` 21):
  - reader state, keyed by the `(source, ref1, ref2)` triple: `read_items`,
    `saved_items`, `hidden_items`, `item_feedback`, and `forward_records` (a log with its
    own id, one row per publish)
  - `subscriptions` (multi-source composite PK) and `keyword_filters`
  - source archives: `hn_stories`; `x_tweets` / `x_feed_items` / `x_following`;
    `rss_feeds` / `rss_entries`
  - the verdict layer: `x_embeddings`, `x_attributes`, `x_vec_labeled` (a sqlite-vec
    `vec0` virtual table)
  - `search_index` (FTS5)
  - app state: `tg_session`, `devices`, `app_meta`, `link_previews`
- `saved_items` holds every item the reader acted on, not only bookmarks: a row exists
  ⟺ saved ∨ note ∨ annotations, so unsaving keeps an annotated row.

⚠️ `db.init_db()` has two load-bearing ordering constraints: `vectors.load()` before the
migrations, and shape-based `ADD COLUMN`s before `create_tables`. Get either wrong and
SQLite reports `database disk image is malformed`.

Read `kb/docs/database.md` before adding tables or columns, writing a migration, or
touching `init_db`. It has table ownership, migration conventions and the schema
changelog (v3–v21).

## Key modules (`condenser/`)

Each row gives the role and what must not break. The full story of a module is its
docstring and inline comments; read them before editing.

### Core and API

| File | Role |
|---|---|
| `config.py` / `crypto.py` | env settings (`CONDENSER_*`); Fernet session encryption and signed cookies from `CONDENSER_SECRET_KEY` |
| `app.py` / `__main__.py` | FastAPI factory + lifespan; uvicorn entry. Serves `frontend/dist` through `SPAStaticFiles` (index.html fallback for client routes; unknown `/api/*` still 404). `SelectiveGZipMiddleware` passes image / video / audio / font responses through uncompressed |
| `auth.py` + `routers/` | every endpoint sits behind `require_auth`: app-password cookie **or** device Bearer token (`devices` table, sha256 only, issued on the web `/authorize` page). Device management is cookie-only. `routers/common.py:parse_key_or_422` is shared by every key-driven endpoint. Plan: `kb/plans/2026-07-16-mobile-client-api-device-token.md` |
| `db.py` | condenser's tables, CRUD and `init_db`. **All SQL lives here**, retention sweeps included. A destructive function's docstring names what it *intentionally preserves* |

### Items, timeline, reader state

| File | Role |
|---|---|
| `items.py` | item keys (`tg:{cid}:{mid}` / `hn:{sid}` / `x:{tweet_id}` / `rss:{entry_id}` ↔ the stored triple) and the item **envelope** `{source, key, datetime, is_read, is_saved, <source payload>}` every list surface shares. X ids cross the API as **strings**. RSS entries and X articles come in two sizes: lists carry `content_excerpt` / `article.has_content`, the body arrives only under `with_content=True` (the detail endpoints and snapshots) |
| `timeline.py` + `sources/` | federated merge: each provider (telegram / hn / x / rss) returns `SourceUnit` pages, k-way merged by timestamp under a composite cursor `base64(json {source: pos})`. A source absent from the cursor restarts from its top; an invalid cursor is a 422. `query_new` / `query_new_count` back the new-content poll and the iOS pill |
| `filters.py` | materializes keyword filters into `messages.is_filtered`, on ingest and on rule change |
| `records.py` | saved records: snapshots in `saved_items.raw_data`, plus item notes and annotations (v18). A snapshot must render **without its source tables**, since retention deletes them, so it carries the article body and computed fields such as RSS `sort_at`. `build_item_snapshot` is shared with forwards; `stamp_notes` adds `note` / `annotations` to list envelopes |
| `forwards.py` / `forward.py` | the forward log's read side (`/forwards` list, the `forwarded_by_me` stamp) / rendering a non-Telegram item into a Telegram message. ⚠️ `forwarded_by_me` is not `is_forwarded`, Telegram's flag for the opposite direction. The write is in `tg.forward_item`, which **deliberately swallows** a failed record write and answers `recorded: false`: the message is already sent, and a 500 would make the client retry and post it twice |
| `search.py` | the only module that knows FTS5. CJK runs are bigram-tokenized in Python and phrase-queried; every token is quoted. The index is a rebuildable cache: bump `TOKENIZER_VERSION` when the tokenizer or any source's document changes. Plan: `kb/plans/2026-08-08-full-text-search.md` |
| `preview.py` | link previews for any source: fetch + metadata extraction, the `link_previews` cache, image fetch for the proxy |

### Sources

| File | Role |
|---|---|
| `tg.py` | `TgManager`: lifecycle, step login with encrypted session storage, realtime ingest, backfill, subscriptions, forwarding. Read `kb/docs/content-update-mechanism.md` before touching ingest or sync |
| `hn.py` + `sources/hn.py` + `routers/hn.py` | `HNManager` samples the front page into `hn_stories` once an HN subscription exists. Round order: sample → preview prefetch → `_qualify` → `_top_up` → `_summarize_round`. Admission is **one-way** and stored (`qualified_at`); the read path never re-ranks. The config PATCH **merges** into `sub_config`, because three admission knobs share the column. HTTP is injectable (`fetch_json` and friends). Plans: `kb/plans/2026-07-19-multi-source-hn.md`, `…2026-08-14-hn-story-admission.md`, `…2026-09-03-hn-day-close-top-up.md` |
| `x.py` + `sources/x.py` + `routers/x.py` | **push model**: the server never talks to X, the local probe pushes JSON (`kb/docs/probe.md`). Parsing is tolerant and raw JSON is archived for re-parsing. The ad, age and language filters fail open. Dedup priority is account > Following > For You. For You sorts by `first_seen_at` and joins the aggregate only per its `aggregate` config (`none` \| `positive` \| `all`), which `bulk_read_scope` shares. An article body (v21) is stored in `article_detail`, and a bodiless re-push must not wipe it. 503 when `CONDENSER_X_ENABLED=false` |
| `rss.py` + `sources/rss.py` + `routers/rss.py` | `RssManager` polls with conditional requests through an injectable `fetch_feed`; parsing is deliberately not injectable. Ingest applies the unread window. Lists ship a 500-char `content_excerpt` and the body comes from `GET /api/rss/entries/{id}`, so keep the list select's explicit column list. `sort_at` is computed in SQL and never stored. Failing feeds back off exponentially up to a week and get marked `abnormal`, never auto-paused. An all-301/308 redirect migrates the feed's URL key. PATCH / DELETE key a feed by `?url=`. Plans: `kb/plans/2026-08-20-rss-source-opml-llm-summary.md`, `…2026-09-16-rss-failure-backoff.md` |
| `summary.py` / `hn_summary.py` | billed LLM summaries for RSS entries and HN stories, run at the tail of each polling round. `CONDENSER_SUMMARY_API_KEY` is the on switch for both, with no fallback key; HN adds `CONDENSER_HN_SUMMARY_ENABLED`. One request per item, a per-round cap, and a failure is charged to whoever caused it. `summary_model` is provenance and also carries the `skip:short` / `skip:empty` sentinels |
| `xarticle.py` / `text.py` | X Article Markdown → HTML (raw HTML escaped) / feed HTML → plain text and excerpt. Both have **no package imports**, because `items.py` depends on them; keep it that way. ⚠️ `text._drop_noise` is a hand-written scan: the obvious regex is quadratic on unclosed tags |
| `cleanup.py` | daily retention sweep (X and RSS rules) and the VACUUM decision. Wakes hourly against a timestamp in `app_meta`, since deploys restart the process too often for a timer, and runs on a worker thread. `GET /api/cleanup/status` reports the last round |

### X For You verdict

Read `kb/docs/x-verdict.md` before touching any of these or the verdict scripts.

| File | Role |
|---|---|
| `verdict.py` | the pipeline on `app.state.verdict`, kicked by ingest: an ensemble of enabled and shadow channels (`CONDENSER_VERDICT_CHANNELS`, default `b`), cold-start and OOD gates, training set read live from `item_feedback` ∪ `saved_items` |
| `channels.py` | shared vocabulary (`ChannelScore`, verdict constants) and the combiners. Production `resolve` is a per-channel vote; abstain is `None`, never 0.0 |
| `authors.py` / `attributes.py` / `ngram.py` | channel A (author prior, no API call) / channel C (LLM-extracted topics and style flags; billed, `CONDENSER_ATTR_API_KEY` is its switch) / channel D (naive Bayes, **not wired** into the running verdict). Channel B is the kNN in `verdict.py` |
| `vectors.py` / `embedding.py` | the only module that knows sqlite-vec, a no-op when the extension is missing / OpenAI-compatible embeddings. Without an embedding key the whole pipeline stays inert. A model or dimension change re-embeds, never migrates |
| `prospective.py` | online evidence: precision measured only on tweets judged *before* the reader labeled them |

### Purifier (iOS reading proxy)

| File | Role |
|---|---|
| `purifier.py` + `purifier_html.py` + `routers/purifier.py` | `GET /p/<host>/<path>` returns a page that depends on nothing but condenser: scripts dropped, assets rewritten to `/pa/…`, links to `/p/…`. Modes: `proxy`, `readable` (default), and `puremd` as fallback only. HTML is walked with lxml, never regexed. `/p` and `/pa` accept only the reader cookie (minted from a 5-minute ticket, bound to a device that must still exist) or the session cookie, never Bearer. Every security fix is pinned by a test; read `kb/reviews/2026-09-07-purifier-code-review.md` and `kb/plans/2026-09-07-purifier.md` before editing the sanitizer, URL parsing or the host guard |
| `purifier_x.py` | X status links are **built** from FxEmbed's anonymous JSON API rather than fetched; the only module that knows FxEmbed. `CONDENSER_PURIFIER_X_API_BASE` empty turns it off, and `/p` then 302s to the original. iOS `isPurifierExcluded(host:path:)` mirrors the URL rule. Measured API quirks are in the module docstring; plan `kb/plans/2026-09-17-purifier-x-fxembed.md` |

## Conventions & gotchas

- **Extension-column contract**: telememo's write paths touch only native columns, so
  `is_filtered` survives edits. Never use a full-row `INSERT OR REPLACE` in telememo.
- **Filtering is materialized**: matching happens on the write side, and the timeline
  query only reads `is_filtered`.
- **Rebuildable caches are rebuilt, never migrated**: `is_filtered`, `search_index`,
  `x_embeddings` / `x_vec_labeled`.
- **Billed components are fenced**: channel C runs only with `CONDENSER_ATTR_API_KEY`
  set, the two summary pipelines only with `CONDENSER_SUMMARY_API_KEY`, each under a
  per-round cap. Never add a fallback to another key, or deploying code starts spending.
- **Tests never touch the network**: Telegram is mocked, and HN / RSS / summary HTTP goes
  through injectable functions.
- **peewee connections are thread-local**: tests close the main-thread connection between
  cases (`tests/conftest.py`), because TestClient runs the lifespan in a portal thread.
- **A transaction that reads before it writes must be `atomic(lock_type='IMMEDIATE')`**
  and must not be nested, since nesting turns it into a savepoint and drops the lock
  type. A deferred one dies with an immediate `database is locked` that no timeout or
  retry saves. Pinned by `tests/test_db_locking.py`. Write-first `atomic()` blocks and
  bare `get_or_create` are fine.
- **Fixed-clock tests vs the cleanup sweep**: a test module seeding old timestamps must
  disable the retention rules (e.g. `CONDENSER_CLEANUP_RSS_ENABLED=false`), or the
  startup round deletes its fixtures. `tests/test_rss_timeline.py` shows the pattern.
- **Cursor + albums**: album rows share a date and adjacent ids. Fetch `limit + buffer`,
  merge by `grouped_id`, anchor the cursor on the unit's min id, and keep `has_more`
  conservative.
- A **PostToolUse formatter hook** rewrites files to single-quote style on save.
- **Telegram is a user account (MTProto)**, a ToS gray area. The StringSession is
  encrypted at rest, and the fetch layer backs off on `FloodWaitError`.
- **Resolve Telegram peers through `tg._channel_handle`**, which prefers `@username`.
  A StringSession does not persist Telethon's entity cache, so `get_entity(int)` fails
  after a restart for peers not met in this process. Private channels fall back to the
  int and depend on `TgManager._warm_entity_cache`, which walks the dialogs once on boot.
- **Forward source names** are filled on ingest by a three-tier cascade: Telethon's
  already-resolved entities, then the `EntityNameCache` JSON file
  (`CONDENSER_ENTITY_CACHE_PATH`), then `get_entity`. Realtime ingest passes
  `allow_network=False` so the event handler never waits on Telegram; only backfill may
  use the third tier. See `telememo/telegram.py:resolve_forward_entity_names`.

## telememo (`../telememo`, separate git repo)

Owns the Telegram fetch and storage layer: `TelegramService` (`service.py`), `db.py`,
`telegram.py` converters, `entity_cache.py`. One handler serves both `NewMessage` and
`MessageEdited`, and `save_message_smart` updates a row in place when `edit_date`
changed. It has its own `CLAUDE.md`. To co-develop against a local checkout, use the
editable overlay described in the README section "Co-developing telememo locally".

## Frontend (`frontend/`)

React 19 + Vite 6 + TS (strict) + Tailwind v4 + shadcn/ui + TanStack Query v5 + React
Router v7, pnpm. Two documents cover it:

- `frontend/AGENTS.md` is the component / hooks / lib inventory and the preview harness.
  Update its row in the same change whenever a component changes.
- `kb/docs/frontend.md` is the cross-cutting behavior: auth gate, scroll-to-read, the
  reading-view shell, cache mutation rules, forwards, Vibe Reader link mode, X surfaces.
  Read it before changing a behavior that spans components.

Know these before opening either:

- The auth gate is the `tg-status` query. The global 401 handler must skip `tg-status`
  itself, or the gate refetch-loops.
- An item is flipped to read only on server confirmation; the green dot means pending.
- Item envelopes sit in several caches at once. Patch them through `lib/itemCaches.ts`.
- `lib/types.ts` mirrors the backend JSON. Change both sides together, and check the iOS
  Kit models, since shipped builds decode the same payloads.

## Local probe (`probe/`)

An independent uv package (`condenser-probe`) that runs on the user's own machine: the X
source's fetch half, since X data exists only inside a logged-in browser session. Each
round: `GET probe-config` → one X read per feed through `xbird` → a TweetDetail read for
each new X Article → `POST ingest`. The server decides when the follow list re-syncs.
`watch` is the long-running mode a launchd agent keeps alive, so **deploying the probe is
`launchctl kickstart`, not `git push`**. A probe left running on old code is the usual
cause of a silent feature.

Read `kb/docs/probe.md` before touching `probe/` or debugging a silent X feed.

## iOS app (`ios/`)

Native SwiftUI client with a pure-CLI workflow (xcodegen `project.yml` + Makefile,
simulator through `simctl`). Two layers: `CondenserKit/`, a local SPM package of pure
logic with Swift Testing, and the `Condenser/` app target. The same target builds as a
**Mac Catalyst** app (`make build-mac`); platform differences live in `UI/Platform.swift`.

- Auth is a device token. `/p` and `/pa` reader pages use the ticket flow instead.
- Shipped builds decode the API as it was when they were built. Add fields beside
  existing ones rather than changing their shape (`feedback_reason` sits next to
  `feedback` for this reason). A client that meets an unknown source draws blank rows,
  which is why `CONDENSER_RSS_ENABLED` defaults to false.
- Release state: 1.1.0 is in TestFlight internal testing and the app is not on the App
  Store yet. The current review status is in the private KB.

`ios/AGENTS.md` has the build commands and conventions. `kb/docs/ios.md` has the feature
history and the design decisions behind each surface; read it before iOS feature work.
Before any release operation, read `ios-app-store-release.md` in the private KB.

## Dev

```bash
uv sync --extra dev    # telememo comes from PyPI; no ../telememo checkout needed
cp .env.example .env   # fill TELEGRAM_API_ID/HASH, CONDENSER_APP_PASSWORD, CONDENSER_SECRET_KEY
uv run pytest          # backend tests

# Dev backend (auto-reload, watcher scoped to the Python sources):
uv run uvicorn condenser.app:create_app --factory --reload --reload-dir condenser --port 8792
# Prod-style run (binds 0.0.0.0): uv run python -m condenser

cd frontend && pnpm install && pnpm dev   # proxies /api -> :8792 (CONDENSER_BACKEND overrides)
pnpm test                                 # vitest
pnpm build                                # -> frontend/dist, served by the backend

# Both panes at once: tmuxp load .tmuxp.yaml

# Log a browser session into the running dev app, for walkthroughs behind the auth gate:
scripts/dev-browser-login.sh [session] [--backend URL] [--frontend URL]
```

Before a UI walkthrough, check that the dev backend was started with `--reload`
(`ps -o command -p $(lsof -ti :8792 -sTCP:LISTEN)`), or the walkthrough verifies stale code.

### `scripts/`

Each script's header comment has its usage and rationale.

| Script | What it does |
|---|---|
| `x_verdict_backtest.py` | leave-one-out backtest of the verdict on real labels. Read-only except the KNN index, which it rebuilds at the end; `--embed-missing` is the only mode that calls an API. Reading its output: `kb/docs/x-verdict.md` |
| `x_verdict_prospective.py` | the online counterpart: scores only tweets judged before they were labeled. Fully read-only, safe on a live copy |
| `dev-browser-login.sh` | puts a logged-in session cookie into an `agent-browser` profile. The app password stays on stdin and never reaches a command line or a transcript |
| `opml_picker.py` | trims an OPML to a chosen subset through a localhost checkbox page. Stdlib only, never touches the DB |
| `demo_bootstrap.py` | initializes and health-checks the App Store review demo instance. Runbook: `demo-server.md` in the private KB |

## Documentation

`kb/docs/` describes the current state. `kb/plans/` holds the design record of each
feature, `kb/reviews/` the code review reports, `kb/sessions/` dated session summaries.

- `kb/docs/database.md` — table ownership, `init_db` ordering traps, migration
  conventions, schema changelog. Read before any schema work.
- `kb/docs/content-update-mechanism.md` — Telegram realtime push, backfill, the manual
  refresh / fetch-older / reset triggers, the enable toggle. Read before touching ingest
  or sync.
- `kb/docs/x-verdict.md` — the For You verdict: pipeline, channels A–D, vector
  infrastructure, the two evaluation scripts. Read before touching a verdict module.
- `kb/docs/x-feedback.md` — up / down labels and down-reason chips: API rules, chip UX on
  web and iOS, the `FEEDBACK_REASONS` taxonomy (pinned across `db.py`, `lib/sources.ts`
  and Kit by a test). Read before changing the feedback endpoints or the reason set.
- `kb/docs/probe.md` — the local X probe: xbird invariants, credentials, SeenCache,
  scheduling, inline article reads, the kickstart trap. Read before touching `probe/`.
- `kb/docs/frontend.md` — frontend cross-cutting behavior. Read before changing a
  behavior that spans components.
- `kb/docs/timeline-message-box-components.md` — anatomy of the Telegram `MessageCard`
  and its media sub-tree. Written 2026-06, before the HN / X / RSS cards and the detail
  pane existed. Read before restructuring `MessageCard`.
- `kb/docs/ios.md` — iOS feature history and design decisions. Read before iOS feature
  work.
- `kb/docs/status-and-gaps.md` — the dated work log, oldest first, so read from the tail.
  Consult it for the evidence behind a feature: measurements, deploy incidents, rejected
  designs. For what is true now, this file and the other docs are the authority.

⚠️ **凡是 app 审核/发布、服务器部署/运维相关的文档，一律写进私密 KB 仓库
`../kb.private/condenser/kb/<docs|plans|sessions>/`，不进本库。** 本库是公开仓库
（<https://github.com/reorx/condenser>），这类文档的价值在于记着具体值（Apple 账号标识、
生产主机与端口、审核表单），所以整份挪走，本库只留指针。判断标准见
`../kb.private/README.md`。已有的：

- `kb.private/condenser/kb/docs/ios-app-store-release.md` — iOS 发布全流程：关键资产、
  签名与出包链路、各 build 的状态、当前审核状态。做发布操作（传 build / 提审 / 出新版本）
  前读它。
- `kb.private/condenser/kb/docs/demo-server.md` — App Store 审核用的第二实例
  `condenser-demo.reorx.com`（只开 HN、无 Telegram 会话）。提审前必读：初始化与健康检查、
  审核表单填法、每次提审前的 checklist。
