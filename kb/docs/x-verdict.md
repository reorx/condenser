---
created: 2026-08-21
tags:
  - x
  - verdict
  - ml
  - embeddings
  - channels
---

# X For You verdict — channels, pipeline, evaluation

The verdict judges each For You tweet as `recommended` / `not for you` / neutral before
the reader sees it, trained live on the reader's own labels (`item_feedback` ∪
`saved_items`). It began as a single kNN-over-embeddings judge (Phase 4 of the X plan)
and grew into a **four-channel voting ensemble** under the v2 plan
(`kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md`). This doc covers the
pipeline (`verdict.py`), the four channels (A–D), their shared vocabulary
(`channels.py`), and the two evaluation tools.

## Pipeline (`verdict.py`)

**For You verdict** on `app.state.verdict`, kicked by ingest — For You only changes when
the probe pushes. `run_once` = drop-retracted → cold-start gate → index-missing → judge.
(Vector expiry moved to `cleanup.py` on 2026-08-07 — it used to run here, but *inside*
the cold-start gate, so a fresh install never pruned. Attribute extraction slots before
judging when channel C votes, after it otherwise: a tweet is judged exactly once, so an
attribute arriving later would never vote; without C scoring, a slow provider must not
delay verdicts.)

**Since step 4 (2026-07-28) judging is the ensemble.** `enabled_channels`
(`CONDENSER_VERDICT_CHANNELS`, default `b` = byte-identical single-channel behavior,
algo `knn-v1`; more channels → `vote-v1`) — plus, since step 5b, `shadow_channels`
(`CONDENSER_VERDICT_SHADOW_CHANNELS`, default empty): channels that score and archive
but **cast no vote**, so an unproven channel can be measured on real traffic without
badging anyone (verified end-to-end: same window judged with and without shadows, 100
verdicts, zero changed). A channel listed in both votes — a typo must not mute an
admitted channel. Shadow entries carry `{"verdict": null, "shadow": true}`, because an
*abstaining* channel is absent from the block entirely and the two states must stay
distinguishable. `algo` still names how the **verdict** was made, so `channels=b` +
shadows is still `knn-v1`.

