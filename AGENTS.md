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
- condenser owns `subscriptions` / `keyword_filters` / `read_items` / `saved_items`
  / `hidden_items` / `tg_session` / `app_meta` / `hn_stories` (the user's assets + app state).
  `read_items` / `saved_items` are **source-generic since SCHEMA_VERSION 4** (2026-07-19,
  multi-source Phase 2): triple PK `(source, ref1, ref2)` — TG `(channel_id, message_id)`,
  HN `(story_id, 0)`; a shape-based migration copies `read_messages` / `telegram_records`
  and keeps them as `*_legacy` for one version. The API currency is the item-key string
  (`tg:{cid}:{mid}` / `hn:{sid}`, see `items.py`).
  `subscriptions` is **multi-source since SCHEMA_VERSION 3** (2026-07-19): composite PK
  `(source, channel_id)`, `channel_id` is a `BareField` (TG rows store int, HN rows a feed
  key str — v1 only `'front'`), plus `name` / `config` columns; a shape-based migration in
  `db.init_db` rebuilds pre-v3 tables. All TG CRUD + timeline JOINs scope `source='telegram'`.
  **SCHEMA_VERSION 5** (2026-07-20) adds `hn_stories.preview` / `preview_attempts`
  (shape-based `ALTER TABLE ADD COLUMN` migration): the story URL's `LinkPreview` JSON,
  denormalized into the archive so it outlives the TTL'd `link_previews` cache.
  **SCHEMA_VERSION 6** (2026-07-22) adds `hidden_items` (new table, no migration needed):
  triple-keyed per-item "never show again" markers; TG rows are stored **album-expanded**
  (one row per raw sibling id, mirroring `mark_read`) so per-row anti-joins remove whole
  display units. Every timeline surface (pages, `/timeline/new`, day counts, unread counts —
  both sources) anti-joins it, so hiding is server-enforced for web *and* iOS; HN exclusion
  happens **after** day-ranking, so hiding a top-N story never promotes a below-cut one.
  API: `POST /api/hidden {key}` / `DELETE /api/hidden/{key}` (undo). Saved records keep
  hidden items (user assets).
  **SCHEMA_VERSION 7** (2026-07-24, X source Phase 1) adds three tables, all new (the
  upgrade is plain `create_tables`, no data migration): `x_tweets` (the tweet archive —
  author, text, `created_at`, media/metrics/article JSON, `quote_of` self-reference,
  `rt_of_handle`, and `raw` = the probe's entry verbatim, because that JSON tracks X's
  internal API and is not a stable contract), `x_feed_items` (`(channel_id, tweet_id)` PK
  — a tweet's appearance in one feed, with the sticky `first_seen_at` sort key and the
  Phase-4 `verdict` / `verdict_meta` columns; split from the body because one tweet can
  appear in both For You and a followed account's feed while a verdict only belongs to the
  For You appearance), and `item_feedback` (source-generic up/down, triple-keyed like
  `hidden_items`; **written since Phase 3**, 2026-07-25 — one row per item, so switching
  sides is a correction and the undo click deletes it. NOT album-expanded, unlike
  read/hide markers: a label belongs to the display unit the reader judged).
  **SCHEMA_VERSION 8** (2026-07-25, X source Phase 4) adds the vector layer, again
  purely additive: `x_embeddings` (`tweet_id` PK, float32 BLOB, `model` = `name@dims`,
  `created_at`) is the **storage of record** for vectors — a rebuildable cache in the
  spirit of `is_filtered`, since the text is still in `x_tweets` and any row can be
  re-embedded; and `x_vec_labeled`, a **sqlite-vec `vec0` virtual table** holding only
  the *labeled* set (hundreds of rows), created with raw SQL in `init_db` **after** the
  extension loads (`vectors.setup`, which also drops+recreates it when
  `CONDENSER_EMBEDDING_DIMENSIONS` changes). Two properties decided sqlite-vec over an
  external vector DB: the index lives in the same file (backup stays "copy one file")
  and vec0 shadow tables **join the surrounding transaction**, so a label and its vector
  cannot drift apart. Unlabeled vectors are pruned after
  `CONDENSER_EMBEDDING_RETENTION_DAYS`; labeled ones are the training set and stay.
  **SCHEMA_VERSION 9** (2026-07-26, the X Phase 3 make-up) adds `item_feedback.reason`
  — the optional one-tap chip behind a thumbs-down, saying *which attribute* earned it
  (`topic` / `promo` / `ai_slop` / `author`, a closed set validated at the endpoint).
  A bare down labels the whole tweet while the cause is usually one instance in it, and
  one embedding averages topic, tone and author into a single point — so "I hate this
  phrasing" is indistinguishable from "I hate this topic" to a dense kNN. The chip is
  what lets a later multi-channel model route the label instead of averaging it
  (`kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md`); nothing reads it yet.
  Shape-based `ALTER TABLE ADD COLUMN` (the v5 pattern); pre-chip labels stay NULL,
  because they *were* bag-level and inventing a reason would invent data.
  **SCHEMA_VERSION 10** (2026-07-28, 判定 v2 step 2) adds `x_attributes`: the LLM-read
  `topics` / `style_flags` per tweet, keyed by `model@taxonomy`. A new table, so the
  upgrade is plain `create_tables` — and a rebuildable cache in the `x_embeddings` spirit,
  since the text is still in `x_tweets` and a taxonomy edit re-reads rather than migrates.
  **SCHEMA_VERSION 11** (2026-07-30, X Following) adds `x_following`: the accounts the
  user follows, pushed by the probe (a paged follow crawl) and replaced whole on every
  sync — an unfollowed account has to *disappear*, which no incremental merge expresses.
  A new table, so again plain `create_tables`. It exists because the Following timeline
  carries injected ads that are structurally indistinguishable from ordinary tweets (bird
  dumps the tweet result, not the timeline entry, so `promotedMetadata` never arrives;
  `promoted`/`advertiser`/`socialContext` hit 0/20), while the author caught 7 of 7 with
  no false positive. A table rather than an `app_meta` blob because every ingest round
  reads it — and because "is this author someone I follow" is a zero-cost prior channel A
  is currently blind to (`authors.py`, still a TODO). The sync *timestamp* lives in
  `app_meta` (`x_following_synced_at`), not in `max(synced_at)`: a sync that produced zero
  rows is still a sync, and reading the rows would re-crawl forever.
  **SCHEMA_VERSION 12** (2026-08-09, full-text search) adds `search_index`, an **FTS5
  virtual table** created with raw SQL in `init_db` after the ordinary tables (the vec0
  precedent): one indexed `text` column holding the pre-tokenized document, plus the
  `items.py` triple and a sort timestamp as `UNINDEXED` columns. One row per **item**, keyed
  the way `saved_items` is — so a Telegram album is indexed once under its display anchor and
  needs no query-time de-duplication. The upgrade is a **backfill, not a migration**
  (`search.ensure_index`), because nothing in the table is not derived from the source
  tables; measured on a real v11 dev database, the whole rebuild is 80ms at 2630 items and
  ~0.3s extrapolated to production, so it runs inline at startup.
  **SCHEMA_VERSION 13** (2026-08-10, t.co expansion) adds `x_tweets.urls` — a JSON list
  `[{url, expanded_url, display_url, indices}]`, the metadata X's own UI uses to render the
  original link in place of the rewritten t.co (xbird 1.2.0 `entities.urls`; shape-based
  `ALTER TABLE ADD COLUMN`, the v5/v9 pattern). A **rebuildable derived column** in the
  `is_filtered` spirit: `raw` archives the entities, so any row can be re-extracted
  (`tmp/backfill_x_urls.py` did exactly that for the 8 probe-upgraded-but-undeployed
  window rows on 2026-08-10). Historical rows stay NULL, which every renderer treats as
  "keep the t.co" per entry — the degradation path is per-link, not per-page.
  **SCHEMA_VERSION 14** (2026-08-14, HN admission) adds `hn_stories.qualified_at` /
  `qualified_rank` — the admission stamp. It turns "which stories are on the timeline" from a
  predicate re-evaluated on every request into an **event that happened once and was written
  down**, so the read path is `WHERE qualified_at IS NOT NULL ORDER BY qualified_at DESC` and
  "became visible" and "sits at" are the same instant by construction. Admission is **one-way**:
  the old query-time rank let a story vanish after it had been read, and made a story that
  climbed into the cut appear *behind* the reader's cursor, where paging cannot reach it and
  `/timeline/new` could never report it. The upgrade is a **backfill, not a migration**
  (`sources/hn.stamp_history`, marker `app_meta.hn_qualified_backfilled`): it replays the old
  rule once and stamps each story it would have shown at that story's own `first_seen_at`, so
  the deploy is invisible — verified on a production snapshot, 316 items identical in order and
  badge. ⚠️ Two ordering traps, both measured, both now with regression tests: the ADD COLUMN
  runs **before `create_tables`** (peewee would otherwise create `hnstory_qualified_at` on a
  table lacking the column — SQLite *accepts* that on a connection that has seen the table
  change, and the next write dies with `database disk image is malformed`), and the backfill is
  a **separate marker-keyed step**, so a crash between the two cannot leave the shape check
  satisfied and the timeline permanently empty.
  **SCHEMA_VERSION 15** (2026-08-20, the RSS source) adds `rss_feeds` and `rss_entries` —
  two new tables, so the upgrade is plain `create_tables`. The split mirrors
  `x_feed_items` / `x_tweets`: `rss_feeds` (PK = the feed URL, which is also the
  subscription's `channel_id` — what the reader typed is the key, the X-handle precedent)
  is machine state rewritten every poll round (`etag` / `last_modified` validators,
  `fetched_at`, a `last_error` / `error_count` streak), while the subscription row is the
  reader's decision. `rss_entries` has a **surrogate** `id` (the item key's ref1) because a
  feed's `guid` is only unique within its feed and is a string of arbitrary shape;
  `(feed_url, guid)` carries the uniqueness and ingest is insert-if-absent on it. `guid`
  itself falls back three ways — `<guid>`/`<id>` → `link` → `sha256(title+published)` —
  and an entry with none of them is dropped rather than archived under a hash of nothing.
  `published_at` is stored **verbatim**, missing or absurd: clamping it against
  `first_seen_at` is a read-side concern (`sources/rss.SORT_AT_SQL`), so the archive keeps
  the evidence. `summary` / `summary_model` / `summary_attempts` are the LLM summary
  denormalized onto the entry (`hn_stories.preview`'s precedent), written by Phase 3.

condenser's peewee models bind to telememo's `db` instance, so everything is one connection.
`condenser/db.py:init_db()` initializes telememo tables (+ `is_filtered`) then condenser tables.
⚠️ `vectors.load()` runs **before the migrations** (only the vec0 *table* waits until after
`create_tables`): an `ALTER TABLE` makes SQLite reload the whole schema on the next statement,
and a vec0 table it cannot parse reports that as `database disk image is malformed` too.

## Key modules (`condenser/`)

| File | Role |
|---|---|
| `config.py` / `crypto.py` | env settings; Fernet session encryption + signed cookie from `CONDENSER_SECRET_KEY` |
| `db.py` | condenser tables (peewee, bound to telememo's db) + CRUD + shared `init_db`. Also the retention SQL `cleanup.py` calls (`sweep_x_retention` + `sqlite_freelist_ratio` / `vacuum`) — all SQL lives here, the `delete_channel_messages` precedent, including the docstring convention of naming what is *intentionally preserved* |
| `filters.py` | keyword-filter **materialization** into `messages.is_filtered` (on ingest + rule change) |
| `items.py` | item keys (`tg:{cid}:{mid}` / `hn:{sid}` / `x:{tweet_id}` / `rss:{entry_id}` ↔ `(source, ref1, ref2)` triple) + the item **envelope** (`{source, key, datetime, is_read, is_saved, telegram\|hn\|x}`, plus `feedback` — the reader's own up/down label — on X envelopes, whose join the other sources grow when their UI does) shared by timeline + records; the hn payload carries `preview`; the rss payload carries `sort_at` (the clamped timeline position — the rule lives in SQL, so the snapshot records the answer) beside an unclamped `published_at`; `_json_field` accepts a stored JSON str, an already-parsed value from saved-record replay, or None. The x payload renders snowflake ids as **strings** (int64 exceeds JS's safe range) and nests the quoted tweet; `x_envelope`'s `datetime` is feed-dependent — For You = `first_seen_at`, a followed account = `created_at` |
| `timeline.py` + `sources/` | **federated timeline merge** (Phase 2): `sources/telegram.py` (the old query — album buffer, unit cursors — unchanged in substance), `sources/x.py` (see the X block below) and `sources/hn.py` (the admission judge **and** the read path it reduced to — `qualified_at IS NOT NULL`, sorted and day-grouped by that same stamp; v14, see the HN admission block below) and `sources/rss.py` (one row per entry, no grouping and no judge — its only real decision is the **sort timestamp**, see the `rss.py` row) each return `SourceUnit` pages; `timeline.py` k-way merges by timestamp with a **composite cursor** `base64(json {source: "ts\x1fid"})` — a source absent from the map = not yet consumed, restarts from its top. `head_cursor`/`end_cursor` are composite too; `query_new` polls per-source anchors (an active source with zero units on page 1 gets a synthetic "now" anchor so its future items still poll). Merge keeps a per-source **floor**: a source drained below `limit` units with `has_more` ends the page early rather than letting older units from other sources jump ahead (album-dense TG pages). Bad/legacy cursors raise `InvalidCursor` → 422. HN unread counts respect the display mode (else the badge never clears) |
| `vectors.py` | the **only** module that knows sqlite-vec exists: `setup(dims)` (load the extension onto the peewee *database* so every thread-local connection replays it, then ensure the `vec0` table), `pack`/`unpack` (float32 BLOB, deliberately extension-independent so vectors are storable even where the extension will not load), `upsert`/`delete`/`clear`/`labeled_ids`/`knn`. Everything degrades to no-op when the extension is unavailable, which is what makes an unsupported host lose only the verdict |
| `embedding.py` | OpenAI-compatible embeddings (`CONDENSER_EMBEDDING_*`, default DashScope `text-embedding-v4@256`): batches of ≤10, two retries, L2-normalize, reorder by the echoed `index`. `available(settings)` is false without an API key → the whole verdict pipeline stays inert. `model_tag` = `name@dims`, the identity a stored vector is comparable within (a model/dimension change re-embeds rather than migrates) |
| `authors.py` | **channel A** — the author prior, and the cheapest channel by far: no API call, no table, no index, just a Beta-smoothed tally over labels already in the database (2026-07-29). It **reads no text**, which is both its strength and its limit — it never abstains on an account you have judged, and it is blind to one you have not. Built after the @IBKR measurement showed every *text* channel has a hole exactly where an ad account lives: B goes out-of-domain each time the account rotates subject, C is blind until the extractor runs, D needs token overlap. `fit` tallies handles (normalized: `@IBKR`/`ibkr` are one account; `save` ×2 like everywhere); `score` shrinks each rate by evidence mass and abstains below `condenser_verdict_a_min_observations`. Deliberately smoothed rather than the hard rule it replaces (`>=2 downs and no positives`): that rule acquits an account outright on its first upvote and convicts on its second down, and the cliff is what produced its one wrong call. Unlike C it routes **no chips** — by the time an account has been downed repeatedly the chips usually name several different attributes, and the pattern they share is "you keep saying no to this person"; filtering on `author` chips alone would discard 55 of the 56 downs that built the signal. Its evidence is a sentence rather than a metric, which makes it the most readable trail in the pane |
| `attributes.py` | **channel C** — extraction (step 2) and scoring (step 3) in one module, the way `ngram.py` holds channel D. Extraction: an LLM reads each tweet and reports *what it is about* (open English slugs) and *how it talks* (`STYLE_FLAGS`, a **closed** taxonomy grown from the reader's own down-reason chips, split finer where a chip lumps patterns together). Since 2026-07-29 each flag's **definition ships with its name** (`FLAG_GUIDE` → the prompt): until then the meanings lived in Python comments and only bare tokens were sent, which measured badly — `ai_slop` reached the model as a naked word, it read that as machine-written spam, and **0 of the reader's 3 `ai_slop` chips** landed on a tweet it had so flagged. A closed taxonomy is only closed if its meanings travel with it, and a test pins that every flag is defined in the prompt. A **feature extractor, not a judge** — the scoring stays in code that can be explained and improves with every label (step 3). `model_tag` = `model@TAXONOMY_VERSION`, the identity an attribute is comparable within (edit the taxonomy → old rows are re-read, never migrated — the `embedding.model_tag` contract). The project's **first per-item billed component**, so it is fenced four ways: `condenser_attr_enabled`, a hard per-round `condenser_attr_batch`, a count on `/api/x/status`, and — deliberately — **its own API key with no fallback to the embedding one**, so deploying the code cannot start spending; setting `CONDENSER_ATTR_API_KEY` *is* the act of turning it on. One request per tweet, never a batched prompt: batching saves a little overhead and buys silent misalignment (four answers for five posts, everything after the gap attached to the wrong tweet). Scoring: `fit_flags` counts each flag's ups and downs under one rule — **credit follows attribution**. `REASON_FLAGS` routes a down's chip to the flags it accuses; a chip that matches nothing falls back to a bag-level share, while `topic`/`author` charge nobody because the reader said the style was not the problem. A label that attributes nothing is spread across the flags it might have meant, and **that includes every upvote** (2026-07-29): an up carries no chip and never can, so crediting each flag on a liked tweet in full — as it did until then — let any flag the chips rarely accuse gain evidence it never lost, one-directionally. And `score_flags` lets the most negative flag carry the tweet — one unmistakable marketing line makes a post marketing, and averaging dilutes exactly what the channel is for. Each rate is shrunk by its evidence mass so a thrice-seen flag cannot outshout an eighteen-times-seen one |
| `channels.py` | the vocabulary the verdict's channels share (v2 plan): `ChannelScore` (score in [−1,+1], `confidence` = *how much evidence*, `corroborated` = may this carry a negative verdict, `meta`), the verdict constants, and the two combiners. **`resolve` is the production one** (step 4, 2026-07-28): each channel classifies on its *own* thresholds and the votes merge by rule — any negative with no positive → negative, any positive with no negative → positive, conflict → neutral. A vote, not a mean, for two measured/structural reasons: the channels' scales are incomparable (C spans ~[-0.4,+0.1] vs B/D's [-1,+1], so the mean diluted the sharp channel), and the revised §9 admits/monitors/kills *one channel's negative side* at a time, which requires the verdict to be attributable to the channel that cast it. `combine` (weighted mean) stays as the backtest's rejected-baseline comparison. The vote is rank-free, so a fourth channel (A, 2026-07-29) joined it without touching this module at all. **Abstaining is `None`, never 0.0** — folding silence in as a zero vote lets a channel that never fires drag the ones that do toward neutral |
| `ngram.py` | **channel D** — naive Bayes over the words of the tweets you labeled (v2 plan step 1). Answers "how does this talk" where the embedding answers "what is it about", which is what 24 of the first 29 downs were complaining about; costs no API call and no table (counts are refit from `x_tweets.text` per round), and it can **name its evidence** in words. Tokenizer: lowercase, drop URLs + @mentions (author identity is channel A's job — `authors.py` since 2026-07-29), keep hashtag words, latin unigrams + bigrams (bigrams built *before* stopword removal, so `save this` survives while `this` does not), CJK character bigrams (no jieba — same dependency thrift that picked sqlite-vec), emoji as tokens (`🧵`/`🔖` are load-bearing). Three decisions came out of the first real backtest and are pinned by a test: only tokens above `min_weight` vote, their weights are **averaged not summed** (a sum scores length, and downs run 30.8 informative tokens against ups' 15.3 — every long tweet saturated at −1), and the result is shifted by `model.offset`, the corpus's own neutral point, measured **leave-one-out** at fit time. The offset is applied to the finished score only: subtracting it per-token reorders the evidence and measured *below* the base rate. **Not wired into the running verdict** (step 4) |
| `verdict.py` | **For You verdict** (Phase 4, on `app.state.verdict`, kicked by ingest — For You only changes when the probe pushes). `run_once` = drop-retracted → cold-start gate → index-missing → judge (vector expiry left for `cleanup.py` on 2026-08-07 — it used to run here, but *inside* the cold-start gate, so a fresh install never pruned; attribute extraction slots before judging when channel C votes, after it otherwise — a tweet is judged exactly once, so an attribute arriving later would never vote; without C scoring, a slow provider must not delay verdicts). **Since step 4 (2026-07-28) judging is the ensemble**: `enabled_channels` (`CONDENSER_VERDICT_CHANNELS`, default `b` = byte-identical single-channel behavior, algo `knn-v1`; more channels → `vote-v1`) — plus, since step 5b, `shadow_channels` (`CONDENSER_VERDICT_SHADOW_CHANNELS`, default empty): channels that score and archive but **cast no vote**, so an unproven channel can be measured on real traffic without badging anyone (verified end-to-end: same window judged with and without shadows, 100 verdicts, zero changed). A channel listed in both votes — a typo must not mute an admitted channel. Their entries carry `{"verdict": null, "shadow": true}`, because an *abstaining* channel is absent from the block entirely and the two states must stay distinguishable. `algo` still names how the **verdict** was made, so `channels=b` + shadows is still `knn-v1` → each channel scores (A = `authors.score` off a per-round tally of labeled handles, B = kNN `topic_score`, C = `attributes.score_flags` off the tweet's stored attributes, D = `ngram.score` off a per-round refit; the configurable set is the single `CHANNEL_KEYS` tuple, so a channel reachable from `channel_policy` but missing there cannot exist) → each classifies under its own `ChannelPolicy` (per-channel thresholds; negatives **double-gated** by the master `negative_enabled` AND the channel's own `*_negative_enabled` admission flag, so admitting D can never resurrect B's dead negative side) → `channels.resolve` votes. `verdict_meta` stays additive: top level keeps B's `score`/`neighbors` exactly as shipped iOS builds decode them, and a `channels` block (vote + score + A's handle/up/down + C's flags + D's tokens; no second copy of B's neighbours) rides beside them. Two gates own the behavior: the **cold-start gate** sits *before* any embedding call (no labels, no spend) and the **OOD gate** drops neighbours past `max_distance` — without it kNN always returns k neighbours and every tweet gets scored off whatever was nearest. Scoring is a distance-weighted vote (`save` ×2 weight, not ±2 value, so the score stays in [−1,+1]); `negative` additionally needs ≥2 down neighbours because a wrong "not for you" costs the tweet while a wrong "recommended" costs a glance. The training set is **read live** from `item_feedback` ∪ `saved_items` (unsaving retracts a sample with no sync code; saved-and-downvoted is contradictory and is dropped from both sides), and the KNN index is **reconciled**, not written through — a restart, an outage or a model change self-heals next round. Already-labeled tweets are excluded from judging (they are in the index and would match themselves at distance 0). `verdict_meta` archives the nearest `META_NEIGHBOURS` (5) with author handles — capped because it is written ~1000×/day. `rebuild_labeled_index()` is the escape hatch for a suspect index |
| `prospective.py` | the **online** half of the verdict's evidence (v2 plan step 5, 2026-07-28): precision measured only on tweets the judge committed to *before* the reader said anything. Needs no `verdict_at` column and no timestamp comparison — `db.x_pending_verdict_rows` never judges an already-labeled tweet, so a For You row holding both a verdict and a label was judged first by construction, which is what makes these pairs free of the backtest's selection bias (it picks an operating point and scores it on the same labels). `summarize` reports the as-shipped badges plus **per-channel attribution** (a channel's own claim even where the vote resolved against it — §9 kills one channel's negative side, so a wrong negative must name its author), and `shadow` replays the *archived* scores at thresholds nobody ran: because the score is stored even when a channel's negative side is off, a channel's admission case can be built from production data **before** it is admitted. Two limits stated in the output rather than hidden: a badge may bias whether a tweet gets read/labeled at all, and channel B's `corroborated` is not fully archived (it counted every close neighbour; only the nearest five are stored), so B's shadow negatives are an upper bound — channel A is the exception, since its rule *is* the down count in its own evidence and therefore replays exactly |
| `records.py` | source-decoupled snapshots into `saved_items.raw_data` keyed by item key: TG = album rows + channel info, HN = story JSON, X and RSS = the envelope payload itself (X's quote already nested; RSS's computed `sort_at` included, since it does not survive the entry row); rendered back into envelopes without source tables |
| `forward.py` | rendering a **non-Telegram** item into a message for the user's own channel (2026-07-27). Telegram is the only outbound channel, so "forward" is two different things: a TG item is natively forwardable (that path, plus the bare t.me link Telegram itself expands into a full message card, stays in `tg.py`), while an HN story or a tweet has to be *written out*. Two shapes, because the two sources give Telegram different things to work with. **HN** is written out: a bold title line hyperlinked to the article, then a source line hyperlinked to the discussion — two links on two lines, because Telegram builds its preview card from the *first* URL, so the card shows the article while the discussion stays one tap away (a self-post has no article, so both lines point at the discussion). **X** is *just a link*, with the host rewritten to `X_EMBED_HOST` (`fixupx.com`): x.com serves Telegram no embed, but FixTweet's x.com-branded mirror does, so the card carries the author, text, media and even the quoted tweet — writing any of that into the body would print every tweet twice. Both hosts key off the status id, so an unknown handle falls back to X's own `i` placeholder. **RSS** (2026-08-20) is HN's shape minus its second line: an article has one destination and there is no discussion page to link beside it, so Telegram's card carries the site and blurb. Everything interpolated is `html.escape`d, comment included |
| `search.py` | the **only** module that knows FTS5 exists (`vectors.py`'s arrangement, same rationale): tokenizer, index maintenance, the per-source documents, the query, and hits → envelopes. Its load-bearing decision is that text is tokenized **in Python before FTS5 sees it** — `unicode61` treats a whole CJK run as one token (so 「模型」 only matches a message whose entire run *is* 「模型」) and `trigram` needs three characters, one more than most Chinese words have, while the tool that does this properly (wangfenjin/simple) is a C++ extension with no PyPI wheel, i.e. compiled binaries for two architectures plus a CI step. So a CJK run is indexed as its overlapping **character bigrams** and queried as a **phrase** over them — 「中文搜索」 → `中文 文搜 搜索`, searched as `"中文 文搜 搜索"`, where FTS5's position continuity gives back exactly substring semantics. A single-character query has no bigram to ask for and becomes a **prefix** query (`"猫" *`) — and that rule has one hole, which is why the index and the query are deliberately **asymmetric**. A prefix only reaches tokens that *start* with the character, so a character sitting last in its run had nothing to match at all: 「猫」 could not find 「我买了一只猫」, whose only 猫 token is 「只猫」 (found in review, then confirmed on the real archive — 「大连站日本分站」 was unreachable by 「站」). The index therefore emits each run's **final character as its own token**; the query must *not*, or 「中文搜索」 would become `"中文 文搜 搜索 索"` and match only text whose run ends there, breaking 「中文搜索工具」. Both directions are pinned by tests. Every token is **quoted**, which is the whole injection story: inside quotes `AND` is a word and `*` is nothing. The tokenizer is deliberately lossy in the *opposite* direction from `ngram.py`'s — that one serves a classifier and throws away URLs, @mentions and stopwords; this one serves recall and drops only what cannot be typed into a search box. `TOKENIZER_VERSION` is the `model_tag` contract simplified to one integer: edit `tokenize` → bump it → the next startup rebuilds. It is bumped for a **new source** too (4: RSS, 2026-08-20) — the marker means "a rebuild finished under this pipeline", and an archive that predates a source is missing from the index exactly the way a tokenizer change makes it wrong: silently. Known and accepted cost: substring semantics means 「中文」 also matches 「其**中文**件」 (the way out, if it ever stops being acceptable, is a real segmenter — not a threshold) |
| `preview.py` | source-agnostic link previews: fetch a URL (async httpx) + extract metadata (`metadata_parser`), `link_previews` cache, per-message batch w/ Telegram-bonus fill, image fetch for the proxy |
| `hn.py` | `HNManager` (on `app.state.hn`, peer of `TgManager`): subscription-driven HN front-page sampling loop (`topstories` diff → `hn_stories`, sticky `first_seen_at`, peak_rank, 48h snapshot refresh) + serial rate-limited hckrnews history backfill w/ pending-day set in `app_meta` (`threading.Lock` + per-day read-modify-write — `schedule_backfill` runs on the threadpool while the loop rewrites the set); HTTP via injectable `fetch_json` (tests need no network). Hardened per `kb/plans/2026-07-19-hn-phase1-review-fixes.md`: `_loop` has a catch-all guard (DB errors outside `poll_once`'s try must not kill the task); **null item ≠ dead** — refresh only marks dead on explicit `dead`/`deleted` (Firebase transiently nulls live items), while a *never-seen* front-page id that fetches null gets a dead placeholder row so it isn't re-pulled every round; `kick()` marshals via `call_soon_threadsafe` (no-op before startup / when source disabled). **Link-preview prefetch** (2026-07-20): `_fill_previews` at the tail of `poll_once` sweeps linkable stories without a stored preview newest-first (`CONDENSER_HN_PREVIEW_BATCH`/round, 0=off; covers fresh, backfilled *and* pre-feature rows) through `preview.get_preview` (warming the shared pane cache) into `hn_stories.preview`; ≤3 real attempts per story (`PREVIEW_MAX_ATTEMPTS`) — a still-fresh negative cache entry skips *without* bumping (the 1h neg-TTL < poll interval would otherwise eat every retry), empty-but-ok results are terminal; injectable `fetch_preview` for tests. **Admission** (v14, 2026-08-14): `_qualify` is the round's *last* step — scores must be fresh (the floors read them) and following the preview prefetch means a story usually arrives with its preview card already filled instead of bare for one interval; it just calls `sources/hn.qualify`, which owns the rule. `_backfill_day` ends with `stamp_history(day)` instead, because an imported day closed before we could judge it live. `routers/hn.py` = `/api/sources/hn/subscriptions*` + `/api/hn/status` (incl. `source_enabled`); POST = subscribe-and-enable (re-enables a paused row, `schedule_backfill` only on first create), POST/PATCH-enable → 503 when `CONDENSER_HN_ENABLED=false`. The config PATCH **merges** into the stored config (`hn.sub_config`, x.py's precedent) — three admission knobs share one column since 2026-08-14, so a whole-value write would disarm two of them. Multi-source plan Phase 1: `kb/plans/2026-07-19-multi-source-hn.md` |
| `x.py` | X (Twitter) source, **push model** — the server never talks to X; a local probe (`probe/`) reads the user's logged-in session through the `xbird` library (the `bird` CLI until 2026-08-06; the pushed JSON shape is unchanged, and the server is written against that shape) and pushes it. Owns tolerant `parse_tweet` (string ids → int64, legacy `'%a %b %d %H:%M:%S %z %Y'` timestamps, media/metrics/article passthrough, `quotedTweet` → a self-referential archive row, retweets only recoverable as `rt_of_handle` from bird's `RT @x:` text prefix), `ingest_tweets` (idempotent by tweet id: tweet rows refresh so metrics move, feed rows are insert-only so `first_seen_at` stays sticky; embedded quotes use insert-if-absent so a depth-limited copy can't downgrade a richer row; unkeyable entries are counted and dropped, a drifted field is counted *and* stored since `raw` is archived), `probe_config` (subscription-driven, like HN sampling), `_learn_user_identity` (a followed account's numeric `user_id` + display `name` come from its first push — the handle is the subscription key because that is what a reader types, the numeric id is what survives a rename), and `status` (push activity from `app_meta` `x_*` keys). Since 2026-07-30 it also owns the **Following** feed (`FOLLOWING_FEED`, a third `x_feed_kind` beside `home`/`user`) and the two filters only it needs (`_apply_following_rules`, plan §6.3): ① an entry whose author is not in `x_following` is dropped **whole**, body included — X injects ads with no structural marker, so the follow list is the only test, and an ad is noise all the way down; ② an entry older than `CONDENSER_X_FOLLOWING_MAX_AGE_HOURS` (24) gets its **body archived but no feed row**, reusing the path a quoted tweet already takes — X pads the feed with a thread's own ancestors (measured: one 2025-09 root arriving in a 2026-07 page) and a feed row would land them in timeline history, invisible but counted as unread. Order matters: ① first, so an ad that is *also* old is not merely archived; and both run on feed entries only, never on `_embedded_quotes`. **An empty follow list disables ① entirely** — the deliberate failure mode, since the alternative on a never-synced install is silently discarding every tweet as advertising. `IngestResult` carries `filtered_ads`/`filtered_old` so the subscription row can show them. Since 2026-08-10 it also owns the **For You language filter** (`_apply_language_filter`, `filtered_lang`): a For You entry whose `lang` (X's own verdict, carried since xbird 1.1.0; `ParsedTweet.lang`, no DB column — `raw` archives it) has a primary subtag outside the global `languages` whitelist is dropped **whole**, the ad filter's path. Armed by two settings at once — the For You sub's `config.lang_filter` AND a non-empty `db.get_languages()` — and **fail-open three ways**: missing `lang` (pre-1.1.0 probe) passes, `NON_LANGUAGE_CODES` (`und`/`zxx`/… — media-only tweets; measured 2 of 40 real home entries) pass, empty whitelist filters nothing. For You only: a followed account posting in another language was still chosen by the reader. `routers/x.py` = `/api/sources/x/subscriptions*` + `probe-config` (now also `sync_following`, the server-side staleness decision, so the probe stays stateless) + `following` (whole-list replace; refuses an empty push over a non-empty list, because a transient bird `[]` would otherwise disable the ad filter for a whole sync interval) + `ingest` (Bearer or cookie — the probe is just a device) + `/api/x/status` + `/api/x/avatar/{handle}` (unavatar proxy, `fallback=false` so a miss 404s into the client's letter avatar — bird carries no avatar URL); 503 when `CONDENSER_X_ENABLED=false`, 404 on a push to an unknown/paused feed. `sources/x.py` is the **Phase 2 timeline provider**: `x_feed_items JOIN x_tweets` (+ a self-join for the quoted tweet), read/saved/hidden anti-joins, and a feed-dependent `SORT_AT_SQL` — For You by `first_seen_at`, a followed account by `created_at`. **For You is opt-in**: bird's `home` re-samples every call (~2400 tweets/day at the old n=50), so by default it is excluded from the aggregate timeline and only appears under `?source=x` / `?source=x&feed=…`; since 2026-07-29 the subscription's `config.aggregate` (`none` | `positive` | `all`, HN's `display_mode` pattern) can admit it — `positive` lets through only what the verdict recommends, measured at ~13% of arrivals, i.e. about a fifth added to a ~50-item day rather than a flood. The predicate lives inside the scoped subquery (with the feed filter, so dedup only ranks admissible rows) and `bulk_read_scope` hands the same rule to the bulk-read sweep, because "mark all read" in the aggregate must burn exactly what the aggregate showed and not the For You labeling backlog; `CONDENSER_X_HOME_COUNT` dropped 50 → 20 as the second capacity lever. **Following joins the aggregate in full by default** (2026-07-30) — it is a *stable window*, not a firehose (two consecutive bird calls overlapped 19/20, ~100-200 tweets/day), and it is never judged, so its `aggregate` modes are `none`/`all` with no `positive`: a recommended-only mode would silently hide the whole feed. The admission rule generalized with it — `aggregate_mode(feed)` + `scope()` now drop any feed set to `none`, replacing the hardcoded "everything except For You" that used to live in `db.enabled_x_feeds`. A tweet in several feeds de-duplicates under an **explicit** `ROW_NUMBER()` priority (account subscription > following > For You), no longer "earliest sighting wins": with three feeds a tweet by an account you also subscribe to sits in two non-For-You feeds, and the winner decides its sort timestamp, its admission rule, its verdict badge *and* which sidebar row owns its unread count — which would otherwise drift with whichever push landed first. Plans: `kb/plans/2026-07-24-x-source-local-probe.md`, `kb/plans/2026-07-30-x-following-feed.md` |
| `rss.py` | **RSS source** (plan `kb/plans/2026-08-20-rss-source-opml-llm-summary.md`) — the simplest source here and deliberately so: a published standard, so no probe, no reverse-engineered API, no anti-scraping and nothing to judge. `RssManager` on `app.state.rss` (HNManager's peer) polls every enabled feed each `CONDENSER_RSS_POLL_MINUTES` (30) behind an `asyncio.Semaphore` (5), through an injectable `fetch_feed`; parsing is **not** injectable, because real-world XML is this source's entire risk surface and a stubbed parser would test nothing. **feedparser** is the one new dependency, and `parse_feed` runs on `asyncio.to_thread` — it is pure Python and 100 feeds a round would otherwise stall the loop this process shares with FastAPI, the TG listener and the HN sampler. Three failure modes are told apart on purpose: a **304 is a hit** (checked *before* `raise_for_status`, which classifies it as a redirect and raises — found on the first live run, so every healthy feed was accruing an error badge), **bozo-but-has-entries is a warning** (`last_error` set, `error_count` stays 0 — dropping real content over a stray `&` is the worse failure), and **`NotAFeedError`** is its own class because an HTML error page parses *clean* with zero entries, which would otherwise read as "this feed never publishes". Ingest is insert-if-absent on `(feed_url, guid)` and applies the **unread window** in the same transaction: an entry published more than `CONDENSER_RSS_UNREAD_WINDOW_DAYS` (7) ago arrives already read, because an entry archived without its marker is unread backlog on screen the moment it commits. The rule runs every round rather than only the first — on a steady-state round nothing real is that old, so it only bites on an import, with no "is this the first round" branch to get wrong. Measured on 8 real blogs: 280 entries, **3 unread**. The tail of the round writes the search documents (`search.index_rss_entries`), and Phase 3's summariser will hang there too. `parse_opml` is hand-rolled `xml.etree` — every `<outline>` carrying an `xmlUrl`, flattened, folders discarded (v1 has none to import into); 204/204 of a real export parse clean. `routers/rss.py` = `/api/sources/rss/subscriptions*` + `/opml` + `/api/rss/status`, the HN/X router shape with **one forced deviation**: this source's key is a URL, which carries its own slashes and query string, so PATCH/DELETE identify the feed with `?url=` rather than a path segment |
| `sources/rss.py` | the RSS timeline provider. One row per entry, no album grouping, no admission, no verdict — every archived entry of an *enabled* feed is a timeline item (plan §0.2), which makes RSS a peer of Telegram rather than an opt-in like X's For You. Its one real decision is `SORT_AT_SQL`: `published_at` **clamped** to `first_seen_at` when it is missing or more than 30 minutes ahead of it. Both halves are needed — an OPML import gives every entry the same `first_seen_at`, while feeds do publish future timestamps, and an unclamped one squats at the top of the timeline until real time catches up. The clamp is applied in SQL and **never** to the stored row, so the pane can still show what the feed claimed; the computed value is selected as `sort_at` and rides in the envelope, because a saved snapshot replays without ever running that SQL again and the rule must not exist in two languages. `rows_by_id` is deliberately not subscription-scoped (`telegram.units_by_key`'s rule — search and the record snapshot read the archive, not the reading list), while every reading surface adds `s.enabled = 1`, so pausing a feed hides it the way pausing a Telegram channel does. `bulk_read_scope` hands the same rule to the sweep: burn what the view showed, not a paused feed's backlog |
| `cleanup.py` | **daily retention sweep** (2026-08-07, on `app.state.cleanup`). The cadence is a **database breakpoint, not a timer**: the loop wakes hourly and asks `app_meta.cleanup_last_run_at` whether a day has passed — `git push` to master is a deploy here, so the process restarts far more often than once a day and an in-memory `sleep(24h)` would rarely survive to fire. The round runs on `asyncio.to_thread` (VACUUM takes an exclusive lock and this process shares one event loop with FastAPI, the TG listener, HN sampling and the verdict; peewee connections are thread-local, so the pooled worker gets its own and `_run_in_thread` hands it back in a `finally`). Rules are duck-typed (`name` / `enabled(settings)` / `run(now, settings) -> CleanupReport`, one `DEFAULT_RULES` tuple) and isolated per rule — a broken future HN rule must not cost X its sweep — while the breakpoint advances unless **every** rule threw, since a transient `database is locked` deserves an hour's retry, not a lost day. Deliberately **no `kick()`**: HN's exists for "subscribe → sample now" and the verdict's for "push → judge now", but no user action makes yesterday's retention scan due sooner. `XRetentionRule` also absorbed `verdict._prune` — that call sat *inside* the cold-start gate, so an install with too few labels to judge anything had never pruned a vector at all. `RssRetentionRule` (2026-08-20) is the same rule one table wider apart: entries older than `CONDENSER_CLEANUP_RSS_RETENTION_DAYS` (30, longer than X's 15 — a feed publishes a few entries a day where For You pushes hundreds) with no read/hidden/feedback/saved marker, plus the search-document anti-join. Adding it was a rule object and one line in `DEFAULT_RULES`, which is the shape working. ⚠️ It also means **a test module with a fixed clock in the past has to switch this rule off**, or the startup round deletes its fixture (the trap `test_x_verdict` hit on 2026-08-09; `tests/test_rss_timeline.py` sets `CONDENSER_CLEANUP_RSS_ENABLED=false` and drives the rule directly in its own test). `GET /api/cleanup/status` exists because at a 15-day window the first weeks legitimately delete nothing, and "ran, found nothing" must not look like "never ran" |
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

Remaining: Docker multi-stage frontend build + README (spec step 9).

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

**X feedback (Phase 3, 2026-07-25)**: `POST /api/feedback {key, verdict}` /
`DELETE /api/feedback/{key}` (`routers/reading.py`, next to hide — same triple-keyed
family) write `item_feedback`; the envelope carries the current label back as
`feedback`, joined live in `sources/x.py` and, for saved records, batched in
`records._saved_feedback` (deliberately NOT snapshotted — the label keeps changing
after the save). Web: `XFeedbackButtons` on the card footer + `useFeedback`. The
endpoints are source-generic like the table, but only X joins the field today.
Phase 3 **only records the label** — nothing is hidden, ranked or filtered by it;
that is Phase 4's verdict, trained on exactly these labels (plus saved items as
strong positives), which is why followed-account tweets are markable even though
they will never get a verdict. iOS got the buttons in Phase 5 (2026-07-25) with the
rest of the X surfaces.

**Down-reason chips (2026-07-26, schema v9)**: the thumbs-down now asks *why* —
`POST /api/feedback` takes an optional `reason` and the envelope carries it back as
the sibling field `feedback_reason` (**not** nested into `feedback`: shipped iOS
builds decode that as a bare string, and an object would fail the whole page's
decode on a binary users upgrade separately). Two rules make it safe: a POST states
the **whole** label, so omitting the reason clears a stored one and correcting a
down-with-reason into an up cannot carry `ai_slop` onto a positive; and the chip is
**skippable at zero cost** — no pick is exactly the bag-level label we had before.
Web asks with an inline chip row under the card footer (`XFeedbackButtons`, transient
— it answers *this* click and never re-nags an already-labeled tweet); iOS asks with
a native `confirmationDialog` (the Chinese labels don't fit one phone-width row, and
the system sheet is already "tap one / Cancel to skip"). The picked reason is echoed
only in the detail pane, never on the card. `FEEDBACK_REASONS` lives in
`db.py` / `lib/sources.ts` / Kit's `ItemFeedbackReason.offered`, plus the request
schema's Literal in `types.py` — pinned to `db.FEEDBACK_REASONS` by a test, because a
one-sided edit means the endpoint accepts and stores a label nothing can route. Why
this exists — and why it was missing until now — is the "Phase 3 补记" section of the
X plan.

**`engagement_farming`「博眼球」** joined the taxonomy 2026-07-27 (a constant-only
change: `reason` is a nullable TEXT column, so no migration and no schema bump). It is
X's own platform-manipulation term for the influencer-thread pattern — hook, FOMO,
"save this 🔖", payoff parked in the replies so an outbound link doesn't cost reach —
and it is deliberately **not** a flavour of `promo`: promo sells a thing (intent), this
games interaction (largely lexical, so the planned n-gram channel can learn it outright
while `promo` needs the expensive LLM one). The rejected alternatives are worth knowing,
since the argument recurs: `clout` overlaps `promo` semantically (clout chasing *is*
self-promotion) and a chip the reader hesitates over yields noisy labels; `content_farm`
names an operation rather than an item, and encodes a *quality* judgement that would
misfire on the digest/summary accounts the user likes — those are derivative too, and
differ only in not baiting. Being a superset (rage bait, poll bait, giveaways) is a
feature: it reaches a trainable label count sooner, which is the binding constraint.
The Chinese label started as the literal 「钓互动」 and became **「博眼球」** the same day
(display-string only — the value, its scope and the stored labels are untouched): a chip
is read mid-scroll, so an idiomatic phrase gets pressed while a translated one gets
skipped. Known trade-off: 博眼球 leans toward the hook/clickbait flavour and reads less
obviously right on a giveaway or a poll, which the value still covers.
Full reasoning: `kb/notes/2026-07-27-engagement-farming-chip.md`.

## Local probe (`probe/`, monorepo)

> **Note:** The original section "Local probe (`probe/`, monorepo)" has been split into a separate file. See [Local probe (`probe/`, monorepo)](kb/docs/probe.md).

## iOS app (`ios/`, monorepo)

> **Note:** The original section "iOS app (`ios/`, monorepo)" has been split into a separate file. See [iOS app (`ios/`, monorepo)](kb/docs/ios.md).

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
| `x_verdict_backtest.py` | Leave-one-out backtest of the For You verdict on your real labels — the tool that turns constants into decisions and, since the v2 plan, **picks the channels**. Read-only on the DB (it does trash the KNN index per fold and rebuilds it at the end). `--channels a,b,d` reports each channel and their combination **on the same folds**; `--sweep` grids each channel's own settings; `--negatives topic` drops style downs from training (the variant §7 of the plan asks for); `--embed-missing` is the only mode that calls an API. Read **abstain/coverage first** (a judge that always shrugs is 100% precise and useless), then the **base rate** printed beside every table (the 2026-07-27 negative failure was 55.6% against 49.2% — without the comparison it reads as usable), then negative precision, then positive. The closing summary ranks operating points with ≥5 calls and stars any negative one clearing the plan's §9 bar. Channels wrap the *production* scoring code, never a copy — and evidence is captured once per fold and re-scored per grid cell, so a sweep costs one pass of the expensive part |
| `x_verdict_prospective.py` | The **online** counterpart of the backtest (v2 plan step 5): scores only the tweets that were judged *before* they were labeled, so nothing here can be tuned against. Fully read-only — unlike the backtest it never touches the KNN index, so it is safe to point at a live copy. Prints coverage first (a channel is not validated just because it has been running), then the verdict×label matrix, then as-shipped precision per side and per channel, then the **shadow replay** (`--sweep` for a threshold grid) — the archived scores classified at thresholds nobody ran, which is how a channel earns admission without being admitted. Ends with every wrong call printed in full, because at these sample sizes the individual tweets *are* the evidence |
| `dev-browser-login.sh` | Puts a logged-in session cookie into an `agent-browser` profile so a UI walkthrough can run behind the auth gate. The app password stays on stdin the whole way (envops → curl → cookie jar → cookie file → agent-browser), so it never reaches a command line or an agent transcript; the temp files are deleted on exit. Encodes two traps: agent-browser's cookie file must be bare `k=v; k2=v2` (a `Cookie: k=v` header line silently becomes a cookie *named* `Cookie: k`, stored but never sent), and a backend-issued cookie works on the Vite origin because cookies ignore ports. **Check the dev backend was started with `--reload`** (`ps -o command -p $(lsof -ti :8792 -sTCP:LISTEN)`) or the walkthrough verifies stale code |

## Status / known gaps

> **Note:** The original section "Status / known gaps" has been split into a separate file. See [Status / known gaps](kb/docs/status-and-gaps.md).

## Documentation

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
