"""Runtime configuration loaded from environment variables (spec §5)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Condenser settings.

    Field names map case-insensitively to the env vars in spec §5, e.g.
    ``telegram_api_id`` <- ``TELEGRAM_API_ID``.
    """

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    telegram_api_id: int
    telegram_api_hash: str
    condenser_app_password: str
    condenser_secret_key: str
    condenser_db_path: str = 'condenser.db'
    # Persistent JSON cache: maps forward-source channel/user ids to names so
    # ingest can resolve them without hitting Telegram on every restart.
    condenser_entity_cache_path: str = 'condenser_entity_cache.json'
    condenser_backfill_days: int = 7
    # TTL for the in-memory "my joined channels" (dialogs) cache; iter_dialogs is slow
    # and FloodWait-prone, so we serve repeated browse-dialog opens from cache.
    condenser_dialogs_cache_ttl: int = 300

    # --- hacker news source (condenser/hn.py) ---
    # Master switch for the sampling loop; sampling itself is subscription-driven.
    condenser_hn_enabled: bool = True
    condenser_hn_poll_interval: int = 600
    # How many topstories ids count as "the front page" per sampling round.
    condenser_hn_front_size: int = 30
    # Stories keep getting score/comment snapshot refreshes this long after first sighting.
    condenser_hn_refresh_hours: int = 48
    # hckrnews history window backfilled on subscribe (0 = no backfill).
    condenser_hn_backfill_days: int = 7
    # Max story URLs link-previewed per sampling round (0 = disable prefetching).
    condenser_hn_preview_batch: int = 30

    # --- x (twitter) source (condenser/x.py) ---
    # Master switch: with it off, subscribe/ingest are refused and probe-config is
    # empty, so the local probe idles instead of archiving.
    condenser_x_enabled: bool = True
    # Default per-round fetch counts handed to the probe (per-feed config overrides).
    # For You re-samples on every bird call (no stable window), so this number times
    # the probe's cadence *is* the archive growth rate — the capacity lever.
    condenser_x_home_count: int = 20
    condenser_x_user_count: int = 10
    # Following is a stable window, not a firehose, so this is a *ceiling* rather
    # than a growth rate: measured at ~100-200 tweets/day, i.e. 1-2 per 15-minute
    # round with a morning peak around 7. 50 is ~7x headroom.
    condenser_x_following_count: int = 50
    # A Following entry older than this gets its body archived but no feed row.
    # X pads the timeline with a thread's ancestors (months old, flattened into
    # ordinary entries by bird) and they would otherwise land in timeline history
    # where nobody sees them and the unread badge still counts them. Measured on a
    # 100-entry sample: 12h and 24h discard exactly the same entries, so the line
    # sits in a gap rather than through the middle of the feed.
    condenser_x_following_max_age_hours: int = 24
    # How often the probe re-crawls the followed-accounts list (~15 bird requests
    # for 732 accounts, so daily is plenty — people do not follow in bursts).
    condenser_x_following_sync_hours: int = 24

    # --- rss source (condenser/rss.py) ---
    # Master switch for the polling loop; polling itself is subscription-driven.
    # Ships **false**, unlike every other source: RSS items go straight into the
    # aggregate timeline, and a client that cannot render them yet draws blank rows
    # (the X Phase 2 lesson). Turning it on in production is the last step of the
    # plan's deploy order, after the iOS build with an RSS card is sideloaded.
    condenser_rss_enabled: bool = False
    condenser_rss_poll_minutes: int = 30
    # Conditional requests make most rounds a 304, so the cost of 100 feeds is the
    # round trips rather than the bodies; 5 at a time keeps the burst polite.
    condenser_rss_fetch_concurrency: int = 5
    condenser_rss_timeout: float = 20.0
    # An entry published longer ago than this arrives already read. Importing an
    # OPML file otherwise dumps every feed's whole retained window onto the reader
    # as unread — the archive is still complete, only the backlog is not offered.
    condenser_rss_unread_window_days: int = 7

    # --- embeddings (condenser/embedding.py) ---
    # OpenAI-compatible endpoint; the provider lives entirely in these four vars so
    # switching vendors is an env change, not a code change. With no API key the
    # whole verdict pipeline stays inert (nothing embedded, no verdicts written).
    condenser_embedding_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    condenser_embedding_api_key: str = ''
    condenser_embedding_model: str = 'text-embedding-v4'
    # text-embedding-v4 supports 64..2048. 256 is the capacity decision: For You
    # embeds ~1000 tweets/day, and 1024 dims would cost ~4x the disk on a SQLite
    # file that is bind-mounted as a single volume.
    condenser_embedding_dimensions: int = 256
    # DashScope caps a batch at 10 inputs per request.
    condenser_embedding_batch: int = 10
    # An unlabeled tweet's vector is used once (at judge time) and is re-derivable
    # from x_tweets.text, so it expires. Labeled vectors are the training set and
    # are never pruned. 0 disables pruning.
    # Read by cleanup.XRetentionRule since 2026-08-07, not by the verdict round:
    # it used to prune at the tail of run_once, *inside* the cold-start gate, so
    # an install with too few labels to judge anything never pruned at all.
    condenser_embedding_retention_days: int = 90

    # --- For You verdict (condenser/verdict.py) ---
    condenser_verdict_enabled: bool = True
    # Cold-start gate: below this many labels of either polarity every tweet stays
    # unjudged — and nothing is embedded at all, so a fresh install spends nothing.
    condenser_verdict_min_positive: int = 20
    condenser_verdict_min_negative: int = 20
    # kNN over the labeled set, then the OOD gate: neighbours farther than
    # max_distance (cosine) are not evidence, and fewer than min_neighbors of them
    # means "too far from everything you labeled" -> neutral.
    condenser_verdict_k: int = 15
    condenser_verdict_max_distance: float = 0.6
    condenser_verdict_min_neighbors: int = 3
    # Deliberately asymmetric: a wrong "recommended" costs one glance, a wrong
    # "uninteresting" costs the tweet. Negative also needs a second down neighbour,
    # so one mis-click cannot condemn a whole semantic neighbourhood.
    # Backtested 2026-07-27 on 59 real labels (scripts/x_verdict_backtest.py):
    # positive >= 0.25 was 100% precise over 8 calls, double the coverage of 0.35
    # at the same precision. The negative side, at every setting in the grid, was
    # indistinguishable from guessing (best 55.6% against a 49.2% base rate), so it
    # is **off by default** — 24 of those 29 downs were style judgements (promo /
    # engagement_farming / ai_slop / author), and a topic embedding cannot see
    # style; it only sees the subject the down happened to be attached to. Turning
    # this on is what the design note's extra channels are for.
    condenser_verdict_positive_score: float = 0.25
    condenser_verdict_negative_enabled: bool = False
    condenser_verdict_negative_score: float = -0.55
    condenser_verdict_min_down_neighbors: int = 2
    # --- the ensemble (plan v2 step 4, 2026-07-28) ---
    # Which channels vote: 'a' (author prior), 'b' (topic kNN), 'c' (LLM
    # attributes), 'd' (n-gram).
    # Comma-separated; default is channel B alone, i.e. exactly the pre-ensemble
    # behavior — enabling more channels is a config decision backed by a backtest,
    # never a side effect of deploying this code.
    condenser_verdict_channels: str = 'b'
    # ('a' — the author prior — joined the set 2026-07-29; see below.)
    # Channels that score and archive but never vote (plan v2 step 5b). The revised
    # §9 validates a channel prospectively — on tweets judged before they were
    # labeled — but doing that by *enabling* the channel means badging the reader
    # with an unproven one first (measured: channel C's positive side is 33%
    # precise against a 48.7% base rate). Shadowing makes the measurement free:
    # the score lands in `verdict_meta.channels` and
    # `scripts/x_verdict_prospective.py` replays it at any threshold, while not one
    # badge changes. A channel listed here *and* in the line above votes — voting
    # wins, so a typo cannot mute an admitted channel.
    condenser_verdict_shadow_channels: str = ''
    # Negatives are double-gated: `condenser_verdict_negative_enabled` above is the
    # master kill-switch, and each channel additionally needs its own admission
    # flag (the revised §9's unit of admission). The split is what lets channel D
    # be admitted without quietly resurrecting channel B's negative side, which
    # the 2026-07-27 backtest showed to be indistinguishable from guessing.
    condenser_verdict_b_negative_enabled: bool = False
    # Judging is for tweets you might still read; a backlog from a probe that was
    # offline for a week is stale by the time it lands.
    condenser_verdict_window_hours: int = 48
    condenser_verdict_batch: int = 100

    # --- verdict channel A: author prior (condenser/authors.py) ---
    # The cheapest channel by far — no API call, no table, no index, just a tally
    # over the labels already in the database. It reads the account, never the
    # tweet, so it is the only channel that never abstains on someone you have
    # already judged (measured on the @IBKR ads: B abstained on 6 of 14, D on 4).
    # An author with fewer labels than this is an anecdote about a tweet, not a
    # record: 2 is both the observation floor and the corroboration rule, since a
    # single mis-tap must not condemn an account.
    condenser_verdict_a_min_observations: int = 2
    # Its own vote thresholds, on its own scale (see channels.resolve), from the
    # 2026-07-29 leave-one-out backtest over 104 real labels (base rate 53.8% neg):
    #   neg <= -0.25 -> 92.9% over 14 calls   <- widest, and the most precise
    #   neg <= -0.35 -> 90.9% over 11 calls
    #   neg <= -0.45 ->  100% over  6 calls
    # No saved tweet is condemned at any of them, which no other channel manages
    # (the b,c,d vote condemns five). It still falls one call short of §9's 15, and
    # a backtest is selection-biased by construction, so the admission flag stays
    # off and the channel earns its way in as a shadow — the step-5b protocol.
    # The positive side has only 3 calls behind it: 100%, and far too few to read.
    condenser_verdict_a_positive_score: float = 0.25
    condenser_verdict_a_negative_score: float = -0.25
    condenser_verdict_a_negative_enabled: bool = False

    # --- verdict channel C: LLM attribute extraction (condenser/attributes.py) ---
    # The project's first per-item billed component, so it is fenced three ways: a
    # switch, a hard per-round cap, and a count on /api/x/status. It also needs its
    # **own** API key — deliberately not falling back to the embedding one, so
    # deploying this code cannot start spending on its own; setting the key is the
    # act of turning it on. Same OpenAI-compatible shape as embeddings; a flash-tier
    # model is ~$0.05/$0.4 per 1M tokens, i.e. ~$0.01/day at 400 tweets.
    condenser_attr_enabled: bool = True
    condenser_attr_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    condenser_attr_api_key: str = ''
    # qwen3.7-flash since 2026-07-29 (was qwen-flash). The extractor is the one place
    # where a weak model costs accuracy nothing downstream can recover: the counts can
    # only learn rates for attributes it actually reports. Changing this re-reads the
    # archive rather than migrating it — `model_tag` is `model@taxonomy`.
    condenser_attr_model: str = 'qwen3.7-flash'
    # Hard ceiling on tweets described per round — the spend bound. A first run
    # against a full archive would otherwise be an unbounded bill.
    condenser_attr_batch: int = 40
    condenser_attr_concurrency: int = 4
    # Channel C's OOD gate: an attribute with fewer labeled observations than this
    # does not get to decide anything. The plan's estimate is ~20 per flag before a
    # flag means much, so at today's label count the channel abstains on almost
    # everything — which is the correct answer, not a failure.
    # Briefly 4 on 2026-07-29 and **put back**: lowering it was meant to hold the
    # vocabulary steady after upvotes stopped being credited to every flag in full
    # (fit_flags spreads them now, so a multi-flag tweet contributes less mass and
    # `thread_bait` fell from 6.0 to 5.0 observations for that reason alone). The
    # qwen3.7-flash@v2 re-extraction then made the whole question moot — nothing but
    # `promo_cta` (23.0) clears *any* gate, everything else sits at 1–3 — so 4 bought
    # no measurable difference while loosening the one thing standing between a
    # thinly-observed flag and a verdict. `score_flags` takes the *most negative*
    # flag, so a flag that has only just cleared the gate can decide a tweet on its
    # own; that is exactly how step 3's `thread_bait` (-0.600 off three sightings)
    # outranked `promo_cta` (-0.405 off eighteen). An unmeasurable change to a safety
    # gate belongs at the conservative value. Revisit when a second flag accumulates
    # real observations — and note the units shrank, so 6 now demands *more* real
    # sightings than it did before the credit change.
    condenser_verdict_c_min_observations: int = 6
    # Channel C's own vote thresholds (each channel classifies on its own scale —
    # that is why the combiner is a vote, see channels.resolve). The negative
    # default is the widest backtested point (80.8% over 26 calls, 2026-07-28) —
    # below the §9 bar, which is why the admission flag defaults off. The positive
    # threshold is out of the channel's observed range (~[-0.4, +0.1]) on purpose:
    # its positive side has shown nothing yet.
    condenser_verdict_c_positive_score: float = 0.25
    condenser_verdict_c_negative_score: float = -0.25
    condenser_verdict_c_negative_enabled: bool = False

    # --- verdict channel D: n-gram bayes (condenser/ngram.py) ---
    # Not wired into the running verdict yet (plan v2 step 1 ships the channel and
    # its backtest; step 4 ships the combiner that lets it vote). The knobs live
    # here so the backtest grids the same constants production would read.
    # A token must appear in this many labeled tweets before it counts as evidence —
    # the small-corpus equivalent of the kNN's OOD gate.
    condenser_verdict_d_min_df: int = 2
    # A word both sides use is not evidence: below this many nats of log-odds it
    # does not vote at all. Without the floor, enough near-neutral words assemble a
    # confident verdict out of noise.
    condenser_verdict_d_min_weight: float = 0.5
    # Fewer recognizable tokens than this and the channel abstains outright.
    condenser_verdict_d_min_hits: int = 3
    # Only the most discriminative tokens vote, so filler cannot outvote one clear
    # marketing phrase.
    condenser_verdict_d_top_tokens: int = 8
    # Divisor before tanh, applied to the corpus-centered *mean* of those tokens'
    # log-odds — i.e. how one-sided the evidence has to be to count as a made-up
    # mind, in nats. At 1.0 a tweet whose words are e times likelier under one side
    # than the other scores ±0.76. Moving it is the same experiment as moving the
    # verdict thresholds, so the backtest sweeps those instead.
    condenser_verdict_d_scale: float = 1.0
    # Channel D's own vote thresholds. The negative default is the operating point
    # the step-1 backtest starred (86.7% over 15 calls at -0.45) — kept off until
    # the §9 admission is actually decided, because that figure was picked out of
    # 88 operating points scored on the same 59 labels.
    condenser_verdict_d_positive_score: float = 0.25
    condenser_verdict_d_negative_score: float = -0.45
    condenser_verdict_d_negative_enabled: bool = False

    # --- daily cleanup (condenser/cleanup.py) ---
    # Master switch for the loop itself: off means the task is never spawned, not
    # that each round no-ops.
    condenser_cleanup_enabled: bool = True
    # How often the loop wakes to *check* the breakpoint below. Short relative to
    # a day on purpose: `git push` to master is a deploy here, so the process
    # restarts often, and this bounds how late a round can land after one.
    condenser_cleanup_check_interval: int = 3600
    # The actual cadence, enforced by app_meta's `cleanup_last_run_at` rather
    # than by any in-memory timer — which is the whole point, since a timer
    # resets on every restart and a daily one might never fire.
    condenser_cleanup_interval_hours: int = 24
    # VACUUM hands freed pages back to the OS but takes an exclusive lock, and
    # production runs auto_vacuum=0 so there is no incremental alternative. Only
    # worth the lock once a round has actually freed a meaningful slice of the
    # file; in steady state the next day's inserts reuse the freelist instead, so
    # this rarely fires — which is correct. The file stops growing either way.
    condenser_cleanup_vacuum_threshold: float = 0.20

    # --- cleanup rule: x retention (condenser/cleanup.py: XRetentionRule) ---
    # Each rule owns its own switch, independent of the loop's master one and of
    # condenser_x_enabled — ingest and retention are separate decisions.
    condenser_cleanup_x_enabled: bool = True
    # How long an X row nobody engaged with is kept, by x_feed_items.first_seen_at
    # (how long it sat in the backlog) rather than by the timeline's sort key —
    # a followed account's backfill can hand us months-old tweets, and deleting
    # those the next morning is not what "15 days" means. Read, hidden, labeled
    # and saved tweets are exempt and kept indefinitely, as TG and HN archives are.
    condenser_cleanup_x_retention_days: int = 15

    # --- link preview fetching (condenser/preview.py) ---
    # Total per-request timeout (seconds) for fetching a URL/its image.
    condenser_preview_fetch_timeout: float = 8.0
    # TTL (seconds) for successful previews; negatives (failed fetches) expire sooner.
    condenser_preview_cache_ttl: int = 7 * 24 * 3600
    condenser_preview_neg_cache_ttl: int = 3600
    # Hard caps on downloaded bytes (HTML page vs. proxied image).
    condenser_preview_max_bytes: int = 2_000_000
    condenser_preview_image_max_bytes: int = 5_000_000
    # Max URLs previewed per message + max concurrent outbound fetches.
    condenser_preview_max_urls: int = 8
    condenser_preview_max_concurrency: int = 5
    condenser_preview_max_redirects: int = 5
    # When True, preview thumbnails stream through the backend (private, hotlink-proof).
    # When False, the image endpoint redirects the browser to the origin URL instead
    # (simpler fallback — loads images directly, as a non-proxied setup would).
    condenser_preview_image_proxy: bool = True
    condenser_preview_user_agent: str = (
        'Mozilla/5.0 (compatible; CondenserBot/0.1; +https://github.com/reorx/condenser)'
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton (validated from the environment)."""
    return Settings()