Each round: every enabled/shadow channel scores (A = `authors.score` off a per-round
tally of labeled handles, B = kNN `topic_score`, C = `attributes.score_flags` off the
tweet's stored attributes, D = `ngram.score` off a per-round refit; the configurable set
is the single `CHANNEL_KEYS` tuple, so a channel reachable from `channel_policy` but
missing there cannot exist) → each classifies under its own `ChannelPolicy` (per-channel
thresholds; negatives **double-gated** by the master `negative_enabled` AND the
channel's own `*_negative_enabled` admission flag, so admitting D can never resurrect
B's dead negative side) → `channels.resolve` votes.

`verdict_meta` stays additive: the top level keeps B's `score`/`neighbors` exactly as
shipped iOS builds decode them, and a `channels` block (vote + score + A's
handle/up/down + C's flags + D's tokens; no second copy of B's neighbours) rides beside
them. It archives the nearest `META_NEIGHBOURS` (5) with author handles — capped because
it is written ~1000×/day.

Two gates own the behavior: the **cold-start gate** sits *before* any embedding call (no
labels, no spend), and the **OOD gate** drops neighbours past `max_distance` — without
it kNN always returns k neighbours and every tweet gets scored off whatever was nearest.
Scoring is a distance-weighted vote (`save` ×2 weight, not ±2 value, so the score stays
in [−1,+1]); `negative` additionally needs ≥2 down neighbours, because a wrong "not for
you" costs the tweet while a wrong "recommended" costs a glance.

The training set is **read live** from `item_feedback` ∪ `saved_items` (unsaving
retracts a sample with no sync code; saved-and-downvoted is contradictory and is dropped
from both sides). The KNN index is **reconciled**, not written through — a restart, an
outage or a model change self-heals next round. Already-labeled tweets are excluded from
judging (they are in the index and would match themselves at distance 0).
`rebuild_labeled_index()` is the escape hatch for a suspect index.

## Vector infrastructure

### `vectors.py`

The **only** module that knows sqlite-vec exists: `setup(dims)` (load the extension onto
the peewee *database* so every thread-local connection replays it, then ensure the
`vec0` table), `pack`/`unpack` (float32 BLOB, deliberately extension-independent so
vectors are storable even where the extension will not load),
`upsert`/`delete`/`clear`/`labeled_ids`/`knn`. Everything degrades to no-op when the
extension is unavailable — an unsupported host loses only the verdict.

### `embedding.py`

OpenAI-compatible embeddings (`CONDENSER_EMBEDDING_*`, default DashScope
`text-embedding-v4@256`): batches of ≤10, two retries, L2-normalize, reorder by the
echoed `index`. `available(settings)` is false without an API key → the whole verdict
pipeline stays inert. `model_tag` = `name@dims`, the identity a stored vector is
comparable within (a model/dimension change re-embeds rather than migrates).

## The channels

### A — author prior (`authors.py`, 2026-07-29)

The cheapest channel by far: no API call, no table, no index — a Beta-smoothed tally
over labels already in the database. It **reads no text**, which is both its strength
and its limit: it never abstains on an account you have judged, and it is blind to one
you have not. Built after the @IBKR measurement showed every *text* channel has a hole
exactly where an ad account lives: B goes out-of-domain each time the account rotates
subject, C is blind until the extractor runs, D needs token overlap.

`fit` tallies handles (normalized: `@IBKR`/`ibkr` are one account; `save` ×2 like
everywhere); `score` shrinks each rate by evidence mass and abstains below
`condenser_verdict_a_min_observations`. Deliberately smoothed rather than the hard rule
it replaces (`>=2 downs and no positives`): that rule acquits an account outright on its
first upvote and convicts on its second down, and the cliff is what produced its one
wrong call.

Unlike C it routes **no chips** — by the time an account has been downed repeatedly the
chips usually name several different attributes, and the pattern they share is "you keep
saying no to this person"; filtering on `author` chips alone would discard 55 of the 56
downs that built the signal. Its evidence is a sentence rather than a metric, which
makes it the most readable trail in the pane.

### B — embedding kNN

The original single-channel judge: kNN over `x_vec_labeled` (see the pipeline section
for the OOD gate, distance-weighted vote, and the ≥2-down-neighbours rule for
negatives). Answers "what is it about".

### C — LLM attributes (`attributes.py`)

Extraction (step 2) and scoring (step 3) in one module, the way `ngram.py` holds
channel D.

**Extraction**: an LLM reads each tweet and reports *what it is about* (open English
slugs) and *how it talks* (`STYLE_FLAGS`, a **closed** taxonomy grown from the reader's
own down-reason chips, split finer where a chip lumps patterns together). Since
2026-07-29 each flag's **definition ships with its name** (`FLAG_GUIDE` → the prompt).
Until then only bare tokens were sent and it measured badly: `ai_slop` reached the model
as a naked word, it read that as machine-written spam, and 0 of the reader's 3 `ai_slop`
chips landed on a tweet it had so flagged. A closed taxonomy is only closed if its
meanings travel with it; a test pins that every flag is defined in the prompt. A
**feature extractor, not a judge** — the scoring stays in code that can be explained and
improves with every label. `model_tag` = `model@TAXONOMY_VERSION`, the identity an
attribute is comparable within (edit the taxonomy → old rows are re-read, never
migrated — the `embedding.model_tag` contract).

The project's **first per-item billed component**, so it is fenced four ways:
`condenser_attr_enabled`, a hard per-round `condenser_attr_batch`, a count on
`/api/x/status`, and — deliberately — **its own API key with no fallback to the
embedding one**, so deploying the code cannot start spending; setting
`CONDENSER_ATTR_API_KEY` *is* the act of turning it on. One request per tweet, never a
batched prompt: batching saves a little overhead and buys silent misalignment (four
answers for five posts, everything after the gap attached to the wrong tweet).

**Scoring**: `fit_flags` counts each flag's ups and downs under one rule — **credit
follows attribution**. `REASON_FLAGS` routes a down's chip to the flags it accuses; a
chip that matches nothing falls back to a bag-level share, while `topic`/`author` charge
nobody because the reader said the style was not the problem. A label that attributes
nothing is spread across the flags it might have meant — **including every upvote**
(2026-07-29): an up carries no chip and never can, so crediting each flag on a liked
tweet in full (as it did until then) let any flag the chips rarely accuse gain evidence
it never lost, one-directionally. `score_flags` lets the most negative flag carry the
tweet — one unmistakable marketing line makes a post marketing, and averaging dilutes
exactly what the channel is for. Each rate is shrunk by its evidence mass so a
thrice-seen flag cannot outshout an eighteen-times-seen one.

### D — n-gram naive Bayes (`ngram.py`)

Naive Bayes over the words of the tweets you labeled (v2 plan step 1). Answers "how does
this talk" where the embedding answers "what is it about" — which is what 24 of the
first 29 downs were complaining about. Costs no API call and no table (counts are refit
from `x_tweets.text` per round), and it can **name its evidence** in words.

Tokenizer: lowercase, drop URLs + @mentions (author identity is channel A's job), keep
hashtag words, latin unigrams + bigrams (bigrams built *before* stopword removal, so
`save this` survives while `this` does not), CJK character bigrams (no jieba — the same
dependency thrift that picked sqlite-vec), emoji as tokens (`🧵`/`🔖` are load-bearing).

Three decisions came out of the first real backtest and are pinned by a test: only
tokens above `min_weight` vote; their weights are **averaged not summed** (a sum scores
length — downs run 30.8 informative tokens against ups' 15.3, so every long tweet
saturated at −1); and the result is shifted by `model.offset`, the corpus's own neutral
point, measured **leave-one-out** at fit time. The offset applies to the finished score
only: subtracting it per-token reorders the evidence and measured *below* the base rate.

**Not wired into the running verdict** (step 4) — shadow/backtest only so far.

### Shared vocabulary (`channels.py`)

`ChannelScore` (score in [−1,+1], `confidence` = *how much evidence*, `corroborated` =
may this carry a negative verdict, `meta`), the verdict constants, and the two
combiners.

**`resolve` is the production combiner** (step 4, 2026-07-28): each channel classifies
on its *own* thresholds and the votes merge by rule — any negative with no positive →
negative, any positive with no negative → positive, conflict → neutral. A vote, not a
mean, for two measured/structural reasons: the channels' scales are incomparable (C
spans ~[−0.4,+0.1] vs B/D's [−1,+1], so a mean diluted the sharp channel), and the
revised §9 admits/monitors/kills *one channel's negative side* at a time, which requires
the verdict to be attributable to the channel that cast it. `combine` (weighted mean)
stays as the backtest's rejected-baseline comparison. The vote is rank-free, so channel
A joined without touching this module at all. **Abstaining is `None`, never 0.0** —
folding silence in as a zero vote lets a channel that never fires drag the ones that do
toward neutral.

## Evaluation

### Offline — `scripts/x_verdict_backtest.py`

Leave-one-out backtest on your real labels — the tool that turns constants into
decisions and, since the v2 plan, **picks the channels**. Read-only on the DB (it does
trash the KNN index per fold and rebuilds it at the end). `--channels a,b,d` reports
each channel and their combination **on the same folds**; `--sweep` grids each channel's
own settings; `--negatives topic` drops style downs from training (the variant §7 of the
plan asks for); `--embed-missing` is the only mode that calls an API.

How to read it: **abstain/coverage first** (a judge that always shrugs is 100% precise
and useless), then the **base rate** printed beside every table (the 2026-07-27 negative
failure was 55.6% against 49.2% — without the comparison it reads as usable), then
negative precision, then positive. The closing summary ranks operating points with ≥5
calls and stars any negative one clearing the plan's §9 bar. Channels wrap the
*production* scoring code, never a copy — and evidence is captured once per fold and
re-scored per grid cell, so a sweep costs one pass of the expensive part.

### Online — `prospective.py` + `scripts/x_verdict_prospective.py`

Precision measured only on tweets the judge committed to *before* the reader said
anything (v2 plan step 5). Needs no `verdict_at` column and no timestamp comparison:
`db.x_pending_verdict_rows` never judges an already-labeled tweet, so a For You row
holding both a verdict and a label was judged first by construction — which is what
makes these pairs free of the backtest's selection bias (it picks an operating point and
scores it on the same labels).

`summarize` reports the as-shipped badges plus **per-channel attribution** (a channel's
own claim even where the vote resolved against it — §9 kills one channel's negative
side, so a wrong negative must name its author). `shadow` replays the *archived* scores
at thresholds nobody ran: because the score is stored even when a channel's negative
side is off, a channel's admission case can be built from production data **before** it
is admitted.

Two limits stated in the output rather than hidden: a badge may bias whether a tweet
gets read/labeled at all, and channel B's `corroborated` is not fully archived (it
counted every close neighbour; only the nearest five are stored), so B's shadow
negatives are an upper bound — channel A is the exception, since its rule *is* the down
count in its own evidence and therefore replays exactly.

The script is fully read-only — unlike the backtest it never touches the KNN index, so
it is safe to point at a live copy. It prints coverage first (a channel is not validated
just because it has been running), then the verdict×label matrix, then as-shipped
precision per side and per channel, then the shadow replay (`--sweep` for a threshold
grid), and ends with every wrong call printed in full — at these sample sizes the
individual tweets *are* the evidence.
