---
created: 2026-08-21
tags:
  - database
  - sqlite
  - schema
  - migrations
---

# Database — ownership, initialization, schema changelog

One SQLite file, shared between [telememo](https://pypi.org/project/telememo/) (a PyPI
dependency) and condenser. condenser's peewee models bind to telememo's `db` instance, so
everything runs on one connection. `SCHEMA_VERSION` lives in `condenser/db.py` (currently
**15**).

## Table ownership

**telememo** owns `channels` / `messages` / `comments`. Two column groups on `messages`
deserve care:

- `media_width` / `media_height` — telememo-native, filled on ingest from
  `message.file.width/height` (frontend uses them to reserve image placeholder space;
  NULL on rows ingested before 2026-06-18).
- `is_filtered` — a **condenser overlay column**, a rebuildable keyword-filter cache.
  The extension-column contract: telememo write paths only touch native columns (never
  full-row `INSERT OR REPLACE`), so the overlay survives incremental edits.

**condenser** owns everything else:

| Group | Tables |
|---|---|
| Reader state | `read_items`, `saved_items`, `hidden_items`, `item_feedback` |
| Subscriptions & rules | `subscriptions`, `keyword_filters` |
| Source archives | `hn_stories`; `x_tweets`, `x_feed_items`, `x_following`; `rss_feeds`, `rss_entries` |
| Verdict / vector layer | `x_embeddings`, `x_attributes`, `x_vec_labeled` (sqlite-vec `vec0` virtual table) |
| Full-text search | `search_index` (FTS5 virtual table) |
| App state & infra | `tg_session`, `devices`, `app_meta`, `link_previews` |

## Initialization order (`condenser/db.py:init_db`)

`init_db()` initializes telememo tables (+ `is_filtered`), then condenser tables. Two
ordering constraints are load-bearing; both have bitten and both are pinned by regression
tests:

1. **`vectors.load()` runs before the migrations** (only the vec0 *table* waits until
   after `create_tables`). An `ALTER TABLE` makes SQLite reload the whole schema on the
   next statement, and a vec0 table it cannot parse reports that as
   `database disk image is malformed`.
2. **Shape-based `ADD COLUMN` migrations run before `create_tables`** (found in v14).
   peewee would otherwise create an index (e.g. `hnstory_qualified_at`) on a table that
   lacks the column — SQLite *accepts* that on a connection that has seen the table
   change, and the next write dies with `database disk image is malformed`.

Virtual tables (`x_vec_labeled`, `search_index`) are created with raw SQL in `init_db`
**after** the ordinary tables (and, for vec0, after the extension loads).

## Migration conventions

- **New table → plain `create_tables`**, no migration (v6, v7, v8, v10, v11, v15).
- **New column → shape-based `ALTER TABLE ADD COLUMN`** (v5, v9, v13, v14): inspect the
  live table, add what is missing. Historical rows stay NULL, and every reader treats
  NULL as "the pre-feature behavior".
- **Backfill, not migration** (v12, v14): when the new data is fully derived from
  existing rows, a rebuild replays the rule once. The backfill is a **separate,
  marker-keyed step** (a flag in `app_meta`), so a crash between shape change and
  backfill cannot leave the shape check satisfied but the data missing.
- **Rebuildable caches never migrate**: `is_filtered`, `x_embeddings`, `x_attributes`,
  `x_tweets.urls`, `search_index`. The source of truth is still in the archive; a rule
  change re-derives rather than migrates.
- **Identity tags instead of migrations** for derived data: vectors are comparable
  within `model_tag` = `name@dims`, attributes within `model@TAXONOMY_VERSION`, the
  search index within the integer `TOKENIZER_VERSION`. Change the identity → re-embed /
  re-read / rebuild; never rewrite old rows in place.
- **Docstring convention** (the `delete_channel_messages` precedent): retention/delete
  SQL names what is *intentionally preserved*, not only what is removed.

## Schema changelog (newest first)

### v15 — 2026-08-20 · RSS source

