# Condenser — Agent Overview

Self-hosted, single-user **timeline reader** in the Google Reader mold. It federates
**four sources** — Telegram channels, Hacker News, X (through a local probe) and RSS —
into one timeline, read from a web frontend and a native iOS / Mac Catalyst app.
`spec.md`, `draft.md` and `M2.md` date from the Telegram-only era; treat them as history.

**A push to master is a production deploy** when it touches what the image consumes:
`condenser/`, `frontend/` (minus tests, preview and docs), `pyproject.toml`, `uv.lock`,
`Dockerfile`. GitHub Actions builds the image and a webhook deploys it to
<https://condenser.reorx.com>. Pushes that only touch `kb/`, `ios/`, `probe/`, `tests/`,
`scripts/` or docs skip the build; `workflow_dispatch` is the manual rebuild. The exact
list is `paths` in `.github/workflows/deploy.yml`. Host-side details live in the deploy
workspace (Ansible role `condenser`).

## Architecture

One Python process: FastAPI plus a Telethon MTProto **user-account** client (a ToS gray
area) on one asyncio loop, with the managers on `app.state` (`tg` / `hn` / `rss` /
`verdict` / `cleanup`). It shares **one SQLite file** with telememo, a PyPI dependency.
condenser's peewee models bind to telememo's `db`, so everything is one connection.

- **telememo** owns `channels` / `messages` / `comments`. condenser adds one overlay
  column, `messages.is_filtered`, a rebuildable keyword-filter cache.
- **condenser** owns the rest (`SCHEMA_VERSION` 21). Reader state is keyed by the
  `(source, ref1, ref2)` triple: `read_items`, `saved_items`, `hidden_items`,
  `item_feedback`, and `forward_records` (a log, one row per publish). Beside it sit
  `subscriptions`, `keyword_filters`, the source archives (`hn_stories`, `x_*`, `rss_*`),
  the verdict layer (`x_embeddings`, `x_attributes`, sqlite-vec `x_vec_labeled`), the
  FTS5 `search_index`, and app state (`tg_session`, `devices`, `app_meta`,
  `link_previews`).
- A `saved_items` row exists ⟺ saved ∨ note ∨ annotations, so unsaving keeps an annotated
  row.

⚠️ `db.init_db()` has two load-bearing ordering constraints: `vectors.load()` before the
migrations, and shape-based `ADD COLUMN`s before `create_tables`. Get either wrong and
SQLite reports `database disk image is malformed`. Read `kb/docs/database.md` before
adding tables or columns, writing a migration, or touching `init_db`.

## Key modules (`condenser/`)

Each row gives the role and what must not break. The full story of a module is its
docstring and inline comments; read them before editing. A feature's design record is a
dated file in `kb/plans/`, named after the feature.

### Core and API

| File | Role |
|---|---|
| `config.py` / `crypto.py` | env settings (`CONDENSER_*`) / Fernet session encryption and signed cookies from `CONDENSER_SECRET_KEY` |
| `app.py` | FastAPI factory + lifespan. `SPAStaticFiles` serves `frontend/dist` with an index.html fallback for client routes (unknown `/api/*` still 404). `SelectiveGZipMiddleware` leaves image / video / audio / font responses uncompressed |
| `auth.py` + `routers/` | every endpoint sits behind `require_auth`: app-password cookie **or** device Bearer token (stored as sha256, issued on the web `/authorize` page). Device management is cookie-only. Key-driven endpoints parse through `routers/common.py:parse_key_or_422` |
| `db.py` | condenser's tables, CRUD and `init_db`. **All SQL lives here**, retention sweeps included. A destructive function's docstring names what it *intentionally preserves* |

### Items, timeline, reader state

