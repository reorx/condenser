"""For You verdicts from your own feedback (plan Phase 4).

The reader labels tweets 👍/👎 and saves the good ones (Phase 3); this module
turns those labels into a judgement on tweets you have *not* seen yet: embed the
tweet, find the nearest labeled tweets, and let them vote.

Everything here is built so that **the default answer is neutral**. Two gates
enforce that, and they matter more than the classifier does:

* the **cold-start gate** — below a floor of labels on each side there is nothing
  to generalize from, so no verdict is written and, deliberately, nothing is even
  embedded: a fresh install must not spend money to produce shrugs;
* the **OOD gate** — kNN always returns k neighbours, however far away they are.
  Without a distance ceiling every tweet gets scored off whatever happened to be
  nearest, which is how a classifier ends up confidently wrong. Neighbours beyond
  ``max_distance`` are not evidence, and too few of them means neutral.

Scoring is asymmetric on purpose: a wrong "recommended" costs a glance, a wrong
"uninteresting" costs the tweet. So `negative` needs both a stronger score and
corroboration from a second downvoted neighbour.

Phase 4 only *labels*. Nothing is hidden, re-ranked or marked read by a verdict —
that comes after the badge has earned trust, and the ``verdict_meta`` evidence
trail is what lets you check whether it has.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from . import attributes, authors, db, embedding, ngram, vectors
from .channels import NEGATIVE, NEUTRAL, POSITIVE, ChannelScore, resolve
from .config import Settings, get_settings

log = logging.getLogger('condenser.verdict')

# Bumped when the scoring changes, so a stored verdict says which rules produced
# it. Single-channel rounds keep the historical tag — their scoring is unchanged —
# while a multi-channel round is a different algorithm and says so.
ALGO_VERSION = 'knn-v1'
ENSEMBLE_ALGO_VERSION = 'vote-v1'

# Sample weights per label kind. A save is a higher-grade positive than a thumb —
# it costs the reader an intent, not a reflex. The weight lives here rather than in
# the label value so the score stays inside [-1, +1] and remains comparable across
# algorithm versions.
LABEL_VALUE = {'up': 1.0, 'save': 1.0, 'down': -1.0}
LABEL_WEIGHT = {'up': 1.0, 'save': 2.0, 'down': 1.0}

LAST_RUN_META_KEY = 'x_verdict_last_run_at'

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]
Extractor = Callable[[list[str]], Awaitable[list[Optional[dict]]]]


@dataclass
class RunResult:
    """What one round did — returned for tests and logged for the status line."""

    indexed: int = 0  # training vectors added to the KNN index
    dropped: int = 0  # training vectors removed (label undone / unsaved)
    judged: int = 0  # feed rows given a verdict
    attributed: int = 0  # tweets described by the attribute extractor (channel C's fuel)
    pruned: int = 0  # expired unlabeled vectors deleted
    skipped_reason: Optional[str] = None  # 'disabled' | 'unavailable' | 'cold_start'


# How many neighbours the stored evidence keeps. Scoring uses every close
# neighbour; only the archived explanation is capped, because it is written once
# per judged tweet (~1000/day on For You) and an unbounded list would grow the
# database faster than the tweets it explains.
META_NEIGHBOURS = 5


@dataclass
class Neighbour:
    tweet_id: int
    distance: float
    label: str
    handle: Optional[str] = None

    @property
    def similarity(self) -> float:
        return 1.0 - self.distance

    def as_meta(self) -> dict:
        # snowflake ids cross the API as strings (int64 > JS's safe integer range)
        meta = {'tweet_id': str(self.tweet_id), 'distance': round(self.distance, 4), 'label': self.label}
        if self.handle:
            # the author is what makes the evidence readable ("like that post of
            # @x's you marked down") at ~15 bytes — the best value per byte here
            meta['handle'] = self.handle
        return meta


@dataclass
class Judgement:
    verdict: str
    meta: dict = field(default_factory=dict)


# --- what text gets judged ----------------------------------------------------


def judge_text(row: dict) -> Optional[str]:
    """The text that represents this tweet, or None when there is nothing to read.

    Three upstream quirks are absorbed here, all of them from bird's flattening:
    a retweet arrives only as an ``RT @orig:`` prefix on the original's text; a
    quote tweet's meaning lives in both halves ("look at this" + the thing); and
    an X long-form post sets ``text`` to its own article title, so the title would
    otherwise be embedded twice and outweigh the body.
    """
    text = (row.get('text') or '').strip()
    if row.get('rt_of_handle') and text:
        text = _strip_rt_prefix(text, row['rt_of_handle'])

    article = _parsed(row.get('article'))
    if article:
        parts = [article.get('title') or '', article.get('previewText') or '']
        text = '\n'.join(part for part in parts if part).strip() or text

    quote = (row.get('quote_text') or '').strip()
    if quote:
        text = f'{text}\n{quote}'.strip()
    return text or None


def _strip_rt_prefix(text: str, handle: str) -> str:
    prefix = f'RT @{handle}:'
    if not text.startswith(prefix):
        return text
    return text[len(prefix) :].strip() or text


def _parsed(value) -> Optional[dict]:
    if isinstance(value, dict):
        return value
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


# --- scoring ------------------------------------------------------------------


def topic_score(neighbours: list[Neighbour], settings: Settings) -> Optional[ChannelScore]:
    """Channel B: the distance-weighted vote over the labeled neighbours.

    Split out from the thresholding below so the ensemble (and the backtest that
    picks its channels) can read this channel's opinion on the same scale as every
    other one. None is the OOD gate firing — an abstention, not a neutral score.
    """
    close = [n for n in neighbours if n.distance <= settings.condenser_verdict_max_distance]
    if len(close) < settings.condenser_verdict_min_neighbors:
        return None

    numerator = sum(n.similarity * LABEL_WEIGHT[n.label] * LABEL_VALUE[n.label] for n in close)
    denominator = sum(n.similarity * LABEL_WEIGHT[n.label] for n in close)
    evidence = sorted(close, key=lambda n: n.distance)[:META_NEIGHBOURS]
    return ChannelScore(
        score=numerator / denominator if denominator else 0.0,
        # how *near* the neighbourhood is, not how many are in it: a vote from
        # tweets at distance 0.1 is evidence, the same vote at 0.59 is a coincidence
        # that happened to clear the gate
        confidence=max(0.0, min(1.0, sum(n.similarity for n in close) / len(close))),
        corroborated=sum(1 for n in close if n.label == 'down') >= settings.condenser_verdict_min_down_neighbors,
        meta={'neighbors': [n.as_meta() for n in evidence]},
    )


# Every channel that can be configured to vote or shadow. One tuple rather than a
# literal at each site: a new channel that reaches `channel_policy` but not this
# list would be silently unconfigurable.
CHANNEL_KEYS = ('a', 'b', 'c', 'd')


@dataclass(frozen=True)
class ChannelPolicy:
    """One channel's thresholds and its negative admission, resolved from settings.

    Per channel because the scales are incomparable (the reason the combiner is a
    vote at all), and because the revised §9 admits negatives one channel at a
    time. ``negative_enabled`` already has the master switch folded in: the global
    flag is the kill-all, the per-channel flag is the admission, and both must be
    on — so admitting channel D can never quietly resurrect channel B's negative
    side, the one the 2026-07-27 backtest showed to be guessing.
    """

    positive_score: float
    negative_score: float
    negative_enabled: bool


def channel_policy(key: str, settings: Settings) -> ChannelPolicy:
    master = settings.condenser_verdict_negative_enabled
    if key == 'a':
        return ChannelPolicy(
            settings.condenser_verdict_a_positive_score,
            settings.condenser_verdict_a_negative_score,
            master and settings.condenser_verdict_a_negative_enabled,
        )
    if key == 'b':
        return ChannelPolicy(
            settings.condenser_verdict_positive_score,
            settings.condenser_verdict_negative_score,
            master and settings.condenser_verdict_b_negative_enabled,
        )
    if key == 'c':
        return ChannelPolicy(
            settings.condenser_verdict_c_positive_score,
            settings.condenser_verdict_c_negative_score,
            master and settings.condenser_verdict_c_negative_enabled,
        )
    if key == 'd':
        return ChannelPolicy(
            settings.condenser_verdict_d_positive_score,
            settings.condenser_verdict_d_negative_score,
            master and settings.condenser_verdict_d_negative_enabled,
        )
    raise KeyError(key)


def enabled_channels(settings: Settings) -> list[str]:
    """The channels that vote this round, in the configured order. Unknown keys are
    dropped rather than raised: a typo in an env var must degrade, not crash the
    judging loop."""
    keys = [key.strip() for key in settings.condenser_verdict_channels.split(',')]
    return [key for key in keys if key in CHANNEL_KEYS]


def shadow_channels(settings: Settings) -> list[str]:
    """The channels that score and archive this round without casting a vote.

    The cheap half of the revised §9: a channel has to be measured on tweets that
    were judged before they were labeled, and the obvious way to get there — turn
    it on and watch — spends the reader's attention on an unproven channel first.
    Shadowing buys the same evidence for nothing, because the score is archived
    either way and ``scripts/x_verdict_prospective.py`` replays it.

    A channel that already votes is never also shadowed: voting wins, so listing
    one in both places is a harmless typo rather than a silent mute.
    """
    voting = set(enabled_channels(settings))
    keys = [key.strip() for key in settings.condenser_verdict_shadow_channels.split(',')]
    return [key for key in keys if key in CHANNEL_KEYS and key not in voting]


def classify(channel: ChannelScore, policy: ChannelPolicy) -> str:
    """Score -> this channel's vote, with the asymmetry that outlived the backtests.

    Negative additionally needs ``corroborated`` (a second down neighbour, or a
    second bait token) and the channel's admission to be on at all — the score is
    still archived either way, so the evidence outlives the switch.
    """
    if channel.score >= policy.positive_score:
        return POSITIVE
    if policy.negative_enabled and channel.score <= policy.negative_score and channel.corroborated:
        return NEGATIVE
    return NEUTRAL


# --- the round ----------------------------------------------------------------


class VerdictManager:
    """Owns the judging round. One instance lives on ``app.state.verdict``.

    Kicked after each probe push rather than polling: For You only changes when
    the probe pushes. ``embed`` is injectable so tests never touch the network.
    """

    def __init__(self, settings: Settings, embed: Optional[Embedder] = None, extract: Optional[Extractor] = None):
        self.settings = settings
        self._embed = embed or self._default_embedder
        self._extract = extract or self._default_extractor
        self._tasks: set[asyncio.Task] = set()
        self._loop_ref: Optional[asyncio.AbstractEventLoop] = None
        self._lock = asyncio.Lock()

    async def _default_embedder(self, texts: list[str]) -> list[list[float]]:
        return await embedding.embed_texts(texts, self.settings)

    async def _default_extractor(self, texts: list[str]) -> list[Optional[dict]]:
        return await attributes.extract_attributes(texts, self.settings)

    @staticmethod
    def _now() -> datetime:
        """Naive UTC now (storage convention); test seam."""
        return datetime.now(timezone.utc).replace(tzinfo=None)

    # ---- lifecycle ----

    async def startup(self) -> None:
        self._loop_ref = asyncio.get_running_loop()
        # reconcile once on boot: labels may have moved while the process was down
        # (and an upgraded sqlite-vec may have arrived with an empty index)
        self._spawn()

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()

    def kick(self) -> None:
        """Ask for a round. Safe to call from FastAPI's threadpool (asyncio objects
        are not thread-safe) and a no-op before startup."""
        if self._loop_ref is None or self._loop_ref.is_closed():
            return
        self._loop_ref.call_soon_threadsafe(self._spawn)

    def _spawn(self) -> None:
        task = asyncio.create_task(self._guarded_run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _guarded_run(self) -> None:
        try:
            result = await self.run_once()
        except Exception:  # noqa: BLE001 - a judging failure must never take the app down
            log.exception('x verdict round crashed')
            return
        if result.skipped_reason is None:
            log.info(
                'x verdict round: indexed=%s dropped=%s judged=%s attributed=%s pruned=%s',
                result.indexed,
                result.dropped,
                result.judged,
                result.attributed,
                result.pruned,
            )

    # ---- the work ----

    def available(self) -> bool:
        return self.settings.condenser_verdict_enabled and embedding.available(self.settings) and vectors.available()

    def training_counts(self) -> tuple[int, int]:
        """(positives, negatives) currently in the training set."""
        samples = db.x_labeled_samples()
        positives = sum(1 for label in samples.values() if label in ('up', 'save'))
        return positives, len(samples) - positives

    def ready(self) -> bool:
        """Is there enough labeled evidence to say anything at all?"""
        positives, negatives = self.training_counts()
        return (
            positives >= self.settings.condenser_verdict_min_positive
            and negatives >= self.settings.condenser_verdict_min_negative
        )

    async def run_once(self) -> RunResult:
        if not self.settings.condenser_verdict_enabled:
            return RunResult(skipped_reason='disabled')
        if not self.available():
            return RunResult(skipped_reason='unavailable')
        async with self._lock:
            samples = db.x_labeled_samples()
            result = RunResult()
            # Retractions are free (no embedding), so they are never gated: whatever
            # else is true, the index must not still hold a label you took back.
            result.dropped = self._drop_retracted(samples)
            if not self._gate_open(samples):
                # every remaining step costs an API call, and with this few labels it
                # would buy nothing but shrugs — a fresh install spends nothing
                result.skipped_reason = 'cold_start'
                return result
            result.indexed = await self._index_missing(samples)
            keys = enabled_channels(self.settings) + shadow_channels(self.settings)
            if 'c' in keys:
                # Channel C scores off the attributes, so this round's arrivals
                # must be described before they are judged — a tweet is judged
                # exactly once, and an attribute that arrives later never votes.
                # Shadowing C needs the same order for the same reason: a score
                # that arrives after the row is written is never archived at all.
                # (_describe absorbs provider failures, so judging still runs and
                # C simply abstains on whatever went undescribed.)
                await self._describe(result)
            await self._judge(samples, result)
            if 'c' not in keys:
                # With C not scoring, the old order stands: a slow or failing
                # provider must not delay the verdicts the reader actually sees.
                await self._describe(result)
            result.pruned = self._prune(samples)
            db.set_meta(LAST_RUN_META_KEY, self._now().isoformat(sep=' ', timespec='seconds'))
            return result

    def _gate_open(self, samples: dict[int, str]) -> bool:
        positives = sum(1 for label in samples.values() if label in ('up', 'save'))
        negatives = len(samples) - positives
        return (
            positives >= self.settings.condenser_verdict_min_positive
            and negatives >= self.settings.condenser_verdict_min_negative
        )

    def _drop_retracted(self, samples: dict[int, str]) -> int:
        """Remove index entries whose label is gone (undone thumb, unsaved item)."""
        dropped = 0
        for tweet_id in vectors.labeled_ids() - set(samples):
            vectors.delete(tweet_id)
            dropped += 1
        return dropped

    async def _index_missing(self, samples: dict[int, str]) -> int:
        """Add index entries for labels that have none yet.

        Reconciliation rather than write-through on the label endpoints: those stay
        synchronous while embedding needs the network, and anything missed — a
        restart, an API outage, a model change — self-heals on the next round.
        """
        missing = set(samples) - vectors.labeled_ids()
        if not missing:
            return 0
        indexed = 0
        model = embedding.model_tag(self.settings)
        # a vector stored under a different model@dims is not comparable — re-embed
        stored = db.x_embedding_vectors(missing, model)
        for tweet_id, blob in stored.items():
            vectors.upsert(tweet_id, vectors.unpack(blob))
            indexed += 1

        to_embed = missing - set(stored)
        if to_embed:
            indexed += await self._embed_and_index(sorted(to_embed))
        return indexed

    async def _embed_and_index(self, tweet_ids: list[int]) -> int:
        """Embed labeled tweets that have no stored vector yet, and index them."""
        texts, ids = [], []
        for row in db.x_tweet_judge_rows(tweet_ids):
            text = judge_text(row)
            if text:
                texts.append(text)
                ids.append(row['tweet_id'])
        if not texts:
            return 0
        vecs = await self._store_embeddings(ids, texts)
        for tweet_id, vec in vecs.items():
            vectors.upsert(tweet_id, vec)
        return len(vecs)

    async def _store_embeddings(self, ids: list[int], texts: list[str]) -> dict[int, list[float]]:
        vecs = await self._embed(texts)
        model = embedding.model_tag(self.settings)
        now = self._now()
        out = {}
        for tweet_id, vec in zip(ids, vecs):
            db.upsert_x_embedding(tweet_id, vectors.pack(vec), model, now)
            out[tweet_id] = vec
        return out

    async def _judge(self, samples: dict[int, str], result: RunResult) -> None:
        since = self._now() - timedelta(hours=self.settings.condenser_verdict_window_hours)
        rows = db.x_pending_verdict_rows(since, self.settings.condenser_verdict_batch)
        if not rows:
            return

        pending: list[tuple[dict, str]] = []
        for row in rows:
            text = judge_text(row)
            if text is None:
                # nothing to embed (media-only tweet): decide it now so the sweep
                # does not reconsider it every round forever
                db.set_x_verdict(row['channel_id'], row['tweet_id'], NEUTRAL, {'reason': 'no_text'})
                result.judged += 1
                continue
            pending.append((row, text))
        if not pending:
            return

        try:
            vecs = await self._store_embeddings([row['tweet_id'] for row, _ in pending], [text for _, text in pending])
        except Exception:  # noqa: BLE001 - the archive is intact; retry next round
            log.exception('x verdict: embedding failed, leaving %s tweets unjudged', len(pending))
            return

        keys = enabled_channels(self.settings)
        shadows = shadow_channels(self.settings)
        scoring = keys + shadows
        handles = db.x_author_handles(set(samples))
        fitted = self._fit_channels(samples, handles, scoring)
        flags = (
            db.x_attributes_for({row['tweet_id'] for row, _ in pending}, attributes.model_tag(self.settings))
            if 'c' in scoring
            else {}
        )
        for row, text in pending:
            vec = vecs.get(row['tweet_id'])
            if vec is None:
                continue
            judgement = self._judge_one(
                vec,
                text,
                row.get('author_handle'),
                flags.get(row['tweet_id'], []),
                samples,
                handles,
                keys,
                shadows,
                fitted,
            )
            db.set_x_verdict(row['channel_id'], row['tweet_id'], judgement.verdict, judgement.meta)
            result.judged += 1

    def _fit_channels(self, samples: dict[int, str], handles: dict[int, str], keys: list[str]) -> dict:
        """Refit the cheap channels from the live labels, once per round.

        Channel D's counts rebuild from ``x_tweets.text`` in milliseconds at a few
        hundred labels (the no-table decision from step 1); channel C's counts come
        from the stored attributes plus the reader's chips; channel A's are a tally
        over handles the round has already loaded for channel B's evidence. Channel
        B's "model" is the KNN index, which ``_index_missing`` has already reconciled.
        """
        fitted: dict = {}
        if 'a' in keys:
            fitted['a'] = authors.fit(
                authors.LabeledAuthor(handle=handles.get(tid), verdict=samples[tid]) for tid in samples
            )
        if 'd' in keys:
            texts = {row['tweet_id']: judge_text(row) for row in db.x_tweet_judge_rows(sorted(samples))}
            fitted['d'] = ngram.fit((texts[tid], samples[tid] != 'down') for tid in samples if texts.get(tid))
        if 'c' in keys:
            described = db.x_attributes_for(set(samples), attributes.model_tag(self.settings))
            reasons = db.x_down_reasons()
            fitted['c'] = attributes.fit_flags(
                attributes.LabeledFlags(flags=described.get(tid, []), verdict=samples[tid], reason=reasons.get(tid))
                for tid in samples
            )
        return fitted

    def _judge_one(
        self,
        vector: list[float],
        text: str,
        handle: Optional[str],
        flags: list[str],
        samples: dict[int, str],
        handles: dict[int, str],
        keys: list[str],
        shadows: list[str],
        fitted: dict,
    ) -> Judgement:
        scores: dict[str, Optional[ChannelScore]] = {}
        for key in keys + shadows:
            if key == 'a':
                scores['a'] = authors.score(fitted['a'], handle, self.settings)
            elif key == 'b':
                hits = vectors.knn(vector, self.settings.condenser_verdict_k)
                neighbours = [
                    Neighbour(tweet_id, distance, samples[tweet_id], handles.get(tweet_id))
                    for tweet_id, distance in hits
                    if tweet_id in samples
                ]
                scores['b'] = topic_score(neighbours, self.settings)
            elif key == 'c':
                scores['c'] = attributes.score_flags(fitted['c'], flags, self.settings)
            elif key == 'd':
                scores['d'] = ngram.score(fitted['d'], text, self.settings)
        votes = {
            key: None if score is None else classify(score, channel_policy(key, self.settings))
            for key, score in scores.items()
            if key in keys  # a shadow channel scores, archives, and says nothing
        }
        return Judgement(resolve(votes), self._meta(scores, votes, keys, shadows))

    def _meta(
        self,
        scores: dict[str, Optional[ChannelScore]],
        votes: dict[str, Optional[str]],
        keys: list[str],
        shadows: list[str],
    ) -> dict:
        """The archived evidence, additive over the single-channel shape.

        The top level stays channel B's evidence exactly as it always was — shipped
        iOS builds decode ``score`` / ``neighbors``, so the ensemble adds a
        ``channels`` block beside them, never instead of them. Channel B's entry in
        that block carries no second copy of the neighbours (this row is written
        ~1000×/day; the top level already has them).

        A shadow channel is marked, not merely voteless: an *abstaining* channel is
        absent from the block entirely, so without the flag "said nothing" and "was
        not allowed to speak" would be told apart only by the absence of a field.
        """
        topic = scores.get('b')
        if 'b' not in keys and 'b' not in shadows:
            meta: dict = {'score': 0.0, 'neighbors': []}
        elif topic is None:
            meta = {'reason': 'out_of_domain', 'neighbors': [], 'score': 0.0}
        else:
            meta = {'score': round(topic.score, 4), 'neighbors': topic.meta['neighbors']}
        if keys != ['b'] or shadows:
            meta['channels'] = {
                key: {
                    'verdict': votes.get(key),
                    'score': round(score.score, 4),
                    **({'shadow': True} if key in shadows else {}),
                    **(score.meta if key != 'b' else {}),
                }
                for key, score in scores.items()
                if score is not None
            }
        meta['model'] = embedding.model_tag(self.settings)
        meta['algo'] = ALGO_VERSION if keys == ['b'] else ENSEMBLE_ALGO_VERSION
        return meta

    async def _describe(self, result: RunResult) -> None:
        """Read attributes for tweets that have none under the current taxonomy.

        Sits inside the cold-start gate with everything else that costs money, and
        under a hard per-round cap: this is the first component billed per item, and
        a first run against a full archive would otherwise be an unbounded bill.
        """
        if not attributes.available(self.settings):
            return
        model = attributes.model_tag(self.settings)
        since = self._now() - timedelta(hours=self.settings.condenser_verdict_window_hours)
        rows = db.x_describable_rows(since, self.settings.condenser_attr_batch, model)
        texts = [(row['tweet_id'], judge_text(row)) for row in rows]
        texts = [(tweet_id, text) for tweet_id, text in texts if text]
        if not texts:
            return

        try:
            answers = await self._extract([text for _, text in texts])
        except Exception:  # noqa: BLE001 - the archive is intact; retry next round
            log.exception('x verdict: attribute extraction failed for %s tweets', len(texts))
            return

        now = self._now()
        for (tweet_id, _), answer in zip(texts, answers):
            cleaned = attributes.clean(answer)
            if cleaned is None:
                # an unreadable answer leaves the tweet undescribed, so the next
                # round picks it up again rather than storing a guess
                continue
            db.upsert_x_attributes(tweet_id, cleaned['topics'], cleaned['style_flags'], model, now)
            result.attributed += 1

    def _prune(self, samples: dict[int, str]) -> int:
        days = self.settings.condenser_embedding_retention_days
        if days <= 0:
            return 0
        return db.prune_x_embeddings(self._now() - timedelta(days=days), set(samples))


def rebuild_labeled_index() -> int:
    """Re-fill the KNN index from the stored vectors + the label tables.

    The escape hatch for anything that makes the index suspect (a sqlite-vec
    upgrade changing the shadow-table format, a half-finished round): the vectors
    of record are in ``x_embeddings`` and the labels in ``item_feedback`` /
    ``saved_items``, so the index is always reconstructible without re-embedding.
    """
    if not vectors.available():
        return 0
    samples = db.x_labeled_samples()
    vectors.clear()
    indexed = 0
    model = embedding.model_tag(get_settings())
    for tweet_id, blob in db.x_embedding_vectors(set(samples), model).items():
        vectors.upsert(tweet_id, vectors.unpack(blob))
        indexed += 1
    return indexed


def status(settings: Settings, manager: Optional[VerdictManager] = None) -> dict:
    """The verdict half of /api/x/status.

    When no badges show up the first question is "broken, or just waiting?" — this
    answers it without reading logs: whether the pipeline can run at all, whether
    the cold-start gate has opened, and how far the labels are from opening it.
    """
    samples = db.x_labeled_samples()
    positives = sum(1 for label in samples.values() if label in ('up', 'save'))
    negatives = len(samples) - positives
    return {
        'enabled': settings.condenser_verdict_enabled,
        # A third kind of silence, and the least guessable one: trained, judging,
        # and still never a "not for you" badge — because that side is switched off.
        'negative_enabled': settings.condenser_verdict_negative_enabled,
        # Which channels vote (plan v2 step 4). The default is B alone; a channel
        # listed here still abstains whenever it has nothing to say.
        'channels': enabled_channels(settings),
        # And which ones only score into the archive (step 5b). This is the state
        # nothing else can reveal — a shadow channel never changes a badge, so
        # without this line "running silently" looks exactly like "not configured".
        'shadow_channels': shadow_channels(settings),
        'embedding_configured': embedding.available(settings),
        'index_available': vectors.available(),
        'ready': (
            positives >= settings.condenser_verdict_min_positive
            and negatives >= settings.condenser_verdict_min_negative
        ),
        'positives': positives,
        'negatives': negatives,
        'needs_positive': max(0, settings.condenser_verdict_min_positive - positives),
        'needs_negative': max(0, settings.condenser_verdict_min_negative - negatives),
        'indexed': len(vectors.labeled_ids()),
        'embedded': len(db.x_embedding_ids()),
        'judged': db.x_verdict_counts(),
        'model': embedding.model_tag(settings),
        'algo': ALGO_VERSION,
        'last_run_at': db.get_meta(LAST_RUN_META_KEY),
        # The attribute channel is billed per item and scores nothing yet, so the
        # only way to tell "off", "misconfigured" and "working" apart is here.
        'attributes': {
            'enabled': settings.condenser_attr_enabled,
            'configured': attributes.available(settings),
            'model': attributes.model_tag(settings),
            'described': db.x_attribute_count(attributes.model_tag(settings)),
        },
    }