Adds `rss_feeds` + `rss_entries` (new tables, plain `create_tables`). The split mirrors
`x_feed_items` / `x_tweets`: `rss_feeds` (PK = the feed URL, which is also the
subscription's `channel_id` — what the reader typed is the key, the X-handle precedent)
is machine state rewritten every poll round (`etag` / `last_modified` validators,
`fetched_at`, a `last_error` / `error_count` streak); the subscription row is the
reader's decision.

- `rss_entries.id` is a **surrogate** (the item key's ref1): a feed's `guid` is only
  unique within its feed and is a string of arbitrary shape. Uniqueness lives on
  `(feed_url, guid)`; ingest is insert-if-absent on it.
- `guid` falls back three ways — `<guid>`/`<id>` → `link` → `sha256(title+published)` —
  and an entry with none of them is dropped rather than archived under a hash of nothing.
- `published_at` is stored **verbatim**, missing or absurd; clamping is a read-side
  concern (`sources/rss.SORT_AT_SQL`), so the archive keeps the evidence.
- `summary` / `summary_model` / `summary_attempts`: the LLM summary denormalized onto
  the entry (the `hn_stories.preview` precedent), written by Phase 3.

### v14 — 2026-08-14 · HN admission stamp

Adds `hn_stories.qualified_at` / `qualified_rank`. Timeline membership becomes an
**event written down once** instead of a predicate re-evaluated per request: the read
path is `WHERE qualified_at IS NOT NULL ORDER BY qualified_at DESC`, so "became visible"
and "sits at" are the same instant by construction.

- Admission is **one-way**. The old query-time rank let a story vanish after being read,
  and made a late climber appear *behind* the reader's cursor — unreachable by paging,
  invisible to `/timeline/new`.
- Upgrade is a **backfill** (`sources/hn.stamp_history`, marker
  `app_meta.hn_qualified_backfilled`): replays the old rule once, stamping each story at
  its own `first_seen_at`. Verified on a production snapshot — 316 items identical in
  order and badge.
- ⚠️ Source of both ordering traps in "Initialization order" above: the ADD COLUMN must
  precede `create_tables`, and the backfill is marker-keyed separately from the shape
  check. Both have regression tests.

### v13 — 2026-08-10 · t.co expansion

Adds `x_tweets.urls` (shape-based ADD COLUMN): a JSON list
`[{url, expanded_url, display_url, indices}]` — the metadata X's own UI uses to render
the original link in place of the rewritten t.co (xbird 1.2.0 `entities.urls`).

- A **rebuildable derived column**: `raw` archives the entities, so any row can be
  re-extracted (`tmp/backfill_x_urls.py` did exactly that for the 8 rows pushed by an
  upgraded-but-undeployed probe).
- Historical rows stay NULL = "keep the t.co", per entry — degradation is per-link,
  never per-page.

### v12 — 2026-08-09 · Full-text search

Adds `search_index`, an **FTS5 virtual table** (raw SQL in `init_db` after the ordinary
tables — the vec0 precedent): one indexed `text` column with the pre-tokenized document,
plus the `items.py` triple and a sort timestamp as `UNINDEXED` columns.

- One row per **item**, keyed the way `saved_items` is — a Telegram album is indexed
  once under its display anchor, so queries need no de-duplication.
- Upgrade is a **backfill** (`search.ensure_index`): everything in the table is derived
  from the source tables. Measured 80ms at 2630 items (~0.3s extrapolated to
  production), so it runs inline at startup.
- Tokenizer + query semantics live in `search.py` (see the module table in AGENTS.md);
  `TOKENIZER_VERSION` bumps trigger a rebuild — including for a **new source** (4: RSS,
  2026-08-20), since an archive predating a source is missing from the index just as
  silently as a tokenizer change makes it wrong.

### v11 — 2026-07-30 · X Following

Adds `x_following` (new table): the accounts the user follows, pushed by the probe (a
paged follow crawl) and **replaced whole** every sync — an unfollowed account has to
*disappear*, which no incremental merge expresses.

- Exists for ad filtering: the Following timeline carries injected ads that are
  structurally indistinguishable from ordinary tweets (bird dumps the tweet result, not
  the timeline entry, so `promotedMetadata` never arrives; the structural markers hit
  0/20), while the follow-list test caught 7 of 7 with no false positive.
- A table rather than an `app_meta` blob: every ingest round reads it, and "is this
  author someone I follow" is a zero-cost prior for verdict channel A (still a TODO).
- The sync *timestamp* lives in `app_meta.x_following_synced_at`, not `max(synced_at)`:
  a sync that produced zero rows is still a sync, and reading the rows would re-crawl
  forever.

### v10 — 2026-07-28 · X attributes (判定 v2 step 2)

Adds `x_attributes` (new table): the LLM-read `topics` / `style_flags` per tweet, keyed
by `model@taxonomy`. A rebuildable cache in the `x_embeddings` spirit — the text is
still in `x_tweets`, so a taxonomy edit re-reads rather than migrates. Extraction and
scoring live in `attributes.py` (channel C — see `kb/docs/x-verdict.md`).

### v9 — 2026-07-26 · Down-reason chips

Adds `item_feedback.reason` (shape-based ADD COLUMN): the optional one-tap chip behind a
thumbs-down, naming *which attribute* earned it (`topic` / `promo` / `ai_slop` /
`author`; a closed set validated at the endpoint — `engagement_farming` joined
2026-07-27 as a constant-only change, no schema bump).

- Why: a bare down labels the whole tweet while the cause is usually one instance in it,
  and one embedding averages topic, tone and author into a single point — "I hate this
  phrasing" is indistinguishable from "I hate this topic" to a dense kNN. The chip lets
  a multi-channel model **route** the label instead of averaging it
  (`kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md`).
- Pre-chip labels stay NULL: they *were* bag-level, and inventing a reason would invent
  data.
- Product surface and safety rules: `kb/docs/x-feedback.md`.

### v8 — 2026-07-25 · Vector layer (X Phase 4)

Purely additive:

- `x_embeddings` (`tweet_id` PK, float32 BLOB, `model` = `name@dims`, `created_at`) —
  the **storage of record** for vectors, and a rebuildable cache in the `is_filtered`
  spirit: the text stays in `x_tweets`, any row can be re-embedded.
- `x_vec_labeled` — a **sqlite-vec `vec0` virtual table** holding only the *labeled* set
  (hundreds of rows); raw SQL in `init_db` after the extension loads (`vectors.setup`,
  which also drops+recreates it when `CONDENSER_EMBEDDING_DIMENSIONS` changes).

Two properties decided sqlite-vec over an external vector DB: the index lives in the
same file (backup stays "copy one file"), and vec0 shadow tables **join the surrounding
transaction**, so a label and its vector cannot drift apart. Unlabeled vectors are
pruned after `CONDENSER_EMBEDDING_RETENTION_DAYS`; labeled ones are the training set and
stay.

### v7 — 2026-07-24 · X source (Phase 1)

Three new tables, plain `create_tables`:

- `x_tweets` — the tweet archive: author, text, `created_at`, media/metrics/article
  JSON, `quote_of` self-reference, `rt_of_handle`, and `raw` = the probe's entry
  verbatim (that JSON tracks X's internal API and is not a stable contract).
- `x_feed_items` (`(channel_id, tweet_id)` PK) — a tweet's *appearance in one feed*,
  with the sticky `first_seen_at` sort key and the Phase-4 `verdict` / `verdict_meta`
  columns. Split from the body because one tweet can appear in both For You and a
  followed account's feed, while a verdict belongs only to the For You appearance.
- `item_feedback` — source-generic up/down, triple-keyed like `hidden_items`; written
  since Phase 3 (2026-07-25). One row per item, so switching sides is a correction and
  undo deletes the row. **Not** album-expanded, unlike read/hide markers: a label
  belongs to the display unit the reader judged.

### v6 — 2026-07-22 · Hidden items

Adds `hidden_items` (new table): triple-keyed per-item "never show again" markers.

- TG rows are stored **album-expanded** (one row per raw sibling id, mirroring
  `mark_read`) so per-row anti-joins remove whole display units.
- Every timeline surface (pages, `/timeline/new`, day counts, unread counts) anti-joins
  it — hiding is server-enforced for web *and* iOS. HN exclusion happens **after**
  day-ranking, so hiding a top-N story never promotes a below-cut one.
- API: `POST /api/hidden {key}` / `DELETE /api/hidden/{key}` (undo). Saved records keep
  hidden items — they are user assets.

### v5 — 2026-07-20 · HN link previews

Adds `hn_stories.preview` / `preview_attempts` (the first shape-based ADD COLUMN — "the
v5 pattern"): the story URL's `LinkPreview` JSON, denormalized into the archive so it
outlives the TTL'd `link_previews` cache.

### v4 — 2026-07-19 · Source-generic read/saved (multi-source Phase 2)

`read_items` / `saved_items` get the triple PK `(source, ref1, ref2)` — TG
`(channel_id, message_id)`, HN `(story_id, 0)`. A shape-based migration copies
`read_messages` / `telegram_records` and keeps them as `*_legacy` for one version. The
API currency is the item-key string (`tg:{cid}:{mid}` / `hn:{sid}`, see `items.py`).

### v3 — 2026-07-19 · Multi-source subscriptions (multi-source Phase 1)

`subscriptions` gets a composite PK `(source, channel_id)`; `channel_id` becomes a
`BareField` (TG rows store an int, HN rows a feed-key string — v1 only `'front'`), plus
`name` / `config` columns. A shape-based migration in `db.init_db` rebuilds pre-v3
tables. All TG CRUD + timeline JOINs scope `source='telegram'`.