| File | Role |
|---|---|
| `items.py` | item keys (`tg:{cid}:{mid}` / `hn:{sid}` / `x:{tweet_id}` / `rss:{entry_id}` ↔ the stored triple) and the **envelope** `{source, key, datetime, is_read, is_saved, <source payload>}` every list surface shares. X ids cross the API as **strings**. RSS entries and X articles come in two sizes: lists carry `content_excerpt` / `article.has_content`, the body comes only with `with_content=True` (detail endpoints, snapshots) |
| `timeline.py` + `sources/` | federated merge: each provider returns `SourceUnit` pages, k-way merged by timestamp under a composite cursor `base64(json {source: pos})`. A source absent from the cursor restarts from its top; an invalid cursor is a 422. `query_new` / `query_new_count` back the new-content poll and the iOS pill |
| `filters.py` | materializes keyword filters into `messages.is_filtered` on ingest and on rule change; the timeline query only reads the column. Latin keywords match whole words through a custom edge (CJK counts as a boundary, so `\b` is wrong here), CJK matches anywhere, `*` opens an end. Bump `MATCHER_VERSION` when the semantics change, and `init_db` rematerializes every archived channel. Plan: `kb/plans/2026-10-25-keyword-filter-word-boundary.md` |
| `records.py` | saved records: snapshots in `saved_items.raw_data`, plus item notes and annotations. A snapshot must render **without its source tables**, since retention deletes them, so it carries the article body and computed fields such as RSS `sort_at`. `build_item_snapshot` is shared with forwards |
| `forwards.py` / `forward.py` | the forward log's read side (`/forwards`, the `forwarded_by_me` stamp) / rendering a non-Telegram item into a Telegram message. ⚠️ `forwarded_by_me` is not `is_forwarded`, Telegram's flag for the opposite direction. The write, `tg.forward_item`, **deliberately swallows** a failed record write and answers `recorded: false`: the message is already sent, and a 500 would make the client retry and post it twice |
| `search.py` | the only module that knows FTS5. CJK runs are bigram-tokenized in Python and phrase-queried. The index is a rebuildable cache: bump `TOKENIZER_VERSION` when the tokenizer or any source's indexed document changes |
| `preview.py` | link previews for any source: fetch + metadata extraction, the `link_previews` cache, image fetch for the proxy |

### Sources

| File | Role |
|---|---|
| `tg.py` | `TgManager`: lifecycle, step login with encrypted session storage, realtime ingest, backfill, subscriptions, forwarding. Read `kb/docs/content-update-mechanism.md` before touching ingest or sync |
| `hn.py` + `sources/hn.py` + `routers/hn.py` | `HNManager` samples the front page into `hn_stories` once an HN subscription exists. Admission is **one-way** and stored (`qualified_at`); the read path never re-ranks. The config PATCH **merges** into `sub_config`, because three admission knobs share the column |
| `x.py` + `sources/x.py` + `routers/x.py` | **push model**: the server never talks to X, the local probe pushes JSON. Parsing is tolerant and raw JSON is archived for re-parsing. The ad, age and language filters fail open. Dedup priority is account > Following > For You. For You sorts by `first_seen_at` and joins the aggregate only per its `aggregate` config (`none` \| `positive` \| `all`), which `bulk_read_scope` shares. A bodiless re-push must not wipe a stored article body (`article_detail`). 503 when `CONDENSER_X_ENABLED=false` |
| `rss.py` + `sources/rss.py` + `routers/rss.py` | `RssManager` polls with conditional requests. Lists ship a 500-char `content_excerpt` and the body comes from `GET /api/rss/entries/{id}`, so keep the list select's explicit column list. `sort_at` is computed in SQL and never stored. Failing feeds back off exponentially up to a week and get marked `abnormal`, never auto-paused. An all-301/308 redirect migrates the feed's URL key. PATCH / DELETE key a feed by `?url=` |
| `summary.py` / `hn_summary.py` | billed LLM summaries for RSS entries / HN stories, run at the tail of each polling round: one request per item under a per-round cap. `CONDENSER_SUMMARY_API_KEY` is the on switch for both, with no fallback key; HN adds `CONDENSER_HN_SUMMARY_ENABLED`. `summary_model` is provenance and also carries the `skip:short` / `skip:empty` sentinels |
| `xarticle.py` / `text.py` | X Article Markdown → HTML (raw HTML escaped) / feed HTML → plain text and excerpt. Both have **no package imports**, because `items.py` depends on them. ⚠️ `text._drop_noise` is a hand-written scan: the obvious regex is quadratic on unclosed tags |
| `cleanup.py` | daily retention sweep (X and RSS rules) and the VACUUM decision, on a worker thread. It wakes hourly against a timestamp in `app_meta`, since deploys restart the process too often for a timer. `GET /api/cleanup/status` reports the last round |

### X For You verdict

`verdict.py` is the pipeline on `app.state.verdict`, kicked by ingest: an ensemble of
enabled and shadow channels (`CONDENSER_VERDICT_CHANNELS`, default `b`) behind cold-start
and OOD gates. Channel A is `authors.py` (author prior), B the kNN inside `verdict.py`,
C `attributes.py` (LLM attributes, billed), D `ngram.py` (**not wired** into the running
verdict). `channels.py` holds the shared vocabulary and the combiners: abstain is `None`,
never 0.0. `vectors.py` is the only module that knows sqlite-vec, `embedding.py` the
embeddings client; without an embedding key the whole pipeline stays inert.
`prospective.py` measures precision online. Read `kb/docs/x-verdict.md` before touching
any of these or the verdict scripts.

