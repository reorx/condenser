---
created: 2026-08-21
tags:
  - status
  - history
  - changelog
---

# Status / known gaps

> A dated, append-only work log: every feature landing since 2026-06, with its
> measurements, test counts, deploy state and the traps found along the way — the
> project's memory of *why* things are the way they are. **Chronological, oldest first:
> read from the tail to catch up on the current state.** Entries were written while this
> lived inside AGENTS.md, so "see the X section/row above" refers to AGENTS.md's module
> table or the other `kb/docs/` splits (`ios.md`, `probe.md`, `database.md`,
> `x-verdict.md`).

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
ssh 进生产主机（地址/端口/用户见 deploy workspace 的 ansible inventory，不入公开库）
→ `docker inspect ghcr.io/reorx/condenser:latest --format
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

**X For You 语言过滤** (2026-08-10, BDD; started from a production `lang: ar` tweet — X's
algorithm recommends foreign-language content by design, no bug involved). Three repos, one
field: **xbird 1.1.0** adds `TweetData.lang` (`legacy.lang`, which upstream bird discards) as
an additive extension — the key is omitted when absent, so the wire shape for old payloads is
byte-identical and the golden suite passed with zero changes; measured on a real home
timeline, 40/40 entries carry it. The **probe changes no code** — `uv lock --upgrade-package
xbird` + a launchd kickstart. Condenser drops a For You entry whose primary subtag is outside
the whitelist at **ingest, whole** (`x._apply_language_filter` — see the `x.py` row; no
schema change, no DB column). Two-layer configuration, deliberately decoupled: the language
list is the **global** `app_meta.languages` (generic key, no `x_` prefix — a reader
preference other sources can reuse; `db.get_languages()`, validated `^[a-z]{2,3}$` in
`PATCH /api/app/meta`, picked in Settings → 语言), while X carries only the **switch** —
For You's `config.lang_filter`, via the existing config-merge PATCH (web:
`XLangFilterToggle` beside `XAggregateMenu`; on-but-no-languages shows 「先在设置中选择语言」
because that state filters nothing). Fail-open is the contract: an un-upgraded probe (no
`lang`) disarms the filter rather than emptying the timeline, and `NON_LANGUAGE_CODES`
(`und`/`zxx`/…) always pass — 2 of 40 real entries are `zxx` (media-only tweets).
`filtered_lang` joins `filtered_ads`/`filtered_old` in `IngestResult` → push stats →
`/api/x/status` → the subscription row (「N 条外语已滤除」). Config changes act on *future*
pushes only (SeenCache re-pushes nothing; accepted). 551 backend + 128 frontend green
(`tests/test_x_lang_filter.py`, 15 scenarios); live e2e + walkthrough in
`tmp/2026-08-09-x-lang-filter/`. Same session, unrelated fix: `tests/test_x_verdict.py`'s
hardcoded `NOW = datetime(2026, 7, 25)` aged past the 15-day cleanup retention window on
2026-08-09 and two tests started failing (the lifespan's cleanup sweep deletes unlabeled
feed rows); `NOW` is now relative to the wall clock.

**X 推文短链展开** (2026-08-10, BDD; plan `kb/plans/2026-08-10-x-expanded-urls-xbird.md`,
schema **v13**, xbird **1.2.0**). X rewrites every link in a tweet body to t.co; the
original lives only in `entities.urls`, which xbird now carries (`TweetData.urls`, the
`lang` precedent: key omitted when absent, golden suite green with zero changes — probe
upgrade was `uv lock --upgrade-package xbird` + kickstart, no code). condenser normalizes
to snake_case at the parse boundary (`x.parse_urls` — wire is camelCase, everything
downstream is snake_case, convert once), stores per tweet row (refresh path, like
metrics), and the envelope + nested quote carry it to both clients. Rendering rules,
identical on web (`lib/xUrls.ts` + `linkify`) and iOS (Kit `XUrlEntity` + `bodyText` +
app `Linkify`): **match by exact t.co string, never by `indices`** (offsets into X's raw
text — they misalign once the RT prefix or an article title is stripped); anchor text =
`display_url`, href = `expanded_url`; an unmatched t.co renders verbatim (old rows,
un-upgraded probe — per-entry degradation). A **trailing t.co beside media is hidden**
(X's own UI behavior), with `urls` missing treated as an **empty set**, not "don't
touch" — caught in the live walkthrough: a media tweet with no outbound links has no
entities at all, and gating the strip on their presence left exactly the self-link the
rule exists to hide. `xPreviewUrls` previews the expanded original (better metadata, no
redirect) and recognizes the quote's own permalink by the quoted status id. Search
documents append `expanded_url` + `display_url` (a card renders them, so the reader will
search them) — `TOKENIZER_VERSION` 3, index rebuilt on next start. Acceptance pinned to
real xbird output (`tests/fixtures/x/urls_tweets.json` via `tmp/make_x_urls_fixture.py`;
the old fixtures stay as the no-urls degradation sample). 563 backend + 141 frontend +
197 Kit green; E2E on a real v12 DB copy (migration + rebuild + real home-20 ingest +
browser screenshots) in `tmp/2026-08-10-x-expanded-urls/`. **Deployed 2026-08-10**
(revision `f00b7c4`, schema 13 on the box, verified over ssh); `tmp/backfill_x_urls.py`
filled the 8 window rows and re-indexed them. Walkthrough gotcha worth keeping: the PWA
service worker serves the pre-rebuild bundle — unregister it before verifying frontend
changes in a browser session.

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

**HN 条目准入下限** (2026-08-14, BDD; plan `kb/plans/2026-08-14-hn-story-admission.md` 阶段
1+2, no schema change). 6- and 7-point stories were reaching the timeline, and the cause is
that "each day's top 10" is a **relative** bar that does not exist yet at the start of a day:
with nine rows in the partition, top-10 is everything — and UTC midnight is 08:00 Beijing, so
the bar hits zero exactly when the reader opens the app. A mature day cuts at **243-476**
points. Two floors now AND onto the rank in `sources/hn._admission_where`, which all four
read queries share (page / `/timeline/new` / `days()` / `unread_count()`) — a floor applied to
the page alone leaves the badge promising a backlog no view can produce.

* **`min_score`, default 50** — chosen to sit far below any formed day's real cut, so it is
  never binding there and only guards the unformed window. Verified on a production snapshot:
  4 stories dropped, all on the day that had not formed, **31 formed days byte-identical**.
* **`max_peak_rank`, default 0 (off)** — the code and the menu option ship, the default does
  not, and that is a measurement. On the same 32 days the gate at 20 had **zero true
  positives and three false ones**: 1235-, 708- and 703-point stories sitting at #2, #8 and
  #2 of their day. `peak_rank` is the best rank we *sampled*, not the best rank the story
  *reached* — sampling is 10-minutely and every `git push` restarts the container, so a story
  whose peak lands in a gap is recorded on its way down (all three were first seen 1.5-24h
  after submission). And the case the gate was built for, a second-chance-pool repost, is by
  construction *also* a story we meet late — so no "did we watch it early" test separates the
  two. Score does, and that is the other floor's job. ⚠️ Re-run
  `tmp/2026-08-14-hn-admission/admission_diff.py` against a fresh snapshot before ever
  turning it back on; do not go by the plan's original "1% cost" table, which counted rows
  without looking at which rows.

Both live in the front feed's subscription config, so `PATCH /api/sources/hn/subscriptions/front`
now **merges** rather than replacing (three knobs, one column). An absent key reads as its
default, which is what arms the score floor on production's pre-floors row. Web:
`HnDisplayModeMenu` → `HnFeedRulesMenu` (one trigger, three groups). **No iOS change** — the
rules are server-side and the envelope is unchanged. 579 backend + 148 frontend green
(`tests/test_hn_admission.py`, 16 scenarios); snapshot diff, the peak_rank post-mortem and a
browser walkthrough in `tmp/2026-08-14-hn-admission/` (read its `README.md` — re-runnable).

**HN 准入戳 —— 阶段 3** (2026-08-14, BDD, same plan §5/§9, schema **v14**). The floors above
patched one window; this moves the whole decision off the read path. `sources/hn.qualify` runs
at the tail of every sampling round, stamps what it admits, and the four read queries collapse
to `qualified_at IS NOT NULL ORDER BY qualified_at DESC` (see the v14 block in Architecture for
the stamp itself and the two migration-ordering traps). What changed conceptually:

* **The day quota became a rate.** `budget(t) = ceil(N × elapsed/24)`, spent cumulatively — the
  plan's direction C, which only becomes *exact* rather than approximate under one-way
  admission, which is why it was never shipped as a query-side stage. `all` has no ceiling;
  `half` takes its rate from the median of the last 7 days' archive volume.
* **`display_mode` therefore means something different**: a prospective rate, not a
  retrospective view filter. Widening admits more from here on; narrowing does **not** recall
  what a day already gave you. Web copy says so ("Let in per day" / "Stories already on the
  timeline stay").
* **A/B did not go away** — they are the judge's candidate conditions now, alongside the
  candidate window (`first_seen_at >= now - refresh_hours`; one constant for two windows,
  because past it scores stop moving and a story can no longer *earn* its way in).

Three decisions the plan did not cover, all forced by it:

* **The hckrnews import stamps history, not `now`.** Imported days are ≥2 days old, i.e.
  outside the judge's window by construction — without `stamp_history(day)` at the end of
  `_backfill_day` a new subscriber's whole backfilled week would be invisible. It tops a day
  up to `N - already stamped` rather than doubling it, which every new subscriber hits on
  their third day (subscribe day 0 → day 0's hckrnews archive arrives on day 2, by which time
  day 0 already has live-admitted stories).
* **Bulk read burns only what was admitted.** The old sweep took the whole archive, on the
  logic that a below-cut story was invisible anyway; one-way admission inverts that — an
  unadmitted story is not below a cut, it is *not here yet*, and pre-burning it lands a fresh
  arrival at the head of the timeline already grey. X's `bulk_read_scope` rule: burn what the
  view showed.
* **`is_dead` stays on the read path** and is not an exception to one-way admission: it says
  HN removed the submission, not that we changed our mind. `mark_hn_story_dead` drops the
  search document too, and the two surfaces must offer the same set.

Deploy-day note: the backfill stamps today's already-visible stories and they count against
today's budget, so nothing new is admitted until the line catches up (measured on the snapshot:
budget 2 vs 6 spent at 04:16 UTC, resuming ~16:16). That is correct — the day's quota was
already spent — and self-healing. Known cosmetic cost: stories stamped in the same round share
a `qualified_at` and tie-break on id (`pack_pos`'s contract, plan §5.4i), so a burst shows its
slot numbers out of order. 595 backend + 150 frontend green (`tests/test_hn_admission.py`, 30
scenarios; `test_hn.py` covers the round wiring). **No iOS change** — `datetime` and `day_rank`
keep their names and types. Acceptance (migration equivalence on a production snapshot, a live
round, browser walkthrough) in `tmp/2026-08-14-hn-admission/README.md`.

**RSS 源 —— 阶段 1+2** (2026-08-20, BDD; plan
`kb/plans/2026-08-20-rss-source-opml-llm-summary.md`, schema **v15**). The fourth source, and
the one that needed the least invention: see the `rss.py` / `sources/rss.py` rows above for
the ingest and the read path, and the v15 block for the two tables. Phase 1 shipped the
archive (manager, feedparser, OPML, subscription API, status); phase 2 made it readable —
provider + registration, the `rss:{id}` key's whole inherited surface (read / save / hide /
records / forward / bulk-read), search, the retention rule, and the web UI (`RssCard`,
`RssSection` with a real OPML file picker, sidebar feed rows, `/s/rss/:feed`).

⚠️ **`CONDENSER_RSS_ENABLED` ships `false`, and that is the deploy order, not caution.**
RSS items go straight into the aggregate timeline, so an installed iOS build that cannot
render them draws **blank rows** (the X Phase 2 lesson) — and `git push` to master is a
deploy. Every server-side stage is therefore safe to push while the switch is off; turning it
on in production is the *last* step, after phase 4 sideloads an iOS build with an RSS card.

Four things worth not re-deriving, all measured rather than assumed:

* **The unread window is the feature, and it looks alarming until you know that.** Eight real
  blogs imported at once: 280 entries archived, **3 unread**. Everything published more than
  7 days ago arrives already read, because importing an OPML file otherwise dumps every feed's
  whole retained window into the inbox. The archive is complete; only the backlog is not
  offered. It also sizes Phase 3: what needs summarizing is "unread inside the window", not
  the archive.
* **The sort timestamp is a read-side clamp, and the answer travels in the envelope.** A feed's
  `published_at` is missing often and in the future occasionally; `first_seen_at` is "all of
  them, now" after an import. Neither works alone, the clamp lives in SQL, and a saved snapshot
  replays without that SQL — so `sort_at` is carried rather than recomputed, and the rule
  exists in one language.
* **304 is the most common healthy outcome and httpx raises on it.** `raise_for_status`
  classifies 304 as a redirect, so an unhandled one records every quiet feed as a failure. Only
  the live run could find it (the tests inject `fetch_feed`), which generalizes: **an injectable
  I/O boundary needs a second test path through the real implementation** — here an
  `httpx.MockTransport` regression test.
* **A test module with a clock in the past must switch the retention rule off.** The cleanup
  round fires at startup on any app whose `app_meta` has no `cleanup_last_run_at` — i.e. every
  test — and deleted `tests/test_rss_timeline.py`'s fixture out from under it on the first run.
  Same trap `test_x_verdict` hit on 2026-08-09.

649 backend + 169 frontend green (`tests/test_rss.py` 33, `tests/test_rss_timeline.py` 21,
`RssCard.test.tsx` 10). **No iOS change yet** — that is phase 4, and it is what gates the
production switch. Acceptance: `tmp/2026-08-20-rss-phase1/` (real feeds end-to-end) and
`tmp/2026-08-20-rss-phase2/` (browser walkthrough over 8 real feeds + the 204-feed OPML parsed
offline); both re-runnable, see their READMEs. Remaining: **phase 3** (the LLM summary pipeline,
`condenser/summary.py`, fenced the way `attributes.py` is — its own API key, so deploying the
code cannot start spending) and **phase 4** (iOS + flipping the switch).

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

