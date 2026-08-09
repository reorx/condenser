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

condenser's peewee models bind to telememo's `db` instance, so everything is one connection.
`condenser/db.py:init_db()` initializes telememo tables (+ `is_filtered`) then condenser tables.

## Key modules (`condenser/`)

| File | Role |
|---|---|
| `config.py` / `crypto.py` | env settings; Fernet session encryption + signed cookie from `CONDENSER_SECRET_KEY` |
| `db.py` | condenser tables (peewee, bound to telememo's db) + CRUD + shared `init_db`. Also the retention SQL `cleanup.py` calls (`sweep_x_retention` + `sqlite_freelist_ratio` / `vacuum`) — all SQL lives here, the `delete_channel_messages` precedent, including the docstring convention of naming what is *intentionally preserved* |
| `filters.py` | keyword-filter **materialization** into `messages.is_filtered` (on ingest + rule change) |
| `items.py` | item keys (`tg:{cid}:{mid}` / `hn:{sid}` / `x:{tweet_id}` ↔ `(source, ref1, ref2)` triple) + the item **envelope** (`{source, key, datetime, is_read, is_saved, telegram\|hn\|x}`, plus `feedback` — the reader's own up/down label — on X envelopes, whose join the other sources grow when their UI does) shared by timeline + records; the hn payload carries `preview`; `_json_field` accepts a stored JSON str, an already-parsed value from saved-record replay, or None. The x payload renders snowflake ids as **strings** (int64 exceeds JS's safe range) and nests the quoted tweet; `x_envelope`'s `datetime` is feed-dependent — For You = `first_seen_at`, a followed account = `created_at` |
| `timeline.py` + `sources/` | **federated timeline merge** (Phase 2): `sources/telegram.py` (the old query — album buffer, unit cursors — unchanged in substance), `sources/x.py` (see the X block below) and `sources/hn.py` (query-time `ROW_NUMBER()` day-rank, display_mode top10/top20/half/all from sub config) each return `SourceUnit` pages; `timeline.py` k-way merges by timestamp with a **composite cursor** `base64(json {source: "ts\x1fid"})` — a source absent from the map = not yet consumed, restarts from its top. `head_cursor`/`end_cursor` are composite too; `query_new` polls per-source anchors (an active source with zero units on page 1 gets a synthetic "now" anchor so its future items still poll). Merge keeps a per-source **floor**: a source drained below `limit` units with `has_more` ends the page early rather than letting older units from other sources jump ahead (album-dense TG pages). Bad/legacy cursors raise `InvalidCursor` → 422. HN unread counts respect the display mode (else the badge never clears) |
| `vectors.py` | the **only** module that knows sqlite-vec exists: `setup(dims)` (load the extension onto the peewee *database* so every thread-local connection replays it, then ensure the `vec0` table), `pack`/`unpack` (float32 BLOB, deliberately extension-independent so vectors are storable even where the extension will not load), `upsert`/`delete`/`clear`/`labeled_ids`/`knn`. Everything degrades to no-op when the extension is unavailable, which is what makes an unsupported host lose only the verdict |
| `embedding.py` | OpenAI-compatible embeddings (`CONDENSER_EMBEDDING_*`, default DashScope `text-embedding-v4@256`): batches of ≤10, two retries, L2-normalize, reorder by the echoed `index`. `available(settings)` is false without an API key → the whole verdict pipeline stays inert. `model_tag` = `name@dims`, the identity a stored vector is comparable within (a model/dimension change re-embeds rather than migrates) |
| `authors.py` | **channel A** — the author prior, and the cheapest channel by far: no API call, no table, no index, just a Beta-smoothed tally over labels already in the database (2026-07-29). It **reads no text**, which is both its strength and its limit — it never abstains on an account you have judged, and it is blind to one you have not. Built after the @IBKR measurement showed every *text* channel has a hole exactly where an ad account lives: B goes out-of-domain each time the account rotates subject, C is blind until the extractor runs, D needs token overlap. `fit` tallies handles (normalized: `@IBKR`/`ibkr` are one account; `save` ×2 like everywhere); `score` shrinks each rate by evidence mass and abstains below `condenser_verdict_a_min_observations`. Deliberately smoothed rather than the hard rule it replaces (`>=2 downs and no positives`): that rule acquits an account outright on its first upvote and convicts on its second down, and the cliff is what produced its one wrong call. Unlike C it routes **no chips** — by the time an account has been downed repeatedly the chips usually name several different attributes, and the pattern they share is "you keep saying no to this person"; filtering on `author` chips alone would discard 55 of the 56 downs that built the signal. Its evidence is a sentence rather than a metric, which makes it the most readable trail in the pane |
| `attributes.py` | **channel C** — extraction (step 2) and scoring (step 3) in one module, the way `ngram.py` holds channel D. Extraction: an LLM reads each tweet and reports *what it is about* (open English slugs) and *how it talks* (`STYLE_FLAGS`, a **closed** taxonomy grown from the reader's own down-reason chips, split finer where a chip lumps patterns together). Since 2026-07-29 each flag's **definition ships with its name** (`FLAG_GUIDE` → the prompt): until then the meanings lived in Python comments and only bare tokens were sent, which measured badly — `ai_slop` reached the model as a naked word, it read that as machine-written spam, and **0 of the reader's 3 `ai_slop` chips** landed on a tweet it had so flagged. A closed taxonomy is only closed if its meanings travel with it, and a test pins that every flag is defined in the prompt. A **feature extractor, not a judge** — the scoring stays in code that can be explained and improves with every label (step 3). `model_tag` = `model@TAXONOMY_VERSION`, the identity an attribute is comparable within (edit the taxonomy → old rows are re-read, never migrated — the `embedding.model_tag` contract). The project's **first per-item billed component**, so it is fenced four ways: `condenser_attr_enabled`, a hard per-round `condenser_attr_batch`, a count on `/api/x/status`, and — deliberately — **its own API key with no fallback to the embedding one**, so deploying the code cannot start spending; setting `CONDENSER_ATTR_API_KEY` *is* the act of turning it on. One request per tweet, never a batched prompt: batching saves a little overhead and buys silent misalignment (four answers for five posts, everything after the gap attached to the wrong tweet). Scoring: `fit_flags` counts each flag's ups and downs under one rule — **credit follows attribution**. `REASON_FLAGS` routes a down's chip to the flags it accuses; a chip that matches nothing falls back to a bag-level share, while `topic`/`author` charge nobody because the reader said the style was not the problem. A label that attributes nothing is spread across the flags it might have meant, and **that includes every upvote** (2026-07-29): an up carries no chip and never can, so crediting each flag on a liked tweet in full — as it did until then — let any flag the chips rarely accuse gain evidence it never lost, one-directionally. And `score_flags` lets the most negative flag carry the tweet — one unmistakable marketing line makes a post marketing, and averaging dilutes exactly what the channel is for. Each rate is shrunk by its evidence mass so a thrice-seen flag cannot outshout an eighteen-times-seen one |
| `channels.py` | the vocabulary the verdict's channels share (v2 plan): `ChannelScore` (score in [−1,+1], `confidence` = *how much evidence*, `corroborated` = may this carry a negative verdict, `meta`), the verdict constants, and the two combiners. **`resolve` is the production one** (step 4, 2026-07-28): each channel classifies on its *own* thresholds and the votes merge by rule — any negative with no positive → negative, any positive with no negative → positive, conflict → neutral. A vote, not a mean, for two measured/structural reasons: the channels' scales are incomparable (C spans ~[-0.4,+0.1] vs B/D's [-1,+1], so the mean diluted the sharp channel), and the revised §9 admits/monitors/kills *one channel's negative side* at a time, which requires the verdict to be attributable to the channel that cast it. `combine` (weighted mean) stays as the backtest's rejected-baseline comparison. The vote is rank-free, so a fourth channel (A, 2026-07-29) joined it without touching this module at all. **Abstaining is `None`, never 0.0** — folding silence in as a zero vote lets a channel that never fires drag the ones that do toward neutral |
| `ngram.py` | **channel D** — naive Bayes over the words of the tweets you labeled (v2 plan step 1). Answers "how does this talk" where the embedding answers "what is it about", which is what 24 of the first 29 downs were complaining about; costs no API call and no table (counts are refit from `x_tweets.text` per round), and it can **name its evidence** in words. Tokenizer: lowercase, drop URLs + @mentions (author identity is channel A's job — `authors.py` since 2026-07-29), keep hashtag words, latin unigrams + bigrams (bigrams built *before* stopword removal, so `save this` survives while `this` does not), CJK character bigrams (no jieba — same dependency thrift that picked sqlite-vec), emoji as tokens (`🧵`/`🔖` are load-bearing). Three decisions came out of the first real backtest and are pinned by a test: only tokens above `min_weight` vote, their weights are **averaged not summed** (a sum scores length, and downs run 30.8 informative tokens against ups' 15.3 — every long tweet saturated at −1), and the result is shifted by `model.offset`, the corpus's own neutral point, measured **leave-one-out** at fit time. The offset is applied to the finished score only: subtracting it per-token reorders the evidence and measured *below* the base rate. **Not wired into the running verdict** (step 4) |
| `verdict.py` | **For You verdict** (Phase 4, on `app.state.verdict`, kicked by ingest — For You only changes when the probe pushes). `run_once` = drop-retracted → cold-start gate → index-missing → judge (vector expiry left for `cleanup.py` on 2026-08-07 — it used to run here, but *inside* the cold-start gate, so a fresh install never pruned; attribute extraction slots before judging when channel C votes, after it otherwise — a tweet is judged exactly once, so an attribute arriving later would never vote; without C scoring, a slow provider must not delay verdicts). **Since step 4 (2026-07-28) judging is the ensemble**: `enabled_channels` (`CONDENSER_VERDICT_CHANNELS`, default `b` = byte-identical single-channel behavior, algo `knn-v1`; more channels → `vote-v1`) — plus, since step 5b, `shadow_channels` (`CONDENSER_VERDICT_SHADOW_CHANNELS`, default empty): channels that score and archive but **cast no vote**, so an unproven channel can be measured on real traffic without badging anyone (verified end-to-end: same window judged with and without shadows, 100 verdicts, zero changed). A channel listed in both votes — a typo must not mute an admitted channel. Their entries carry `{"verdict": null, "shadow": true}`, because an *abstaining* channel is absent from the block entirely and the two states must stay distinguishable. `algo` still names how the **verdict** was made, so `channels=b` + shadows is still `knn-v1` → each channel scores (A = `authors.score` off a per-round tally of labeled handles, B = kNN `topic_score`, C = `attributes.score_flags` off the tweet's stored attributes, D = `ngram.score` off a per-round refit; the configurable set is the single `CHANNEL_KEYS` tuple, so a channel reachable from `channel_policy` but missing there cannot exist) → each classifies under its own `ChannelPolicy` (per-channel thresholds; negatives **double-gated** by the master `negative_enabled` AND the channel's own `*_negative_enabled` admission flag, so admitting D can never resurrect B's dead negative side) → `channels.resolve` votes. `verdict_meta` stays additive: top level keeps B's `score`/`neighbors` exactly as shipped iOS builds decode them, and a `channels` block (vote + score + A's handle/up/down + C's flags + D's tokens; no second copy of B's neighbours) rides beside them. Two gates own the behavior: the **cold-start gate** sits *before* any embedding call (no labels, no spend) and the **OOD gate** drops neighbours past `max_distance` — without it kNN always returns k neighbours and every tweet gets scored off whatever was nearest. Scoring is a distance-weighted vote (`save` ×2 weight, not ±2 value, so the score stays in [−1,+1]); `negative` additionally needs ≥2 down neighbours because a wrong "not for you" costs the tweet while a wrong "recommended" costs a glance. The training set is **read live** from `item_feedback` ∪ `saved_items` (unsaving retracts a sample with no sync code; saved-and-downvoted is contradictory and is dropped from both sides), and the KNN index is **reconciled**, not written through — a restart, an outage or a model change self-heals next round. Already-labeled tweets are excluded from judging (they are in the index and would match themselves at distance 0). `verdict_meta` archives the nearest `META_NEIGHBOURS` (5) with author handles — capped because it is written ~1000×/day. `rebuild_labeled_index()` is the escape hatch for a suspect index |
| `prospective.py` | the **online** half of the verdict's evidence (v2 plan step 5, 2026-07-28): precision measured only on tweets the judge committed to *before* the reader said anything. Needs no `verdict_at` column and no timestamp comparison — `db.x_pending_verdict_rows` never judges an already-labeled tweet, so a For You row holding both a verdict and a label was judged first by construction, which is what makes these pairs free of the backtest's selection bias (it picks an operating point and scores it on the same labels). `summarize` reports the as-shipped badges plus **per-channel attribution** (a channel's own claim even where the vote resolved against it — §9 kills one channel's negative side, so a wrong negative must name its author), and `shadow` replays the *archived* scores at thresholds nobody ran: because the score is stored even when a channel's negative side is off, a channel's admission case can be built from production data **before** it is admitted. Two limits stated in the output rather than hidden: a badge may bias whether a tweet gets read/labeled at all, and channel B's `corroborated` is not fully archived (it counted every close neighbour; only the nearest five are stored), so B's shadow negatives are an upper bound — channel A is the exception, since its rule *is* the down count in its own evidence and therefore replays exactly |
| `records.py` | source-decoupled snapshots into `saved_items.raw_data` keyed by item key: TG = album rows + channel info, HN = story JSON, X = the envelope payload itself (quote already nested); rendered back into envelopes without source tables |
| `forward.py` | rendering a **non-Telegram** item into a message for the user's own channel (2026-07-27). Telegram is the only outbound channel, so "forward" is two different things: a TG item is natively forwardable (that path, plus the bare t.me link Telegram itself expands into a full message card, stays in `tg.py`), while an HN story or a tweet has to be *written out*. Two shapes, because the two sources give Telegram different things to work with. **HN** is written out: a bold title line hyperlinked to the article, then a source line hyperlinked to the discussion — two links on two lines, because Telegram builds its preview card from the *first* URL, so the card shows the article while the discussion stays one tap away (a self-post has no article, so both lines point at the discussion). **X** is *just a link*, with the host rewritten to `X_EMBED_HOST` (`fixupx.com`): x.com serves Telegram no embed, but FixTweet's x.com-branded mirror does, so the card carries the author, text, media and even the quoted tweet — writing any of that into the body would print every tweet twice. Both hosts key off the status id, so an unknown handle falls back to X's own `i` placeholder. Everything interpolated is `html.escape`d, comment included |
| `search.py` | the **only** module that knows FTS5 exists (`vectors.py`'s arrangement, same rationale): tokenizer, index maintenance, the per-source documents, the query, and hits → envelopes. Its load-bearing decision is that text is tokenized **in Python before FTS5 sees it** — `unicode61` treats a whole CJK run as one token (so 「模型」 only matches a message whose entire run *is* 「模型」) and `trigram` needs three characters, one more than most Chinese words have, while the tool that does this properly (wangfenjin/simple) is a C++ extension with no PyPI wheel, i.e. compiled binaries for two architectures plus a CI step. So a CJK run is indexed as its overlapping **character bigrams** and queried as a **phrase** over them — 「中文搜索」 → `中文 文搜 搜索`, searched as `"中文 文搜 搜索"`, where FTS5's position continuity gives back exactly substring semantics. A single-character query has no bigram to ask for and becomes a **prefix** query (`"猫" *`) — and that rule has one hole, which is why the index and the query are deliberately **asymmetric**. A prefix only reaches tokens that *start* with the character, so a character sitting last in its run had nothing to match at all: 「猫」 could not find 「我买了一只猫」, whose only 猫 token is 「只猫」 (found in review, then confirmed on the real archive — 「大连站日本分站」 was unreachable by 「站」). The index therefore emits each run's **final character as its own token**; the query must *not*, or 「中文搜索」 would become `"中文 文搜 搜索 索"` and match only text whose run ends there, breaking 「中文搜索工具」. Both directions are pinned by tests. Every token is **quoted**, which is the whole injection story: inside quotes `AND` is a word and `*` is nothing. The tokenizer is deliberately lossy in the *opposite* direction from `ngram.py`'s — that one serves a classifier and throws away URLs, @mentions and stopwords; this one serves recall and drops only what cannot be typed into a search box. `TOKENIZER_VERSION` is the `model_tag` contract simplified to one integer: edit `tokenize` → bump it → the next startup rebuilds. Known and accepted cost: substring semantics means 「中文」 also matches 「其**中文**件」 (the way out, if it ever stops being acceptable, is a real segmenter — not a threshold) |
| `preview.py` | source-agnostic link previews: fetch a URL (async httpx) + extract metadata (`metadata_parser`), `link_previews` cache, per-message batch w/ Telegram-bonus fill, image fetch for the proxy |
| `hn.py` | `HNManager` (on `app.state.hn`, peer of `TgManager`): subscription-driven HN front-page sampling loop (`topstories` diff → `hn_stories`, sticky `first_seen_at`, peak_rank, 48h snapshot refresh) + serial rate-limited hckrnews history backfill w/ pending-day set in `app_meta` (`threading.Lock` + per-day read-modify-write — `schedule_backfill` runs on the threadpool while the loop rewrites the set); HTTP via injectable `fetch_json` (tests need no network). Hardened per `kb/plans/2026-07-19-hn-phase1-review-fixes.md`: `_loop` has a catch-all guard (DB errors outside `poll_once`'s try must not kill the task); **null item ≠ dead** — refresh only marks dead on explicit `dead`/`deleted` (Firebase transiently nulls live items), while a *never-seen* front-page id that fetches null gets a dead placeholder row so it isn't re-pulled every round; `kick()` marshals via `call_soon_threadsafe` (no-op before startup / when source disabled). **Link-preview prefetch** (2026-07-20): `_fill_previews` at the tail of `poll_once` sweeps linkable stories without a stored preview newest-first (`CONDENSER_HN_PREVIEW_BATCH`/round, 0=off; covers fresh, backfilled *and* pre-feature rows) through `preview.get_preview` (warming the shared pane cache) into `hn_stories.preview`; ≤3 real attempts per story (`PREVIEW_MAX_ATTEMPTS`) — a still-fresh negative cache entry skips *without* bumping (the 1h neg-TTL < poll interval would otherwise eat every retry), empty-but-ok results are terminal; injectable `fetch_preview` for tests. `routers/hn.py` = `/api/sources/hn/subscriptions*` + `/api/hn/status` (incl. `source_enabled`); POST = subscribe-and-enable (re-enables a paused row, `schedule_backfill` only on first create), POST/PATCH-enable → 503 when `CONDENSER_HN_ENABLED=false`. Multi-source plan Phase 1: `kb/plans/2026-07-19-multi-source-hn.md` |
| `x.py` | X (Twitter) source, **push model** — the server never talks to X; a local probe (`probe/`) reads the user's logged-in session through the `xbird` library (the `bird` CLI until 2026-08-06; the pushed JSON shape is unchanged, and the server is written against that shape) and pushes it. Owns tolerant `parse_tweet` (string ids → int64, legacy `'%a %b %d %H:%M:%S %z %Y'` timestamps, media/metrics/article passthrough, `quotedTweet` → a self-referential archive row, retweets only recoverable as `rt_of_handle` from bird's `RT @x:` text prefix), `ingest_tweets` (idempotent by tweet id: tweet rows refresh so metrics move, feed rows are insert-only so `first_seen_at` stays sticky; embedded quotes use insert-if-absent so a depth-limited copy can't downgrade a richer row; unkeyable entries are counted and dropped, a drifted field is counted *and* stored since `raw` is archived), `probe_config` (subscription-driven, like HN sampling), `_learn_user_identity` (a followed account's numeric `user_id` + display `name` come from its first push — the handle is the subscription key because that is what a reader types, the numeric id is what survives a rename), and `status` (push activity from `app_meta` `x_*` keys). Since 2026-07-30 it also owns the **Following** feed (`FOLLOWING_FEED`, a third `x_feed_kind` beside `home`/`user`) and the two filters only it needs (`_apply_following_rules`, plan §6.3): ① an entry whose author is not in `x_following` is dropped **whole**, body included — X injects ads with no structural marker, so the follow list is the only test, and an ad is noise all the way down; ② an entry older than `CONDENSER_X_FOLLOWING_MAX_AGE_HOURS` (24) gets its **body archived but no feed row**, reusing the path a quoted tweet already takes — X pads the feed with a thread's own ancestors (measured: one 2025-09 root arriving in a 2026-07 page) and a feed row would land them in timeline history, invisible but counted as unread. Order matters: ① first, so an ad that is *also* old is not merely archived; and both run on feed entries only, never on `_embedded_quotes`. **An empty follow list disables ① entirely** — the deliberate failure mode, since the alternative on a never-synced install is silently discarding every tweet as advertising. `IngestResult` carries `filtered_ads`/`filtered_old` so the subscription row can show them. `routers/x.py` = `/api/sources/x/subscriptions*` + `probe-config` (now also `sync_following`, the server-side staleness decision, so the probe stays stateless) + `following` (whole-list replace; refuses an empty push over a non-empty list, because a transient bird `[]` would otherwise disable the ad filter for a whole sync interval) + `ingest` (Bearer or cookie — the probe is just a device) + `/api/x/status` + `/api/x/avatar/{handle}` (unavatar proxy, `fallback=false` so a miss 404s into the client's letter avatar — bird carries no avatar URL); 503 when `CONDENSER_X_ENABLED=false`, 404 on a push to an unknown/paused feed. `sources/x.py` is the **Phase 2 timeline provider**: `x_feed_items JOIN x_tweets` (+ a self-join for the quoted tweet), read/saved/hidden anti-joins, and a feed-dependent `SORT_AT_SQL` — For You by `first_seen_at`, a followed account by `created_at`. **For You is opt-in**: bird's `home` re-samples every call (~2400 tweets/day at the old n=50), so by default it is excluded from the aggregate timeline and only appears under `?source=x` / `?source=x&feed=…`; since 2026-07-29 the subscription's `config.aggregate` (`none` | `positive` | `all`, HN's `display_mode` pattern) can admit it — `positive` lets through only what the verdict recommends, measured at ~13% of arrivals, i.e. about a fifth added to a ~50-item day rather than a flood. The predicate lives inside the scoped subquery (with the feed filter, so dedup only ranks admissible rows) and `bulk_read_scope` hands the same rule to the bulk-read sweep, because "mark all read" in the aggregate must burn exactly what the aggregate showed and not the For You labeling backlog; `CONDENSER_X_HOME_COUNT` dropped 50 → 20 as the second capacity lever. **Following joins the aggregate in full by default** (2026-07-30) — it is a *stable window*, not a firehose (two consecutive bird calls overlapped 19/20, ~100-200 tweets/day), and it is never judged, so its `aggregate` modes are `none`/`all` with no `positive`: a recommended-only mode would silently hide the whole feed. The admission rule generalized with it — `aggregate_mode(feed)` + `scope()` now drop any feed set to `none`, replacing the hardcoded "everything except For You" that used to live in `db.enabled_x_feeds`. A tweet in several feeds de-duplicates under an **explicit** `ROW_NUMBER()` priority (account subscription > following > For You), no longer "earliest sighting wins": with three feeds a tweet by an account you also subscribe to sits in two non-For-You feeds, and the winner decides its sort timestamp, its admission rule, its verdict badge *and* which sidebar row owns its unread count — which would otherwise drift with whichever push landed first. Plans: `kb/plans/2026-07-24-x-source-local-probe.md`, `kb/plans/2026-07-30-x-following-feed.md` |
| `cleanup.py` | **daily retention sweep** (2026-08-07, on `app.state.cleanup`). The cadence is a **database breakpoint, not a timer**: the loop wakes hourly and asks `app_meta.cleanup_last_run_at` whether a day has passed — `git push` to master is a deploy here, so the process restarts far more often than once a day and an in-memory `sleep(24h)` would rarely survive to fire. The round runs on `asyncio.to_thread` (VACUUM takes an exclusive lock and this process shares one event loop with FastAPI, the TG listener, HN sampling and the verdict; peewee connections are thread-local, so the pooled worker gets its own and `_run_in_thread` hands it back in a `finally`). Rules are duck-typed (`name` / `enabled(settings)` / `run(now, settings) -> CleanupReport`, one `DEFAULT_RULES` tuple) and isolated per rule — a broken future HN rule must not cost X its sweep — while the breakpoint advances unless **every** rule threw, since a transient `database is locked` deserves an hour's retry, not a lost day. Deliberately **no `kick()`**: HN's exists for "subscribe → sample now" and the verdict's for "push → judge now", but no user action makes yesterday's retention scan due sooner. The only rule is `XRetentionRule`, which also absorbed `verdict._prune` — that call sat *inside* the cold-start gate, so an install with too few labels to judge anything had never pruned a vector at all. `GET /api/cleanup/status` exists because at a 15-day window the first weeks legitimately delete nothing, and "ran, found nothing" must not look like "never ran" |
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
  itself** or the gate refetch-loops (`lib/queryClient.ts`).
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

Independent uv package (`condenser-probe`) that runs on the user's own machine — the X
source's fetch half, since X data only exists inside a logged-in browser session. Each
round: `GET /api/sources/x/probe-config` → one X read per feed → `POST
/api/sources/x/ingest`, plus a follow-list re-crawl (~15 requests) whenever
probe-config's `sync_following` says so — the *server* decides, so the probe keeps
no schedule. That sync runs **before** the feeds: the server drops Following entries whose
author is not in the list, so a first round that ingested first would read its own empty
list.

**The X reads go through the `xbird` library, not the `bird` CLI** (2026-08-07;
`condenser_probe/xsource.py`, formerly `bird.py`). `xbird` is Reorx's own Python rewrite of
`@steipete/bird` and ships a library surface, so the subprocess-and-parse-stdout layer is
gone: `home` → `get_home_timeline`, `--following` → `get_home_latest_timeline`, `user-tweets`
→ `get_user_id_by_username` + `get_user_tweets_paged`, `following --all` → `get_current_user`
+ a paged `get_following` loop, `whoami` → `get_current_user`. Four things did **not** change,
each on purpose:

* **the wire shape.** What is pushed is `xbird.types.to_json(tweet)` — byte-identical to what
  `xbird … --json` prints, because the server parses those camelCase keys and archives every
  entry verbatim as `raw`. Handing it pydantic-native snake_case would orphan every historical
  row. Verified on real data: 25 tweets across all three feed kinds through `condenser.x.parse_tweet`,
  0 unkeyable, 0 warnings (`tmp/2026-08-06-xbird-migration/`).
* **failures are per-feed.** xbird returns remote failures as *values* (`result.success`),
  never exceptions; `xsource` raises `XSourceError` on every one, because a failure that read
  as an empty page would report the round OK and hide a dead X session indefinitely.
* **the follow crawl is all-or-nothing.** A failed page raises rather than returning what it
  collected: the server *replaces* the list wholesale and drops Following tweets by authors
  missing from it, so half a list silently discards the rest as advertising.
* **the 1s page pacing** of the follow crawl, which the CLI's `--all` did. Dropping it would
  be an unannounced change in how hard the probe hits X.

The client is built and closed per call (it owns an httpx pool, and `watch` runs for days);
re-resolving credentials each time is what lets a browser re-login take effect without a
restart. Credentials: `resolve_credentials()` → `AUTH_TOKEN`/`CT0` or browser cookies
(Safari → Chrome → Firefox; reading Chrome's needs `/usr/bin/security`, hence the launchd
plist's PATH). xbird is not on PyPI: `pyproject.toml` points at `ssh://git@github.com/reorx/xbird`
(private repo, hence SSH) on `branch = "master"` with `uv.lock` pinning the commit; co-develop
a local checkout with the telememo-style overlay (`uv pip install -e ../../xbird` +
`UV_NO_SYNC=1`). `bird_bin` is gone from the settings; `x_timeout_ms` (per X API request,
20000) joined `timeout` (per condenser HTTP request).

**Live on the probe machine since 2026-08-07 00:08**, and soaked: **74 unattended rounds in
the first 8 hours, 0 errors, 0 tracebacks, 0 parse errors**, both cadences firing on time.
(Re-measure rather than quote — `grep -c "round done" ~/Library/Logs/condenser-probe.log`.)

Note the probe deploys by **restarting the launchd agent**, not by `git push` — `watch` holds
its code in memory, so editing the source changes nothing until
`launchctl kickstart -k gui/$(id -u)/com.condenser.probe`. This bites in a specific way worth
knowing: edit a file *after* a kickstart and the agent silently keeps running the older code,
with nothing on screen to say so (it happened during this very migration — two cleanup edits
landed 35s after the restart). To check rather than assume, compare the process start time
against the source mtimes: `ps -o lstart -p $(launchctl list | awk '/condenser.probe/{print $1}')`.

Two more things measured before going live, both worth re-checking rather than assuming: the
SSH git dependency resolves with **no `SSH_AUTH_SOCK`** (which launchd does not provide), and
the seen-cache file format is unchanged, so old and new code share it.

**Configless** beyond a server URL + device token (env or
`~/.config/condenser-probe/config.json`): the feed list lives on the server, and the server
dedupes by tweet id, so a probe that crashed or slept has nothing to recover. One feed's
failure never sinks the others (`runner.FeedOutcome`), and neither does the follow sync.
The one piece of local state is `cache.SeenCache`
(`~/.cache/condenser-probe/seen/<feed>.json`, pruned to 24h, opt-out via `--no-cache`):
Following is a stable window, so a 15-minute round would otherwise re-upload almost the same
50 tweets — measured on a real second round, 41 of 50 skipped and a followed account pushed
nothing at all, while For You skipped 0 (it re-samples, which is the control). Two
consequences, both accepted (plan decision 2): a tweet's metrics **freeze at first sighting**
(the server refreshes them per push; an on-demand refresh is the follow-up), and if the
server's data is ever wiped the cache would suppress the restoring re-push — hence
`--no-cache`. Recording happens *after* a successful push, never before. CLI:
`condenser-probe check | run [--no-cache] | watch`; **scheduling is in-process since
2026-07-30** (`scheduler.py`, APScheduler): `watch` is the long-running mode launchd merely
keeps alive (KeepAlive plist example in the package), running For You hourly at :05 and
Following + account feeds at :00/:15/:30/:45 — staggered minute lanes plus a one-worker
executor, so two X crawls never overlap, and missed firings coalesce into one catch-up
round per task at wake. On start `watch` runs one full round; `run` = one full round for
cron-style setups. Tests stub xbird + the server, so `uv run pytest` needs no X account
(`test_xsource.py` = the adapter, `test_probe.py` = orchestration over a stubbed fetch).

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
optional (nil → letter avatar, no request). **Multi-source Phase 4 (2026-07-21)**: Kit
models are envelope-based (`TimelineItem` + `HnStory`/`LinkPreview`; `DisplayMessage` lost
its read/saved flags), `CondenserAPI` speaks item keys (`markRead(keys:)`,
`saveRecord(key:)`, `DELETE /api/records/{key}`) + `sources()` (`SourceGroup`/`SourceSub`
with int-or-string `SubChannelID`; `/api/subscriptions` dropped), `TimelineStore`/
`NewContentPoller` take a `source` param, `ReadReporter` queues keys, `SnapshotCache`
dir carries a contract version (`condenser-snapshots-v2`, old snapshots = miss),
`hnPlainText` converts HN self-post HTML in Kit. App: source-switcher Menu top-left of
Timeline (All + added sources from `/api/sources`), tab 2 频道→订阅 (source→subs two-level
list; TG row → channel timeline, HN row → `HnFeedTimelineScreen` = source-scoped store),
`HnCard`/`HnDetailSheet` (title → Safari original / comments for self-posts, meta line,
day-rank, prefetched preview box), Saved/detail dispatch by source, debug routes gained
`hn` + `tab/subs`. Fixtures regenerated as envelopes
(`tmp/make_ios_fixtures.py`: mixed/tg/hn pages, hn_shapes, sources, records incl. a
temp-saved HN record). **Message stats + forward (2026-07-22)**: Kit gains
`ReactionCount` (unknown kind → `.other` forward-compat) / `MessageStats` /
`ForwardResult` / `AppMeta` models and off-protocol `APIClient` methods
(`messageStats`, `forwardMessage` — trims the comment, empty → body without
`comment` = native forward, `appMeta`, `setForwardChannel`); app: stats row in
`MessageDetailSheet` (views/forwards/reaction chips, fetched in the sheet's
`.task` — a `Group { if … }.task` never fires when empty, hence the
presentational `MessageStatsRow`), `ForwardDialog` sheet (preflights
`appMeta` → not-configured guidance / composer / success-with-link states,
error mapping per routers/messages.py), Settings 转发 section
(read/save `forward_channel`), debug route `forward/<cid>/<mid>[/<comment>]`
(auto-submit, real network — walkthrough `tmp/2026-07-22-ios-stats-forward/`).
**Silent refresh + gray toast, no polling (2026-07-22)**: the timeline refreshes by
exactly two paths — the user's pull-to-refresh, and a silent auto-update on cold start /
return-to-foreground after ≥5 min background, which reports itself afterwards via a
**non-interactive gray "N 条新消息" toast** (auto-dismiss 4s, tap = dismiss). The 30s
`/timeline/new` poll loop and its blue tappable capsule were **removed** (user feedback:
interrupting mid-read is annoying) — nothing pops while you read. Kit:
`TimelineStore.loadInitial` returns the new-item count vs the rendered snapshot
(`@discardableResult`) for the cold-start toast; `ForegroundRefreshPolicy` (first-leave
timestamp, threshold check clears state) gates the foreground path; `NewContentPoller`
→ **`NewContentChecker`** (one-shot `check() async -> Int`, no count/reset/start/stop —
failures and missing cursor are 0). App: `MessageListView` owns the whole flow
(`checker:` param, nil for channel/feed views); `TimelineScreen` only flushes reads on
background. Foreground return calls `check()` **first** and only disturbs scroll when
count > 0 (scroll-to-top before refresh, else the new first screen lands above the
viewport and scroll-to-read false-marks it); 0 = reading position untouched. Walkthrough
`tmp/2026-07-22-ios-foreground-toast/`.
**X source (Phase 5, 2026-07-25)**: Kit gains the `XTweet` payload family
(`XMediaItem`/`XMetrics`/`XArticle`/`XQuote`/`XVerdict`+`XVerdictMeta`) plus the
source-generic `ItemFeedback` on the envelope, a `feed` scope on `TimelineStore` /
`NewContentChecker` / the timeline endpoints (X is the first source with *many* feeds),
`setFeedback`/`clearFeedback` on `CondenserAPI` with an optimistic toggle in both stores
(tapping the lit side = undo), and `xAvatarURL`/`proxiedImageURL`. `XTweet` owns the
card's pure logic (`bodyText` strips bird's `RT @orig:` prefix and drops a long-form
post's title-as-text, `displayName`, `tweetURL`/`profileURL`, `photos`). App: `XCard`
(+`XQuoteCard`/`XMediaView`/`XMediaThumb`/`XAvatarView`/`XGlyph`/`XVerdictBadge`/
`XFeedbackButtons`) and `XDetailSheet` (verdict evidence — score + labeled neighbours
with handles + `model@dims` — in Chinese; the card badge keeps web's English),
`XFeedTimelineScreen` reached from the subs tab's X group (**For You's only entry — it is
not in the aggregate timeline**), `ImageViewerItem` generalized to `ViewerPhoto`
(`.telegram(cid,mid)` / `.proxied(url)`), and `TruncatableText` shared with `MessageCard`.
Every image routes through the backend, so reading a tweet never contacts X.
`XVerdict`/`ItemFeedback` decode unknown values to `.other` rather than failing the page.
Debug routes gained `x[/<feed>]`, `detail/x/<feed>[/<id>]` and `tab/subs/<source>`.
161 Kit tests; walkthrough `tmp/2026-07-25-x-phase5-ios/`.
v1 spec complete; remaining polish: end-to-end
`ASWebAuthenticationSession` verify on device, video playback (non-goal).

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
the archive accumulates. **Phase 2 (API multi-source, breaking) is done** (2026-07-19):
item envelopes + keys (`items.py`), `read_items`/`saved_items` v4 migration, federated
timeline merge with composite cursors (`sources/`), `POST /api/read {keys}` /
`/api/records {key}` / `DELETE /api/records/{key}`, `GET /api/sources` (batched names +
per-sub unread), bulk-read covers HN, plus the web frontend mechanical adaptation
(`TimelineItem` envelope types, key-based read/save hooks, source-dispatched cards with a
minimal `HnCard`). Tests: `tests/test_multi_source.py` (31 scenarios) + all legacy tests
migrated (126 backend + 17 frontend green). Phase 2 post-merge review fixes are complete
(2026-07-20, TDD: invalid-cursor 422, merge floor for album-dense pages, synthetic poll
anchors for empty sources, HN new-count buffer, half-mode ceil, aggregate header unread via
`useSources`, records batch read-join — `kb/plans/2026-07-20-phase2-review-fixes.md`).
**Phase 3 (web UI) is done** (2026-07-20): `/s/:source` source-scoped timeline route
(`source` threaded through `useTimeline`/`useTimelineDays`/`useNewContent` + the backend
already supported it; HN view header gets a top-N `HnDisplayModeMenu`, hides the TG-only
refresh button), sidebar reworked to two-level source groups from `GET /api/sources`
(`SidebarSourceGroup`, collapse persisted via `useCollapsedSources` localStorage), the
Subscriptions page split into per-source sections (HN block gains the display-mode menu),
full `HnCard` (day-rank badge, sanitized self-post HTML with a char-threshold "more"
clamp via `lib/sanitize.ts`/DOMPurify, muted job posts, submitted-time shown), and
`LinkPreviewPane` generalized to a `PaneTarget` union (HN story → URL preview +
"Open comments on Hacker News" footer). One small non-breaking backend addition:
`POST /api/read/bulk` accepts `source` so the `/s/:source` mark-all-read doesn't leak
across sources (TDD'd in `tests/test_multi_source.py`; 128 backend + 31 frontend green;
vitest setup now substitutes an in-memory localStorage — jsdom 29 delegates to Node's
inert WebStorage under vitest).
**HN embedded link previews** (2026-07-20, TDD): every archived story URL gets its link
preview prefetched at ingest (`HNManager._fill_previews`) and persisted in
`hn_stories.preview` (SCHEMA_VERSION 5); the envelope's `hn.preview` renders as an inline
`LinkPreviewCard` in `HnCard` and makes the pane open instantly. Purely additive —
doesn't affect the Phase 4 deploy-order constraint (138 backend + 34 frontend green).
**Phase 4 (iOS) is done** (2026-07-21, see the iOS section above): the whole
multi-source plan (`kb/plans/2026-07-19-multi-source-hn.md`) is complete and the
**deploy-order constraint is lifted** — backend + web + iOS all speak the envelope
contract, deploy whenever (rebuild + reinstall the iOS app alongside, deploy-order
decision (b)).
**TG message stats + forward-to-my-channel** (2026-07-22, BDD, plan
`kb/plans/2026-07-21-tg-message-stats-forward.md`): `GET /api/messages/{cid}/{mid}/stats`
reads live views/forwards/reactions via Telethon (never stored; reaction kinds
emoji/custom/other with forward-compatible degradation, `chosen` = own reaction) and
`POST .../forward` republishes into `app_meta.forward_channel` — empty comment = native
`forward_messages`, non-empty = new message `comment\n\n<t.me link>` (server-built URL;
returns the landed message's link). New `routers/messages.py` (same `/api/messages`
prefix as preview.py, split because it needs TgManager) translates
`TelegramMessageNotFound`→404, `LookupError`(no target)→422, FloodWait→429+Retry-After,
`UnauthorizedError`→503. Web: `MessageStatsRow` + Forward button in the pane (TG targets),
`ForwardDialog` (deliberately Chinese copy), Settings "Forward" section. 150 backend +
42 frontend green; accepted live against @telememo_test
(`tmp/2026-07-21-tg-stats-forward/`). iOS UI shipped 2026-07-22 (see the iOS
section above; walkthrough `tmp/2026-07-22-ios-stats-forward/`) — the plan is
fully closed.
**Item detail pane + hidden items** (2026-07-22, BDD): the web pane opened from a card's
time is now `ItemDetailPane` (条目详情) — `ItemDetailInfo` full-info block on top, link
previews as a section, and a 隐藏 action (toast with 撤销 undo) backed by the new
`hidden_items` table / `POST /api/hidden` (SCHEMA_VERSION 6, see Architecture). Hiding is
excluded server-side from every timeline query, so iOS needs no change to stop showing
hidden items. `lib/linkPreviewPane.tsx` → `lib/itemDetailPane.tsx` (context now carries the
whole `TimelineItem` envelope). 161 backend + 45 frontend green; screenshots
`tmp/2026-07-22-item-detail-pane/`.
**X source Phase 1** (2026-07-24, BDD, plan `kb/plans/2026-07-24-x-source-local-probe.md`):
schema v7 + `condenser/x.py` + `routers/x.py` + the `probe/` package + the web X block —
i.e. subscriptions, probe contract, ingest and archive. **Not** in Phase 1: the timeline
(Phase 2), feedback (3), verdicts (4), iOS (5) — nothing X-shaped reaches a reader surface
yet, which is the point: deploy now so the archive and the future training data start
accumulating. Tests use real bird output (`tests/fixtures/x/`, curated by
`tmp/make_x_fixtures.py` from `tmp/2026-07-24-bird-samples/`); 27 X + 188 backend + 11
probe + 45 frontend green, plus a live end-to-end run (real bird → probe → ingest) and UI
screenshots in `tmp/2026-07-24-x-source-phase1/`.
⚠️ **Measured, and it changes the plan's capacity math: `bird home` re-samples on every
call.** Three consecutive calls returned 60 distinct tweets with **zero** overlap, so For
You is a firehose sample, not a stable window — every round ingests ~N brand-new tweets
(n=50 every 30 min ≈ 2400/day, not the plan's assumed ~500). Consequences to settle before
Phase 2/4: probe cadence, the reading volume a For You timeline dumps on you, and the
embedding storage estimate. It also re-validates the `first_seen_at` sort decision (a
`created_at` sort would splice these into timeline history) and means the *For You* leg of
ingest idempotency is unobservable in practice (a followed account's feed does repeat and
correctly reports 0 new).
**X source Phase 2 — timeline** (2026-07-25, BDD): `sources/x.py` provider + `x` in
`items.py` / `timeline.SOURCES` / the source patterns, a `feed` scope on
timeline/days/new/read-bulk, an X group in `GET /api/sources` (per-feed unread),
X saved-record snapshots, `/api/x/avatar/{handle}`, and the web cards + `/s/:source/:feed`
route. The capacity question the Phase 1 measurement raised is **settled** (user decision):
**isolate + throttle** — For You is excluded from the aggregate timeline (visible only in
its own views), and `CONDENSER_X_HOME_COUNT` drops 50 → 20; the archive stays full-fidelity
so Phase 4 training data is unaffected. Author avatars proxy unavatar.io (decision: real
avatars over letter-only). 23 X-timeline + 211 backend + 51 frontend green; live
end-to-end against the dev backend (fixture push → real UI, incl. unavatar avatars and
proxied tweet media) with screenshots in `tmp/2026-07-25-x-phase2-timeline/`.
~~⚠️ iOS gap until Phase 5~~ — **closed 2026-07-25 by Phase 5**: followed-account tweets
used to render as blank rows in the aggregate timeline (the card dispatch only knew
telegram/hn); they now render as `XCard`. See the iOS section above.
**X source Phase 3 — feedback loop** (2026-07-25, BDD): `/api/feedback` POST/DELETE +
`db.set_feedback`/`clear_feedback`, the envelope's `feedback` field (X provider join +
batched records join), `XFeedbackButtons` + `useFeedback` on the web card, and the
pane's 反馈 row. Deliberately inert: labels are recorded and nothing else changes —
no verdict, no hiding, no read side effect — so Phase 4 has training data waiting when
it lands. 11 X-feedback + 223 backend + 58 frontend green, plus a live browser
walkthrough against the dev backend (label → reload → server state → undo, saved
view, detail pane, dark mode) in `tmp/2026-07-25-x-phase3-feedback/`. iOS was deferred
to Phase 5 (it couldn't render X cards yet, so there was nothing to attach buttons to)
and landed there the same day.
**X source Phase 4 — embedding verdict** (2026-07-25, BDD): schema v8 + `vectors.py` +
`embedding.py` + `verdict.py` + `XVerdictBadge` / `XVerdictDetail` + the X status line's
判定 row + `scripts/x_verdict_backtest.py` (see the module table and the v8 block above).
The plan's sqlite-vec choice was **re-litigated and kept** — Chroma resolves to 79
packages (incl. `kubernetes`, `onnxruntime`, `grpcio`, a second web server) *and* makes
labels and vectors two stores with no shared transaction, while a hand-rolled brute-force
kNN trades that same guarantee for saved dependencies; sqlite-vec is 1 package, one file,
one transaction (all four properties smoke-tested through peewee: extension loads,
replays on new thread connections, int64 snowflake rowids round-trip, vec0 rolls back
with ordinary tables). Two deviations from the plan's flow, both to avoid spending money
on shrugs: the **cold-start gate moved ahead of the embedding call** (③ before ②), and
unlabeled For You tweets are not embedded while the gate is closed. Retractions are
processed even during cold start, since deleting from the index costs nothing.
**Real numbers worth keeping** (`text-embedding-v4@256`): same topic across
languages ≈ 0.18 cosine distance, unrelated ≈ 0.80 — `CONDENSER_VERDICT_MAX_DISTANCE=0.6`
sits between them. 32 verdict + 254 backend + 64 frontend green; live end-to-end against
the dev backend (real DashScope embeddings → vec0 kNN → verdict → badge) with
screenshots in `tmp/2026-07-25-x-phase4-verdict/`. ⚠️ **The classifier is unvalidated**:
Phase 3 shipped the same day, so the real label count is ~0 and the production gate
(20/20) keeps every verdict `null` until the user has labeled enough. Accuracy is a
question for `x_verdict_backtest.py` later, and the ± thresholds stay placeholders
until it has real data.
**X source Phase 5 — iOS** (2026-07-25, BDD; the plan is now fully closed): the whole
X surface lands on iOS — envelope payload + feedback in Kit, `feed`-scoped stores,
`XCard`/`XDetailSheet`, the subs-tab X group as For You's only entry, and the verdict
badge + its evidence. 41 new Kit scenarios (161 total) + 256 backend green; simulator
walkthrough against the dev backend (real bird data + real DashScope verdicts) in
`tmp/2026-07-25-x-phase5-ios/`. Web and iOS now render the same X contract.
**Verdict thresholds are settled, and the negative side is OFF** (2026-07-27, closes the
2026-07-26 TODO): the gate opened the moment the training set crossed 20/20 (30 👍 / 29 👎),
the first real round ran `indexed=59 judged=82`, and a leave-one-out backtest over a
production snapshot turned the placeholders into decisions:

| | result |
|---|---|
| positive, D0.60 / M3 / `>= 0.25` | **100% precision** over 8 calls, 13.6% coverage — double 0.35's coverage at the same precision |
| negative, every grid cell | best **55.6%** precision against a **49.2%** base rate — statistically it knew nothing |

So `condenser_verdict_positive_score` is now **0.25** and the new
`condenser_verdict_negative_enabled` defaults to **false** (`verdict.score_neighbours`
gates the branch; the score and neighbours are still archived, so flipping it on needs no
backfill). Why the asymmetry is a *property of the labels*, not a tuning failure: 24 of the
29 downs were style judgements (`promo` 11, `engagement_farming` 10, `ai_slop` 3, `author`
1) and only **1** was `topic` — a topic embedding cannot represent style, so those downs
only dragged on whatever subject they happened to be attached to. Per-reason recall makes it
concrete: at D0.60/M3/−0.45 the model recovered 2 of 11 `promo` downs and **0 of everything
else**. The `reason IS NULL OR reason='topic'` variant the note asked for was run too and is
**not** the fix at this size — it leaves 4 negatives, and its flattering 88% positive
precision is just the 30/34 base rate of a classifier that calls everything positive.
Re-run `scripts/x_verdict_backtest.py --sweep` (plus `tmp/x_verdict_variants.py`, which
decouples the two thresholds and breaks recall down by reason) against a **copy** of the
production DB before moving any of these — the sweep trashes and rebuilds the KNN index per
fold. `CONDENSER_X_HOME_COUNT` went 20 → 10 → **20 again on 2026-07-27**, raised to fill the
training set faster; prod reads the code default, so no prod env var is needed.
**Scope check — tuning these constants is not "the verdict is done".** The design note
(`kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md`, the authority on where this
algorithm is going) classes today's single-channel dense kNN as a **v1 baseline / control
group**, because it has a defect no threshold can reach: one tweet gets one vector, so
topic, tone and author are averaged into a single point and "I hate this phrasing" is
indistinguishable from "I hate this topic". Settling D_MAX and the ± thresholds calibrates
the baseline; the note's target shape is a multi-channel ensemble (author prior + this kNN +
LLM attribute extraction + n-gram Bayes + a combiner), with **each channel independently
switchable and independently backtested** so the data picks the architecture. The 2026-07-27
backtest is the first evidence that this is not just theory: **the entanglement defect is
what killed the negative side**, and no threshold reached it. The next phase is specced as a
standalone handoff — `kb/plans/2026-07-27-x-verdict-style-channels.md` (channels C/D, the
combiner, the extended backtest harness, and the written-down bar for ever re-enabling
negative verdicts). Which makes the extra channels
the actual roadmap for negatives — the reason mix says which ones pay first: `promo` (11) +
`engagement_farming` (10) + `ai_slop` (3) = 24 of 29 downs are style, i.e. exactly channel C
(LLM attribute extraction) and channel D (n-gram Bayes) territory, while `author` had 1 and
channel A (author prior) stays near-zero cost. The labels before 2026-07-26 carry `reason`
NULL — a real discontinuity, not missing data.

**判定 v2 steps 0–1 — the harness, and channel D exists** (2026-07-27, BDD; plan
`kb/plans/2026-07-27-x-verdict-style-channels.md`). Step 0 rebuilt
`scripts/x_verdict_backtest.py` around channels (see its row above) and folded in the
throwaway `tmp/x_verdict_variants.py`; step 0's own acceptance test was reproducing the
2026-07-27 channel-B numbers exactly (13.6% coverage, 100% positive precision over 8 calls,
`promo` 2/11 recalled and 0 of everything else). `verdict.score_neighbours` was split into
`topic_score` (the vote, as a `ChannelScore`) + `classify` (the thresholds) so the harness
measures the code production runs.

Step 1 shipped channel D. **It has real signal, and the first three attempts at it did
not** — worth keeping, because each failure was a different way to be at the base rate:

| attempt | what the numbers said |
|---|---|
| sum of top-k log-odds | called 78% of everything negative at **54.3%** (base 49.2%); *no* upvoted tweet scored positive — a sum grows with length and downs run 30.8 informative tokens against ups' 15.3 |
| + mean, + `min_weight` floor | 69.7% precision, but the whole scale sat below zero: best up −0.05 |
| + centering per **token** | scale fixed, ranking destroyed (36.4% positive precision) — the offset changed *which* tokens ranked as evidence |
| + centering the **score**, offset measured leave-one-out | up median +0.07 / down −0.31; `neg <= -0.45` → **86.7% over 15 calls** |

The diagnostic that turned this around was **AUC** (`tmp/x_ngram_variants.py`): every
variant sat at 0.78–0.85, so the information was there all along and only the calibration
was broken — precision-at-a-threshold had been answering "is the ranking good" and "is the
scale right" at once, and therefore neither. Channel D's *positive* side is also live
(100% over 9–10 calls at `top5 |w|0.0`), which was not expected of a style channel.

**判定 v2 step 2 — the attribute pipeline** (2026-07-28, BDD): schema **v10** adds
`x_attributes` (a new table, so the upgrade is plain `create_tables`; a rebuildable cache
like `x_embeddings` — the text is still in `x_tweets`), plus `condenser/attributes.py` (see
its module row), `verdict.run_once`'s `_describe` step and an `attributes` block on
`/api/x/status`. Extraction runs **after** judging and **inside** the cold-start gate: it
must not delay the verdicts the reader sees, and a fresh install must not pay to describe
tweets for a verdict it cannot make. Labeled tweets are described first — they are the
training data channel C will score against, and there is a fixed backlog of them while
unlabeled For You tweets arrive forever. Storage is validated at the write boundary as well
as at the parser (`attributes.clean`), so the table cannot hold a flag nothing can score
regardless of which path produced it. **Nothing scores on attributes yet** (step 3); this
step only starts the data accumulating, which can only happen forwards.

**判定 v2 step 3 — channel C scores** (2026-07-28, BDD): `attributes.fit_flags` /
`score_flags` turn the stored attributes into a `ChannelScore`, with **reason-directed
credit assignment** — a down whose chip says 「广告营销」 charges the promo flags, not the
emoji that happened to share the tweet. Headline on 59 labels: `neg <= -0.25` → **80.8%
precision over 26 calls** at a 49.2% base rate, the widest coverage any negative side has
managed — though honestly it is currently a `promo_cta` detector, since that one flag has
18 observations and every other is under 3.

Two design rules were **overturned by the data**, both worth keeping in mind:

* *"a chip that matches no extracted flag charges nobody"* was wrong. Upvotes are credited
  to every flag in full (an upvote has no chip and never can), so any flag the chips fail
  to reach can only gain positive evidence: `humblebrag` came out at **+0.600 while sitting
  on seven downvoted tweets**. It now falls back to the bag-level share (+0.043). `topic` /
  `author` still charge nobody — there the reader said the problem is *not* the style.
* *"thin flags shout loudest"* was the wrong diagnosis for the unreliable negative tail.
  `tmp/x_flag_drivers.py` showed the five most negative scores in the set are **upvoted**
  promo tweets: holding one out removes one of `promo_cta`'s only five upvotes and makes
  the flag look worse precisely on the fold where it is wrong. Leave-one-out variance on a
  dominant flag — no scoring rule reaches it, only more labels. (Evidence shrinkage stayed,
  under the rationale that does hold: `thread_bait` at -0.600 off three sightings must not
  outrank `promo_cta` at -0.405 off eighteen.)

Chip↔extractor alignment, which is what makes directed credit possible at all: `promo`
matched an extracted flag **11 of 11** times, `engagement_farming` 4 of 10, `ai_slop`
**0 of 3** — what the reader calls AI slop and what qwen-flash calls `ai_slop` are not the
same thing yet. **A finding for step 4**: the channels' scales are not comparable (C spans
about [-0.4, +0.1] where B and D span [-1, +1]), so a plain weighted mean dilutes the
sharper channel — the b+c+d mix scored 100% over 7 calls where B alone managed 100% over 8,
and its negative side never spoke. The combiner needs per-channel calibration or a vote,
not an average. 337 backend green (52 new behaviour tests across steps 0–3); the analysis
scripts that produced these numbers live in `tmp/` and are listed in the plan's §12.

**Nothing shipped to production.** `condenser_verdict_negative_enabled` stays false and the
verdict still runs channel B alone — D is reachable only from the backtest until the
combiner (step 4). Two reasons beyond the plan's ordering: that 86.7% was picked out of 88
negative operating points scored on the same 59 labels (selection bias; the 95% interval on
15 calls is roughly 60–98%), and the plan's §9 condition 4 — *no upvoted or saved tweet
among the wrong negatives* — is **unsatisfiable as written in a leave-one-out backtest**,
where every sample is labeled and so every wrong negative is by definition an upvoted
tweet. That condition needs a decision (strictest reading = 100% precision; likely intent =
no *saved* item among the misses) before anyone can claim the bar was cleared.

**判定 v2 步骤 4 — 投票组合器 + 接线** (2026-07-28, BDD; §7/§9 of the plan were
**revised first, by user decision**, and the code follows the revision): the combiner is a
**vote** (`channels.resolve`), not the planned weighted mean — the step-3 backtest showed the
channels' scales are incomparable and the mean dilutes the sharp channel, and the revised §9
(admission + badge-only **prospective validation**, replacing the one-shot retrospective gate)
needs verdicts attributable to the channel that cast them. Wiring: `CONDENSER_VERDICT_CHANNELS`
(default `b` — **production behavior is unchanged by deploying this**), per-channel thresholds,
double-gated negatives (master + per-channel admission), additive `verdict_meta.channels`,
`/api/x/status` reports the channel list; web `XVerdictDetail` + iOS `XDetailSheet` render the
per-channel votes (iOS decodes the block tolerantly — a malformed `channels` degrades to nil
instead of failing the page). The backtest gained a vote-combined report beside the rejected
mean baseline; on the 2026-07-27 snapshot (59 labels, all negatives admitted for evaluation):
**b,d vote = 93.8% negative precision over 16 calls (coverage 27.1%) — the first operating
point to clear §9's numeric bar, starred by the script** — and b,c,d vote = 100% positive over
13 calls (vs B alone's 8; C's negative veto cancels D's one wrong positive) with 83.3%/30 on
the negative side (C's wide -0.25 point dilutes below the bar). Conflicts: 2 of 59. The usual
caveat stands: those numbers carry selection bias (same 59 labels picked and scored), which is
exactly what the revised §9's prospective monitoring is for. Step 5 is now an **admission
decision** (first candidate: D's negative side, or the b,d vote), not a code task. Tests:
352 backend + 81 frontend + 173 Kit green; live end-to-end (snapshot copy, real DashScope,
channels=b,c,d) with screenshots in `tmp/2026-07-28-x-verdict-v2-step4/`.

**判定 v2 步骤 5 — 前瞻监控，以及「一个都不准入」** (2026-07-28, BDD; plan §10.5): the
missing §9 artifact shipped — `condenser/prospective.py` + `scripts/x_verdict_prospective.py`
+ 12 behaviour tests (364 backend green) — and then **the decision it was built to inform went
the other way**. Two measurements, both from a fresh production snapshot:

* **the backtest's operating points did not survive 17 more labels.** 59 → 76 labels (39 down
  / 33 up / **4 saved**, the first saves ever): the starred b,d vote fell from 93.8% over 16
  calls to **71.4% over 21, with 2 saved items condemned**; D alone 86.7%/15 → 61.5%/13;
  channel B's shipped *positive* side 100%/8 → **62.5%/16** against a 48.7% base rate. Across
  the whole 88-cell sweep **nothing clears §9's bar**. The plan's own warning (a 86.7% over 15
  calls has a ~60–98% interval, and it was picked out of 88 cells scored on the same labels)
  was confirmed within a day.
* **the prospective sample, which cannot be tuned against, is worse.** 18 judged-then-labeled
  pairs exist: B's positive badge is **0 for 2** in production (reasons `topic` and `author` —
  the topic channel getting the topic wrong out of sample), and its shadow negative condemns a
  *saved* item at every threshold that fires at all (2 of 2 at −0.45; 3 of 6 at −0.25). Three
  of the four saved tweets sit in B's negative tail (−0.456 / −0.469 / −0.326) — the
  entanglement defect running the other way, since the reader saves things topically adjacent
  to what he downvotes.

So `condenser_verdict_negative_enabled` stays false, `CONDENSER_VERDICT_CHANNELS` stays `b`,
and the honest reading of the label budget changed: **numbers off ~60 labels are not evidence**,
and the next backtest is not worth much before ~150. Two things surfaced that block the next
round of evidence (plan §13.6/§13.7): ~~production is still running pre-step-0 code~~ (no
`x_attributes` table, schema v9 — so C and D have never scored a single production tweet), and
turning them on to fix that would badge readers with C's 33% / D's 64.7% positive precision.
The proposed unblock is a **shadow-channel mode** — score and archive into `verdict_meta`,
cast no vote — which makes §9's prospective validation cost nothing at all.
⚠️ **Both blockers are closed — do not read the struck clause as current.** It stood here
unmarked for a day after the step-5b block below recorded the deploy, and cost a later session a
confidently wrong answer about production. Measured on the box 2026-07-29 **15:59 UTC** (a reading
this precise goes stale by design — re-measure rather than quote it): schema **v10**, image revision
**`10daa6d`**, `x_attributes` re-extracting under `qwen3.7-flash@v2`, shadow **`c,d,a`** live.
**Check, don't infer**:
`ssh -p 1122 root@<PROD-HOST>` → `docker inspect ghcr.io/reorx/condenser:latest --format
'{{index .Config.Labels "org.opencontainers.image.revision"}}'`, and read
`app_meta.schema_version` out of `/data/condenser.db`, and `GET /api/x/status` for which channels
are actually live.
⚠️ **`git push` to master IS a production deploy.** `.github/workflows/deploy.yml` (CD restored
2026-07-19 via hookploy): push → build → push to ghcr.io → `POST /hooks/condenser`, and the
hookploy edge on hh-hk-01 pins the digest and recreates the container. Treat pushing as an
outward-facing action, not as syncing a remote. Two stale sources say otherwise and both are
wrong as of 2026-07-29 — the deploy workspace's `ansible/playbook.yml` comment ("deploys are
manual … the repo's CI webhook step was removed") and an earlier revision of this very
paragraph. The workflow file is the authority. Note also that the compose env — including
`CONDENSER_VERDICT_SHADOW_CHANNELS` — lives in the ansible role template, not in `.env`, and
hookploy only repins the image: a template change still needs an ansible run to land.

**For You 的推荐进主时间线** (2026-07-29, BDD): the Phase 2 capacity decision — For You is a
firehose, keep it out of the aggregate — was made against the *whole* feed. Filtering by the
verdict changes the arithmetic, measured on production: For You arrives at 57–136 tweets/day
of which ~13% are judged positive, against ~50 Telegram messages/day, so the recommendations
are about a fifth more reading rather than a flood. The For You subscription's
`config.aggregate` (`none` default | `positive` | `all`) now decides, following HN's
`display_mode` pattern — a setting rather than a constant because the right answer tracks how
good the classifier currently is, and that moves with every label. `sources/x.py` owns the
rule (`aggregate_mode`, `is_aggregate`, the predicate inside `_scope_where`), and every
surface that counts derives from it: the page, `/timeline/days`, `/timeline/new`, and
`bulk_read_scope` — the last one matters most, since "mark all read" in the aggregate must
burn exactly what it showed and not the For You backlog the classifier still learns from.
`/api/sources` gained **`aggregate_unread`** beside `unread`: the sidebar row opens the feed's
own view (all 8) while the badge above it promises the aggregate (the 1 admitted), and summing
the first into the second is why that badge already advertised a backlog no view could
produce. Web: `XAggregateMenu` on the For You row (a followed account has no choice to make).
No iOS change — it decodes envelopes generically and already renders X cards in the aggregate.
379 backend + 82 frontend green; browser walkthrough in `tmp/2026-07-29-x-aggregate-mode/`.

**判定 v2 步骤 5b — 影子通道** (2026-07-28, BDD, plan §10.6): `CONDENSER_VERDICT_SHADOW_CHANNELS`
lands the unblock above. Listed channels score every judged tweet and archive it, and vote on
nothing; `scripts/x_verdict_prospective.py` then replays those scores at any threshold against
labels that arrived *after* the verdict, so channel C or D can earn admission out of production
data without a single badge changing. Details worth keeping: a channel listed as both voting and
shadow **votes** (a typo must not mute an admitted channel); shadow entries are marked
`{"verdict": null, "shadow": true}` because an abstaining channel is *absent* from the block, and
"not allowed to speak" must not look like "nothing to say"; and attribute extraction now runs
before judging whenever C **votes or shadows** — a tweet is judged once, so a late attribute is
never archived at all. Web + iOS render the tag (both already decoded `verdict` as nullable).
Verified end-to-end on a production snapshot copy with real DashScope + qwen-flash: the same
48h window judged twice, `channels=b` vs `+shadow=c,d` — **100 verdicts, 0 changed, 0 top-level
scores changed**, with shadow scores on C 23/100 and D 64/100 (C's coverage is the
`condenser_attr_batch=40`/round backlog, and climbs on its own). 371 backend + 82 frontend + 174
Kit green; artifacts in `tmp/2026-07-28-x-verdict-v2-step5/`.
~~⚠️ Production still runs pre-step-0 code~~ — **deployed 2026-07-28 evening**: production is on
schema v10 with `x_attributes` filling (255 rows by the next morning), `CONDENSER_ATTR_API_KEY`
set, and `CONDENSER_VERDICT_SHADOW_CHANNELS: c,d` in the **`docker-compose.yml`** (not `.env` —
it is a non-secret measurement setting, so its value belongs in the repo; look there, not in the
env file, when auditing which channels are live). First shadow entries are stamped
2026-07-28 16:26. So C and D are now accumulating prospective evidence on real traffic, and
`scripts/x_verdict_prospective.py --sweep` is the thing to run once the pairs pile up.

**判定 v2 步骤 5c — 通道 C 的记账修正与抽取器换代** (2026-07-29, BDD). Started as an
explanation of `promo_cta` and ended in three changes, because explaining it surfaced a defect.

*The defect.* `fit_flags` credited a downvote only to the flags its chip accuses (by design —
that is what the chips are for) but credited an upvote to **every** flag on the tweet in full.
One-directional by construction: a flag the chips rarely reach could gain positive evidence and
never lose any. Measured on 104 production labels, `ai_slop` scored **+0.429 while sitting on six
downvoted tweets** and `emoji_spam` **+0.200 on 1 up against 6 downs** — the latter because it
appeared in *no* chip's list at all, a hole the `REASON_FLAGS` test could not catch since it only
pinned the mapping's *chip* side. Both flags were also pushed below `min_observations`, so the
bias silenced them twice. This is the same class as the step-3 `humblebrag` bug, whose fallback
fix only reached downs whose chip matched *nothing*.

*The measurement that refused to decide.* Four credit rules (directed / down-residue /
symmetric-up / undirected) were run through the real leave-one-out machinery
(`tmp/x_credit_rule_backtest.py`, `tmp/x_credit_rule_overlap.py`). They condemned **the same 48
tweets, every one driven by `promo_cta`** — the rules only rescale, and the threshold grid
follows. Precision could not tell them apart (79.6–81.2%), so the rule was chosen on mechanism
instead: **credit follows attribution, on both sides** — an upvote attributes nothing and is now
spread across the tweet's flags exactly as an unattributed down already was. `emoji_spam` joined
`engagement_farming` (user decision), and a test now pins the mapping in **both** directions.

*The actual cause was upstream.* Those 48 condemnations included 9 the reader had liked or
saved, all carrying `promo_cta` — an extraction problem no accounting rule can reach. And
`system_prompt()` was sending **bare flag names**: the taxonomy's meanings lived in Python
comments and never left the process, so `ai_slop` arrived as a naked token (the model read it as
machine-written spam; the reader means the LLM explainer *register*, which is why 0 of 3 chips
aligned). `FLAG_GUIDE` now ships a definition with every flag, `TAXONOMY_VERSION` → **v2**, and
`condenser_attr_model` → **qwen3.7-flash** (verified on DashScope; `qwen3.7-flash-2026-07-15`).

*Re-extracting the 104-label set under `qwen3.7-flash@v2` (real calls, snapshot copy):*

| | v1 (`qwen-flash`, bare names) | v2 (`qwen3.7-flash`, definitions) |
|---|---|---|
| tweets carrying any flag | 60 / 104 | 30 / 104 |
| `promo_cta` up/down | 9 / 39 | **2 / 22** |
| negative precision | 81.2% (48 calls) | **91.7% (24 calls)** |
| saved items condemned | 2 | **1** |
| `ai_slop` chip alignment | 0 / 3 | 1 / 3 |

Half the coverage, and the failure mode largely gone: the flag stopped firing on tweets the
reader likes. **§9's bar is 3 of 4 met** — ≥85% ✓, ≥15 calls ✓, above the 53.8% base rate ✓,
**one saved tweet still condemned ✗** — so `condenser_verdict_c_negative_enabled` stays false and
C stays a shadow channel. Two honest caveats: C is *still* effectively a `promo_cta` detector
(every other flag now sits at 1–3 observations, so the threshold is inert across −0.25…−0.45),
and its positive side has never made a single call. `condenser_verdict_c_min_observations` was
lowered 6 → 4 and then **put back**: it was measured under v1, where symmetric credit cost
`thread_bait` the gate, but under v2 nothing except `promo_cta` clears *any* gate, so 4 bought
no measurable difference while loosening the only thing between a thinly-observed flag and a
verdict — and `score_flags` lets the most negative flag decide alone. Revisit when a second flag
accumulates real observations. 402 backend green. **Deployed 2026-07-29 15:59 UTC** — image revision
`10daa6d`, container recreated, restarts=0. As predicted, the `model_tag` change requeued every v1
attribute row: measured on the box right after, `x_attributes` held `qwen-flash@v1` 251 +
`qwen3.7-flash@v2` 40, i.e. one `condenser_attr_batch` round done and ~6 to go (pennies). Both
flavours coexisting until it drains is the `model_tag` contract working, not a migration bug.

**判定 v2 步骤 6 — 通道 A（作者先验）落地** (2026-07-29, BDD; `condenser/authors.py`). The plan
listed this channel first and then deferred it — of the first 29 downs only **one** carried the
`author` chip, which looked like "nothing to learn". That confused the *chip* with the *signal*:
the prior never needed you to say "I dislike this person", only to keep saying no to their posts.

What reopened it was a measurement. The reader asked whether the shipped machinery could reliably
catch the Interactive Brokers ads in For You. The archive held **14 @IBKR tweets, every one an ad,
6 downvoted** — the most-downvoted account there is, arriving roughly hourly — and production had
judged **all 14 `neutral`**. Rescoring them offline said why no text channel is the answer:
B abstained on 6 of 14 as `out_of_domain` (an ad account rotates its subject — futures, FX, gold,
oil, equities — and each rotation is a neighbourhood with no labels in it) and at judging time
never once reached its own threshold; C abstained wherever the extractor had not run; D abstained
on 4 of 14. **The author was present all 14 times.** Channel A now scores all 14 at −0.51…−0.56
against a −0.25 threshold — a 0.26 margin where C's is 0.046, *and* C's score for the same tweet
drifted 0.12 in a single day (−0.176 on the 0728 snapshot → −0.296 on the 0729 one, i.e. it crossed
its own threshold overnight). That margin-vs-drift ratio is the whole case for the channel.

Design: Beta-smoothed counts (`ALPHA=1.0`, `CONFIDENCE_SMOOTH=2.0` — deliberately below channel
C's 5.0, because an author appears as often as you have judged them, 2–6 times for everyone but
@IBKR, and at k=5 a six-times-downed account would still score at half strength). It replaces the
hard rule the analysis started from (`>= 2 downs and no positives -> negative`, 92.9% over 14 LOO
calls) because that rule has a cliff at its centre: one upvote acquits outright, the second down
convicts outright. Smoothing keeps the ordering and removes both cliffs — measurably: the hard
rule's only wrong call was @yibie (3 downs, 1 up), and the smoothed channel puts them at −0.222,
just above the line, so **that miss does not happen in production at all**. `save` counts ×2 like
everywhere else. The channel **reads no text**, which is its strength (never abstains on an account
you have judged) and its limit (blind to an account you have not) — stated as a test, not a caveat.

Backtest on 104 real labels (base rate 53.8% neg): `neg <= -0.25` → **92.9% over 14 calls**,
`-0.35` → 90.9%/11, `-0.45` → 100%/6, and **no saved tweet condemned at any threshold** — which no
other channel manages (the b,c,d vote condemns five). It is still one call short of §9's 15, and a
backtest is selection-biased by construction, so `condenser_verdict_a_negative_enabled` defaults
**false** and the channel earns admission through the step-5b shadow protocol. Wiring is the step-4
contract unchanged: `CHANNEL_KEYS` (one tuple, so a channel that reaches `channel_policy` but not
the config list cannot exist), per-channel thresholds, double-gated negatives, additive
`verdict_meta.channels`. `db.x_pending_verdict_rows` gained `author_handle`; `_fit_channels` tallies
handles the round already loaded for B's evidence, so the channel costs **no API call, no table and
no index**. `prospective.shadow` now replays A's corroboration **exactly** (its rule *is* the down
count in its own archived evidence, unlike B's neighbour count, which is capped at 5 and therefore
an upper bound). Web + iOS render its evidence as a sentence — `@ibkr · 你踩过 6 次，赞过 0 次` —
the only evidence in the pane that needs no metric to read.
Verified end-to-end on a production-snapshot copy with real DashScope: the same window judged
`channels=b` vs `+shadow=a` — **100 verdicts, 0 changed, 0 top-level scores changed**; channel A
spoke on 9 of 100 (91 abstentions are accounts never labeled — the blind spot, working as
designed), 6 of them the @IBKR rows at −0.5625, and @yibie at −0.222 below the line.
399 backend + 83 frontend + 175 Kit green; artifacts in `tmp/2026-07-29-ib-check/`.
**Shadow mode is live in production since 2026-07-29 15:59 UTC**: the ansible role template
(`roles/condenser/templates/docker-compose.yml.j2:34`) and the running container both carry
`CONDENSER_VERDICT_SHADOW_CHANNELS: c,d,a`, on image revision `10daa6d` — so A scores and archives
and badges nobody. **There is nothing to configure; the next step is reading, not deploying.** No
`a` entry existed in `verdict_meta` yet at deploy time (the 69 blocks then present were the previous
build's `b/vote` 67, `c/shadow` 32, `d/shadow` 60) — expected, since A abstains on every account you
have never labeled (9 of 100 in the offline run). Let the probe push for a while, then read
`scripts/x_verdict_prospective.py --shadow a --sweep` before considering
`CONDENSER_VERDICT_CHANNELS: b,a` + `CONDENSER_VERDICT_A_NEGATIVE_ENABLED`.

**X Following 时间线** (2026-07-30, BDD; plan `kb/plans/2026-07-30-x-following-feed.md`,
schema **v11**). `bird home --following` gives the chronological "accounts you follow"
timeline, and the measurement that made it worth doing is that **it is not a firehose**:
two consecutive calls overlapped 19/20 where For You's overlapped 0/60. So the ingest
volume stops depending on probe cadence — it is just what the people you follow posted,
~100-200/day — and it joins the aggregate timeline in full by default rather than being
isolated the way For You was.

X pads that feed with two things nothing else in the project has to handle, and each got a
rule (`x._apply_following_rules`; both Following-only, both on feed entries only):

* **Injected ads, 7 per 100.** They carry no structural marker at all — `--json-full`'s
  `_raw` has no `promotedMetadata` because bird dumps the tweet result, not the timeline
  entry, and `promoted`/`advertiser`/`socialContext` hit 0/20. Filtering by author against
  the follow list caught **7 of 7 with no false positive**, so that is the rule, and the
  list lives on the server (schema v11 `x_following`, pushed by the probe) because the
  server owns the archive: a rule applied probe-side throws away data nothing can recover.
  Ads are dropped **whole**, body included. **An empty list disables the filter** — the
  deliberate failure mode, since on a never-synced install the alternative is silently
  discarding every tweet as advertising (its own behaviour test).
* **A thread's own ancestors.** X drags them in for context and bird flattens them into
  ordinary entries; one measured chain reached back to 2025-09 inside a 2026-07 page. Those
  get their **body archived but no feed row** — the path a quoted tweet already takes — so
  they cannot land in timeline history where they are invisible but still counted as
  unread. `CONDENSER_X_FOLLOWING_MAX_AGE_HOURS` = 24, and the measurement says the line sits
  in a gap: 12h and 24h discard *exactly the same* entries.
  **A rejected condition, do not put it back**: "older than 24h **and** a duplicate id".
  It is backwards — ancestors are first sightings, so the id clause waves through precisely
  the case being treated, while "an old tweet we already have" is a no-op anyway
  (`x_feed_items` is insert-only).

The dedup tie-break became explicit with the third feed (account > following > For You).
Not cosmetic: the winning row decides the sort timestamp, the aggregate-admission rule, the
verdict badge and which sidebar row owns the unread count — under the old "earliest sighting
wins" all four would drift between two rows depending on which push landed first. And the
aggregate admission generalized: `aggregate_mode(feed)` + `scope()` now drop any feed set to
`none`, retiring the hardcoded "everything except For You" in `db.enabled_x_feeds`.
Following's modes are `none`/`all` — **no `positive`**, because it is never judged and a
recommended-only mode would silently hide the whole feed.

Consequence worth stating, because it is a feature and not an oversight: **the verdict now
has no say over accounts you follow.** A measured 25% of For You is people you follow, and
those tweets reach the aggregate through Following instead, badge-free. That is the right
reading of "Following" — the verdict exists to filter strangers the algorithm picked. Two
good side effects: the aggregate total is *less* than the sum of the feeds (Following
absorbs part of For You), and labels collected on un-badged cards are the unbiased sample
`prospective.py` currently cannot get.

The probe gained its first local state, `SeenCache` (see the probe section) — the price of
a stable window is that re-pushing it every 15 minutes is nearly all waste. 435 backend +
27 probe + 87 frontend green; **no iOS change** (envelopes are generic and `feed_kind`
degrades — both clients only test `== 'home'`). End-to-end acceptance against real bird +
the dev backend, all six plan scenarios, in `tmp/2026-07-30-x-following/` (read its
`README.md` — the scripts there are re-runnable).
**Deployed 2026-07-30**, image revision `9cdbfe4`, schema v11 on the box, restarts=0.
Nothing changes on screen until the **Following subscription is added** (which is a click on
the Subscriptions page, not a deploy) — but the follow-list crawl starts on the next probe
round regardless, because `sync_following` only needs *some* enabled feed, so the ad filter
is armed before the feed exists. The local launchd agent still fires **hourly**; the 15-min
cadence Following was sized for needs the installed plist edited (the repo only carries the
`.example`).

**X 归档每日清理** (2026-08-07, BDD; `condenser/cleanup.py`, session
`kb/sessions/2026-08-07-x-archive-daily-cleanup.md`). The archive only ever grew. Measured on a
production snapshot: `x_tweets` is 6147 rows / **10.3 MB = 48% of the database** at 1.68 KB a row,
growing ~700 feed rows + ~60 embedded-quote bodies a day ≈ **1.2 MB/day ≈ 440 MB/year** — while
`read_items` holds 447 X rows against 5596 feed rows, i.e. **92% of it was never opened**. So a
daily round deletes what is old *and* untouched, and 15 days of retention turns that curve into a
~18 MB plateau.

The rule reads backwards until you say it out loud: an **unread** old row is deleted and a **read**
one is kept forever, like TG messages and HN stories never expire. Step 1 drops `x_feed_items`
older than `condenser_cleanup_x_retention_days` (15) by `first_seen_at` — the backlog clock, not
the timeline's `SORT_AT_SQL`, since an account backfill hands us months-old tweets that should sort
into history without being deleted the next morning — exempting anything with a `read_items` /
`hidden_items` / `item_feedback` / `saved_items` row. Step 2 then deletes bodies with no surviving
feed row, not quoted by a surviving tweet, same exemptions; this one sweep also collects the
pre-existing orphan class (embedded quotes + Following's out-of-window ancestors, ~13% of the table
and never reachable from a feed-scoped rule). Step 3 cascades into `x_embeddings` / `x_attributes`
by anti-join, so it heals orphans it did not create. `x_vec_labeled` needs nothing — it holds only
labeled tweets, which are exempt.

Four things are worth not re-deriving:

* **The body sweep loops to convergence, not one pass a day.** A `DELETE` evaluates its `WHERE`
  against the pre-statement state, so in A→B→C, B still sees A and survives the pass that removes
  A. Measured: one pass left **17.5%** of the deletable bodies behind. The loop terminates because
  a quote always points at an older tweet. Do not "fix" this back into a single statement.
* **`x_tweets.fetched_at` means *last* seen, not first archived** — `upsert_x_tweet` refreshes it
  on every re-push. Measured drift: max 1.9 days on Following, **11.9 on For You**. That is why
  the feed-row delete also requires the probe to have stopped pushing the tweet: without it, a row
  deleted at 15 days gets recreated by the next push with a fresh `first_seen_at` and a
  long-ignored tweet resurfaces at the top of the unread list. Unreachable today (11.9 < 15) but
  guaranteed the moment an account feed is subscribed, and it costs 0 rows at the default window.
* **`PRAGMA freelist_count` reads correctly through the WAL** — verified, not assumed: identical
  from a fresh connection immediately after a delete, unchanged by a passive checkpoint. No
  checkpoint step is needed before the VACUUM decision.
* **VACUUM's transaction boundary is enforced by SQLite itself** (`cannot VACUUM from within a
  transaction`), so an unmocked VACUUM test is what guards it. It fires only when a round deleted
  something *and* `freelist/page_count > 0.20`; in steady state the next day's inserts reuse the
  freelist, so it rarely runs — correct, since the goal is a file that stops growing, not one that
  shrinks. Note `freelist_count` does not see ordinary fragmentation: a 0-deletion VACUUM still
  reclaimed 1.6 MB in testing.

Accepted costs, both the user's explicit call: `/api/x/status`'s `judged` tally and
`x_verdict_label_coverage`'s denominator become **15-day rolling** windows (`x_prospective_rows` is
unaffected — it only reads labeled rows, which are exempt, so the channel-admission evidence chain
stays whole); and hidden items are **exempt**, so they accumulate. Only the X rule exists — HN
(~130 stories/day) and `link_previews` (TTL checked on read, rows never deleted) still only grow;
adding one is adding a rule object, not touching the loop. 480 backend tests green; acceptance
against a production snapshot copy (11 result invariants, 3-day window: 7272 rows, 21.4 → 13.2 MB)
in `tmp/2026-08-07-x-cleanup/` — re-runnable, see its README.
⚠️ **At the 15-day default the first weeks legitimately delete nothing** (the oldest production row
is 13 days old), so `deleted=0` in the logs is not a fault — that is exactly why
`GET /api/cleanup/status` exists.

**全文搜索** (2026-08-09, BDD; plan `kb/plans/2026-08-08-full-text-search.md`, schema **v12**).
Search across every source, on its own `/search` page — sidebar entry between Saved and
Filters, `GET /api/search`, `condenser/search.py`. The design work was all in one question,
**how to tokenize Chinese**, and the answer is deliberately dependency-free: see the
`search.py` row above for why `trigram` and the `simple` C++ extension were both rejected and
how CJK character bigrams + phrase queries recover substring semantics. Four decisions worth
not re-deriving:

* **One index row per *item*, keyed like `saved_items`.** The plan said one row per raw
  Telegram message plus query-time de-duplication; indexing the *display unit* instead
  (anchor = the album's lowest id, text = whichever sibling carries the caption) honours the
  same intent — one result per card — and deletes the whole dedup problem, including what it
  would have done to `total` and to paging.
  ⚠️ **The unit is resolved from the database, not from the `DisplayMessage` the hook is
  handed** — the trap that made this land wrong the first time. Backfill yields albums
  already merged, but the **realtime** handler dispatches one raw row at a time (telememo's
  `_handle_new_message` groups a single message), so its `dm.id` is a sibling id. Trusting it
  indexed an album once per photo and made an edit *add* a row beside the stale one instead of
  replacing it, leaving the pre-edit text findable forever. `search.index_telegram_unit` reads
  the unit back and also clears any sibling-keyed document, so a wrongly indexed unit heals on
  its next edit.
* **Search reads the archive, not the reading list.** No subscription scoping: a paused
  channel is findable, and so is a For You tweet the aggregate mode keeps out of the timeline
  (measured in the walkthrough: For You contributes 4 of the 45 hits for 「模型」). The two
  exceptions are `hidden_items` and `is_filtered` — judgements about the *item*, and a
  keyword rule is a standing instruction about the very text a search matches on.
* **Deletion cascades, and one of them is not where the plan put it.** The X sweep's
  anti-join is against `x_feed_items`, not `x_tweets`: a body can outlive its feed rows (a
  live tweet still quotes it) and such a tweet is no longer a timeline item, so a hit on it
  would open onto nothing. `db.delete_channel_messages` drops a channel's documents, and
  `mark_hn_story_dead` drops a killed story's — the timeline's ranking already excludes dead
  stories (`sources/hn.py:_RANKED`), and search must not be the one surface still offering
  them. That policy needs enforcing in **three** places, not one: the deletion, `_rebuild_hn`
  (which would otherwise resurrect every killed story on the next rebuild) and
  `index_hn_story` itself, since Firebase serves already-flagged submissions that are still
  sitting in `topstories`.
* **A keyword filter is checked against the whole display unit, not the anchor row.**
  `is_filtered` is materialized per raw row and an album's caption usually lives on a
  *sibling*, so an anchor-only test let the album through — and the card then rendered the
  very caption the rule bans, answering a query for the banned word itself. Deliberately
  stricter than the timeline, which drops the filtered row and still shows the rest of the
  album: a filter that does not answer a search for its own keyword is not a filter.
* **The rebuild is cheap enough to run inline, and that was measured, not assumed.**
  `tmp/search_rebuild_timing.py` on a production snapshot: 80 ms for 2630 items, ~0.3 s
  extrapolated to production's real row counts. It got there via `executemany` — the naive
  per-row DELETE+INSERT was 774 ms, which would have forced the background thread the plan's
  §4 contemplates.

Web: `SearchView` (local draft + 300 ms debounce; the **URL owns** the committed query and
every filter, so a search is a link), `SearchScopeMenu` (two levels flat, from `GET
/api/sources`), status chips defaulting to **All** — unlike the timeline, you search for
something you remember reading as often as for something you haven't — and a sort toggle
(newest / bm25). Results are `DatedItemRow`s, shared with the Saved view (renamed from
`SavedMessageItem`), and **not** wired to scroll-to-read: scrolling past an old message while
hunting for a different one is not reading it. `lib/itemCaches.ts` is new and load-bearing —
the same card can now be on screen in the timeline, the search results and the saved list at
once, so save/hide/feedback patch all three through one helper instead of three copies of the
timeline-only code. 536 backend + 121 frontend green; **no iOS change** (the API is generic,
its UI is the plan's §8 non-goal). Walkthrough against the real dev database — which was on
schema 11, so the v11 → v12 backfill is part of the acceptance — in
`tmp/2026-08-09-full-text-search/` (re-runnable, see its README).

⚠️ **Typecheck the frontend with `pnpm build` / `tsc -b`, never `tsc --noEmit`.** The bare
form resolves the solution-style root `tsconfig.json`, which lists only project references
and therefore checks *nothing* — it reports success on code that fails the real build. This
shipped three `TS2322`s past a "green" typecheck and past 121 passing vitest runs (esbuild
strips types without checking them), and `git push` to master is a deploy, so the first thing
that would have noticed was the Docker frontend stage.

**Forward is source-generic** (2026-07-27, BDD): `POST /api/forward {key, comment?}` joins
the key-driven family (`/api/read`, `/api/hidden`, `/api/feedback`, `/api/records`);
`TgManager.forward_message` became `forward_item(key, comment)` and non-TG items route
through the new `forward.py` renderer (see its row above). `mode` follows one rule for every
source now — **a comment makes it `quote`, no comment makes it `forward`** — which is exactly
what TG already did, so no client needed a new enum value. The old
`POST /api/messages/{cid}/{mid}/forward` stays as a **thin shell** over the same path
(a test pins the two to identical output): iOS is installed separately from the server, so a
server-first upgrade must not 404 the forward button on a phone nobody has re-installed yet.
UI: the entry moved into the **item detail drawer**, right under the basic-info block and
paired with a new **收藏** button (web `ItemDetailPane`; iOS moved the star out of each
sheet's header into the bottom action row, shared via `ItemActionButtons` / `ItemActionRow`).
Telegram's own two modes are deliberately untouched — a bare t.me link renders as a full
message-quote card with channel, text and media, which beats any hyperlink we could write.
302 backend + 77 frontend + 171 Kit green.

Still open: subscription
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