### Purifier (iOS reading proxy)

| File | Role |
|---|---|
| `purifier.py` + `purifier_html.py` + `routers/purifier.py` | `GET /p/<host>/<path>` returns a page that depends on nothing but condenser: scripts dropped, assets rewritten to `/pa/…`, links to `/p/…`. Modes: `proxy`, `readable` (default), and `puremd` as fallback only. HTML is walked with lxml, never regexed. `/p` and `/pa` accept only the reader cookie (minted from a 5-minute ticket, bound to a device that must still exist) or the session cookie, never Bearer. Every security fix is pinned by a test; read `kb/reviews/2026-09-07-purifier-code-review.md` and `kb/plans/2026-09-07-purifier.md` before editing the sanitizer, URL parsing or the host guard |
| `purifier_x.py` | X status links are **built** from FxEmbed's anonymous JSON API rather than fetched; the only module that knows FxEmbed. `CONDENSER_PURIFIER_X_API_BASE` empty turns it off, and `/p` then 302s to the original. iOS `isPurifierExcluded(host:path:)` mirrors the URL rule |

## Conventions & gotchas

- **Extension-column contract**: telememo's write paths touch only native columns, so
  `is_filtered` survives edits. Never use a full-row `INSERT OR REPLACE` in telememo.
- **Rebuildable caches are rebuilt, never migrated**: `is_filtered`, `search_index`,
  `x_embeddings` / `x_vec_labeled`.
- **Billed components are fenced**: channel C runs only with `CONDENSER_ATTR_API_KEY`
  set, the two summary pipelines only with `CONDENSER_SUMMARY_API_KEY`, each under a
  per-round cap. Never add a fallback to another key, or deploying code starts spending.
- **Tests never touch the network**: Telegram is mocked, and HN / RSS / summary HTTP goes
  through injectable functions (`fetch_json`, `fetch_feed`). RSS parsing is deliberately
  not injectable.
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
- **Resolve Telegram peers through `tg._channel_handle`**, which prefers `@username`: a
  StringSession does not persist the entity cache, so `get_entity(int)` fails after a
  restart for peers not met in this process.
- **Realtime ingest never waits on Telegram**: forward source names resolve there with
  `allow_network=False`, and only backfill may fall through to `get_entity`. Both
  Telegram rules are spelled out in `kb/docs/content-update-mechanism.md`, "Invariants &
  gotchas".

## telememo (`../telememo`, separate git repo)

Owns the Telegram fetch and storage layer: `TelegramService` (`service.py`), `db.py`,
`telegram.py` converters, `entity_cache.py`. An edited message updates its row in place
(`save_message_smart`). It has its own `AGENTS.md`. To co-develop against a local
checkout, use the editable overlay in the README section "Co-developing telememo
locally".

## Frontend (`frontend/`)

React 19 + Vite + TypeScript + Tailwind v4 + shadcn/ui + TanStack Query, pnpm.
`frontend/AGENTS.md` is the one-line-per-module inventory and the UI verification loop.
`kb/docs/frontend.md` is the behavior that spans components (auth gate, scroll-to-read,
detail pane, cache mutation rules, …); read it before changing one.

`lib/types.ts` mirrors the backend JSON. Change both sides together, and check the iOS
Kit models, since shipped builds decode the same payloads.

## Local probe (`probe/`)

An independent uv package (`condenser-probe`) that runs on the user's own machine: the X
source's fetch half, since X data exists only inside a logged-in browser session. Each
round reads the feeds the server's `probe-config` asks for through `xbird` and POSTs
them to ingest. `watch` is the long-running mode a launchd agent keeps alive, so
**deploying the probe is `launchctl kickstart`, not `git push`**. A probe left running on
old code is the usual cause of a silent feature.

Read `kb/docs/probe.md` before touching `probe/` or debugging a silent X feed.

## iOS app (`ios/`)

Native SwiftUI client built from the CLI (xcodegen + Makefile): `CondenserKit/` is a local
SPM package of pure logic with tests, `Condenser/` the app target, which also builds as a
**Mac Catalyst** app. `ios/AGENTS.md` has the commands and conventions; `kb/docs/ios.md`
has the feature history and design decisions, read it before iOS feature work.

What backend work must know:

- **Shipped builds decode the API as it was when they were built.** Add fields beside
  existing ones rather than changing their shape (`feedback_reason` sits next to
  `feedback` for this reason). A client that meets an unknown source draws blank rows,
  which is why `CONDENSER_RSS_ENABLED` defaults to false.
- The app is not on the App Store yet; builds go out through TestFlight. Before any
  release operation, read `ios-app-store-release.md` in the private KB.

## Dev

```bash
uv sync --extra dev    # telememo comes from PyPI; no ../telememo checkout needed
cp .env.example .env   # fill TELEGRAM_API_ID/HASH, CONDENSER_APP_PASSWORD, CONDENSER_SECRET_KEY
uv run pytest          # backend tests

# Dev backend (auto-reload, watcher scoped to the Python sources):
uv run uvicorn condenser.app:create_app --factory --reload --reload-dir condenser --port 8792
# Prod-style run (binds 0.0.0.0): uv run python -m condenser

cd frontend && pnpm install && pnpm dev   # proxies /api -> :8792 (CONDENSER_BACKEND overrides)
# pnpm dev is portless: it claims condenser.localhost (app port 5792). A second instance
# for a parallel walkthrough runs `pnpm exec vite --port N` so it can't take that name.
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
| `x_verdict_backtest.py` | leave-one-out backtest of the verdict on real labels. Read-only except the KNN index, which it rebuilds at the end; `--embed-missing` is the only mode that calls an API |
| `x_verdict_prospective.py` | the online counterpart, fully read-only and safe on a live copy |
| `dev-browser-login.sh` | puts a logged-in session cookie into an `agent-browser` profile. The app password never reaches a command line or a transcript |
| `opml_picker.py` | trims an OPML to a chosen subset through a localhost checkbox page. Never touches the DB |
| `demo_bootstrap.py` / `demo_tg_snapshot.py` | the App Store review demo instance: initialize and health-check it / give it Telegram content without an account (public `t.me/s/` previews written as backfill rows, run inside the demo container). Runbook: `demo-server.md` in the private KB |

## Documentation

`kb/docs/` describes the current state. `kb/plans/` holds the design record of each
feature, `kb/reviews/` the code review reports, `kb/sessions/` dated session summaries
(new work records go there). In `kb/docs/`:

- `database.md` — table ownership, `init_db` ordering traps, migration conventions,
  schema changelog (v3–v21). Read before any schema work.
- `content-update-mechanism.md` — Telegram realtime push, backfill, the manual refresh /
  fetch-older / reset triggers. Read before touching ingest or sync.
- `x-verdict.md` — the For You verdict and how to read its two evaluation scripts.
- `x-feedback.md` — up / down labels, down-reason chips and the `FEEDBACK_REASONS`
  taxonomy (pinned across `db.py`, `lib/sources.ts` and Kit by a test). Read before
  changing the feedback endpoints or the reason set.
- `probe.md` — the local X probe: xbird invariants, credentials, scheduling.
- `frontend.md` — frontend behavior that spans components.
- `timeline-message-box-components.md` — anatomy of the Telegram `MessageCard`, written
  2026-06 before the HN / X / RSS cards and the detail pane existed. Read before
  restructuring it.
- `ios.md` — iOS feature history and design decisions.
- `status-and-gaps.md` — the work log up to 2026-09-19, now frozen. Consult it for the
  evidence behind a feature (measurements, deploy incidents, rejected designs); its
  "still open" lines are historical.

What is still open: `kb/known-issues.md` (open problems and unverified items),
`kb/next-up.md` (dated checks), `kb/todo.md` (deferred features). Check `known-issues.md`
before working on an area, and `next-up.md` for items that have come due.

⚠️ **app 审核/发布、服务器部署/运维的文档，一律写进私密 KB
`../kb.private/condenser/kb/<docs|plans|sessions>/`，不进本库。** 本库是公开仓库，这类文档记着
具体值（Apple 账号标识、生产主机与端口、审核表单），整份挪走，本库只留指针。判断标准见
`../kb.private/README.md`。已有的两份在该目录的 `docs/` 下：

- `ios-app-store-release.md` — iOS 发布全流程、各 build 状态、当前审核状态。做发布操作前
  读它。
- `demo-server.md` — App Store 审核用的第二实例 `condenser-demo.reorx.com`（HN + RSS +
  Telegram 快照，无 Telegram 会话）。提审前必读。
