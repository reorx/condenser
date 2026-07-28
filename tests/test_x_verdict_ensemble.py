"""Behavior tests for the vote combiner and the channel wiring (plan v2 step 4).

Plan: kb/plans/2026-07-27-x-verdict-style-channels.md (§7 as revised 2026-07-28)

The combiner is a **vote**, not a weighted mean. The mean was rejected by the
step-3 backtest — the channels' scales are incomparable (C spans ~[-0.4, +0.1]
where B/D span [-1, +1]), so averaging diluted the sharp channel — and by the
revised §9 governance: admission, prospective monitoring and the kill switch all
operate on "one channel's negative side", which a blended score has no way to
attribute. So every channel classifies with its own thresholds first, and the
verdict is resolved from the votes.

Three properties dominate below:

* **the default changes nothing** — `CONDENSER_VERDICT_CHANNELS=b` must produce
  byte-identical verdicts and metadata to the pre-ensemble code, because step 4
  ships infrastructure, not behavior;
* **negatives are double-gated** — the global master switch AND the channel's own
  admission flag, so admitting channel D can never quietly re-enable channel B's
  negative side (the one the 2026-07-27 backtest killed);
* **the metadata stays additive** — shipped iOS builds decode the top-level
  `score` / `neighbors`, so the multi-channel evidence arrives as a new
  `channels` block beside them, never instead of them.
"""

import json
import math
import os
from datetime import datetime, timedelta

from condenser import db, verdict as verdict_mod, x
from condenser.channels import ChannelScore, resolve
from condenser.config import get_settings
from condenser.verdict import channel_policy, classify, enabled_channels

NOW = datetime(2026, 7, 28, 12, 0)

# Topic axes for the fake embedder (the test_x_verdict.py pattern): orthogonal, so
# a tweet on one axis sits at cosine distance 1.0 from every other axis.
AXES = ('crypto', 'rust', 'cooking', 'ads')


def unit(**weights: float) -> list[float]:
    vec = [0.0] * get_settings().condenser_embedding_dimensions
    for axis, weight in weights.items():
        vec[AXES.index(axis)] = weight
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeEmbedder:
    def __init__(self):
        self.calls: list[list[str]] = []

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [unit(**self._weights(text)) for text in texts]

    def _weights(self, text: str) -> dict:
        for axis in AXES:
            if axis in text:
                return {axis: 1.0}
        return {'ads': 1.0}  # off-topic: an axis nothing is labeled on


class FakeExtractor:
    """Judge text -> attributes by keyword (the test_x_attributes.py pattern)."""

    def __init__(self, answers: dict | None = None):
        self.answers = answers or {}
        self.calls: list[str] = []

    async def __call__(self, texts: list[str]) -> list[dict | None]:
        self.calls.extend(texts)
        return [self._answer(text) for text in texts]

    def _answer(self, text: str) -> dict:
        for keyword, answer in self.answers.items():
            if keyword in text:
                return answer
        return {'topics': ['misc'], 'style_flags': []}


def setup_db(monkeypatch, **overrides) -> None:
    env = {
        'CONDENSER_EMBEDDING_API_KEY': 'test-key',
        'CONDENSER_VERDICT_MIN_POSITIVE': '2',
        'CONDENSER_VERDICT_MIN_NEGATIVE': '2',
        'CONDENSER_VERDICT_MIN_NEIGHBORS': '1',
        **overrides,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    db.init_db(os.environ['CONDENSER_DB_PATH'])


def bird_entry(tweet_id: int, text: str, minutes: int = 0) -> dict:
    created = NOW - timedelta(minutes=minutes)
    return {
        'id': str(tweet_id),
        'text': text,
        'createdAt': created.strftime('%a %b %d %H:%M:%S +0000 %Y'),
        'author': {'username': 'someone', 'name': 'Some One'},
        'authorId': '12345',
    }


def ingest(channel_id: str, *entries) -> None:
    original = x._now
    x._now = lambda: NOW
    try:
        x.ingest_tweets(channel_id, list(entries))
    finally:
        x._now = original


def make_manager(embedder=None, extractor=None) -> verdict_mod.VerdictManager:
    mgr = verdict_mod.VerdictManager(get_settings(), embed=embedder or FakeEmbedder(), extract=extractor)
    mgr._now = lambda: NOW
    return mgr


def label(tweet_id: int, verdict: str, reason: str | None = None) -> None:
    db.set_feedback(db.ItemKey(source='x', ref1=tweet_id), verdict, reason)


def feed_verdict(tweet_id: int):
    row = db.XFeedItem.get_or_none((db.XFeedItem.channel_id == 'foryou') & (db.XFeedItem.tweet_id == tweet_id))
    return None if row is None else row.verdict


def verdict_meta(tweet_id: int) -> dict:
    row = db.XFeedItem.get((db.XFeedItem.channel_id == 'foryou') & (db.XFeedItem.tweet_id == tweet_id))
    return json.loads(row.verdict_meta)


def seed_bait_world(monkeypatch, **overrides):
    """The label mix the ensemble exists for: the downs share a *voice* (bait
    phrasing on crypto), the ups share a subject (rust). Channel B can only see
    the subjects; channel D can see the voice."""
    setup_db(monkeypatch, **overrides)
    db.add_x_subscription('foryou', name=x.FORYOU_NAME, config={'kind': 'home'})
    ingest(
        'foryou',
        bird_entry(101, 'save this thread 🧵 crypto tools you must know', 200),
        bird_entry(102, 'save this thread 🧵 crypto coins you must know', 190),
        bird_entry(201, 'notes on rust borrow checking', 180),
        bird_entry(202, 'more notes on rust async runtimes', 170),
    )
    for tweet_id in (101, 102):
        label(tweet_id, 'down')
    for tweet_id in (201, 202):
        label(tweet_id, 'up')
    return make_manager()


# --- the vote -------------------------------------------------------------------


def test_one_negative_vote_and_no_positive_is_negative():
    assert resolve({'b': 'neutral', 'd': 'negative'}) == 'negative'


def test_one_positive_vote_and_no_negative_is_positive():
    assert resolve({'b': 'positive', 'd': 'neutral'}) == 'positive'


def test_conflicting_votes_land_neutral():
    """Conservative on purpose: a wrong negative costs the tweet, so a positive
    voice anywhere is enough to hold the badge back. Whether the positive should
    *win* outright is a data question — measure the conflict rate first."""
    assert resolve({'b': 'positive', 'd': 'negative'}) == 'neutral'


def test_abstention_is_not_a_vote():
    """The channels.py rule, carried into the vote: silence must stay
    distinguishable from a considered neutral."""
    assert resolve({'b': None, 'd': 'positive'}) == 'positive'
    assert resolve({'b': None, 'd': None}) == 'neutral'


# --- per-channel thresholds and the double gate -----------------------------------


def test_each_channel_classifies_with_its_own_thresholds(env, monkeypatch):
    """The whole reason the combiner is a vote: -0.5 clears channel D's backtested
    line (-0.45) but not channel B's (-0.55). One shared threshold could not say
    that."""
    setup_db(
        monkeypatch,
        CONDENSER_VERDICT_NEGATIVE_ENABLED='1',
        CONDENSER_VERDICT_B_NEGATIVE_ENABLED='1',
        CONDENSER_VERDICT_D_NEGATIVE_ENABLED='1',
    )
    settings = get_settings()
    score = ChannelScore(-0.5)

    assert classify(score, channel_policy('d', settings)) == 'negative'
    assert classify(score, channel_policy('b', settings)) == 'neutral'


def test_negative_needs_both_the_master_switch_and_the_channels_admission(env, monkeypatch):
    """Admission is per channel (revised §9), the master switch is the kill-all.
    Either alone must not produce a negative — otherwise flipping the master for
    channel D would quietly resurrect channel B's dead negative side."""
    score = ChannelScore(-0.9)

    setup_db(monkeypatch, CONDENSER_VERDICT_NEGATIVE_ENABLED='0', CONDENSER_VERDICT_D_NEGATIVE_ENABLED='1')
    assert classify(score, channel_policy('d', get_settings())) == 'neutral'

    setup_db(monkeypatch, CONDENSER_VERDICT_NEGATIVE_ENABLED='1', CONDENSER_VERDICT_D_NEGATIVE_ENABLED='0')
    assert classify(score, channel_policy('d', get_settings())) == 'neutral'

    setup_db(monkeypatch, CONDENSER_VERDICT_NEGATIVE_ENABLED='1', CONDENSER_VERDICT_D_NEGATIVE_ENABLED='1')
    assert classify(score, channel_policy('d', get_settings())) == 'negative'


def test_unknown_channel_keys_are_ignored(env, monkeypatch):
    setup_db(monkeypatch, CONDENSER_VERDICT_CHANNELS='b, z ,d')

    assert enabled_channels(get_settings()) == ['b', 'd']


# --- the default changes nothing --------------------------------------------------


async def test_with_the_default_channels_the_meta_is_unchanged(env, monkeypatch):
    """Step 4 ships infrastructure: with `channels=b` (the default) the stored
    verdict and its metadata are exactly what the pre-ensemble code wrote — no
    `channels` block, the same algo tag — so deploying this changes nothing."""
    mgr = seed_bait_world(monkeypatch)
    ingest('foryou', bird_entry(301, 'a fresh take on rust lifetimes', 5))

    await mgr.run_once()

    assert feed_verdict(301) == 'positive'
    meta = verdict_meta(301)
    assert 'channels' not in meta
    assert meta['algo'] == 'knn-v1'
    assert meta['score'] > 0
    assert meta['neighbors']


# --- the wiring ------------------------------------------------------------------


async def test_channel_d_carries_a_negative_where_the_knn_abstains(env, monkeypatch):
    """The scenario this whole plan exists for: the same bait phrasing on a subject
    you never labeled. Channel B is honestly out of domain; channel D reads the
    words and votes it down."""
    mgr = seed_bait_world(
        monkeypatch,
        CONDENSER_VERDICT_CHANNELS='b,d',
        CONDENSER_VERDICT_NEGATIVE_ENABLED='1',
        CONDENSER_VERDICT_D_NEGATIVE_ENABLED='1',
    )
    ingest('foryou', bird_entry(301, 'save this thread 🧵 gardening tools you must know', 5))

    await mgr.run_once()

    assert feed_verdict(301) == 'negative'
    meta = verdict_meta(301)
    # channel B abstained, and the top level says so the way it always has
    assert meta['reason'] == 'out_of_domain'
    # the evidence names the channel and its words
    assert meta['channels']['d']['verdict'] == 'negative'
    tokens = [token for token, _ in meta['channels']['d']['tokens']]
    assert 'save this' in tokens


async def test_an_unadmitted_channel_never_votes_negative(env, monkeypatch):
    """Same tweet, same evidence, but channel D's admission flag is off: the score
    is still archived in the channels block while the verdict stays neutral. This
    is the per-channel kill switch the revised §9 monitoring relies on."""
    mgr = seed_bait_world(monkeypatch, CONDENSER_VERDICT_CHANNELS='b,d')
    ingest('foryou', bird_entry(301, 'save this thread 🧵 gardening tools you must know', 5))

    await mgr.run_once()

    assert feed_verdict(301) == 'neutral'
    meta = verdict_meta(301)
    assert meta['channels']['d']['verdict'] == 'neutral'
    assert meta['channels']['d']['score'] < 0  # the evidence outlives the switch


async def test_conflicting_channels_hold_the_verdict_at_neutral(env, monkeypatch):
    """Bait phrasing on a subject you *like*: channel B votes positive off the rust
    neighbours, channel D votes negative off the phrasing. Neither wins."""
    mgr = seed_bait_world(
        monkeypatch,
        CONDENSER_VERDICT_CHANNELS='b,d',
        CONDENSER_VERDICT_NEGATIVE_ENABLED='1',
        CONDENSER_VERDICT_D_NEGATIVE_ENABLED='1',
    )
    ingest('foryou', bird_entry(301, 'save this thread 🧵 rust tools you must know', 5))

    await mgr.run_once()

    assert feed_verdict(301) == 'neutral'
    meta = verdict_meta(301)
    assert meta['channels']['b']['verdict'] == 'positive'
    assert meta['channels']['d']['verdict'] == 'negative'


async def test_multi_channel_meta_keeps_the_topic_evidence_for_old_clients(env, monkeypatch):
    """Shipped iOS builds decode the top-level score/neighbors. The channels block
    is added beside them, never instead of them."""
    mgr = seed_bait_world(
        monkeypatch,
        CONDENSER_VERDICT_CHANNELS='b,d',
    )
    ingest('foryou', bird_entry(301, 'a fresh take on rust lifetimes', 5))

    await mgr.run_once()

    assert feed_verdict(301) == 'positive'
    meta = verdict_meta(301)
    assert meta['score'] > 0
    assert meta['neighbors']
    assert meta['algo'] == 'vote-v1'
    assert meta['channels']['b']['verdict'] == 'positive'


async def test_channel_c_votes_from_the_attributes_extracted_this_round(env, monkeypatch):
    """With channel C enabled, description runs *before* judging — a fresh arrival
    is described and then judged off its attributes in the same round. (Without C
    in the mix the old order stands: nothing may delay the verdicts for a channel
    that does not score.)

    The training set: promo-flagged tweets the reader downed with the promo chip,
    clean tweets upped. A new promo-flagged arrival on an unlabeled subject gets
    channel C's negative while channel B abstains.
    """
    extractor = FakeExtractor(
        answers={
            'crypto': {'topics': ['crypto'], 'style_flags': ['promo_cta']},
            'course': {'topics': ['course'], 'style_flags': ['promo_cta']},
        }
    )
    setup_db(
        monkeypatch,
        CONDENSER_ATTR_API_KEY='test-key',
        CONDENSER_VERDICT_CHANNELS='b,c',
        CONDENSER_VERDICT_NEGATIVE_ENABLED='1',
        CONDENSER_VERDICT_C_NEGATIVE_ENABLED='1',
        CONDENSER_VERDICT_C_MIN_OBSERVATIONS='1',
        CONDENSER_VERDICT_C_NEGATIVE_SCORE='-0.1',
    )
    db.add_x_subscription('foryou', name=x.FORYOU_NAME, config={'kind': 'home'})
    ingest(
        'foryou',
        bird_entry(101, 'crypto presale is live, buy now', 200),
        bird_entry(102, 'crypto signals group, join today', 190),
        bird_entry(201, 'notes on rust borrow checking', 180),
        bird_entry(202, 'more notes on rust async runtimes', 170),
    )
    label(101, 'down', 'promo')
    label(102, 'down', 'promo')
    label(201, 'up')
    label(202, 'up')
    mgr = make_manager(extractor=extractor)
    ingest('foryou', bird_entry(301, 'limited seats: buy my course today', 5))

    await mgr.run_once()

    assert feed_verdict(301) == 'negative'
    meta = verdict_meta(301)
    assert meta['channels']['c']['verdict'] == 'negative'
    assert meta['channels']['c']['driver'] == 'promo_cta'


async def test_a_tweet_without_attributes_leaves_channel_c_abstaining(env, monkeypatch):
    """A failed or capped extraction is not an opinion: the tweet is judged by the
    channels that can read it, and C simply is not in the evidence."""
    setup_db(
        monkeypatch,
        CONDENSER_ATTR_API_KEY='',  # extraction unavailable: nothing is ever described
        CONDENSER_VERDICT_CHANNELS='b,c',
    )
    db.add_x_subscription('foryou', name=x.FORYOU_NAME, config={'kind': 'home'})
    ingest(
        'foryou',
        bird_entry(101, 'crypto presale is live', 200),
        bird_entry(102, 'crypto signals group', 190),
        bird_entry(201, 'notes on rust borrow checking', 180),
        bird_entry(202, 'more notes on rust async runtimes', 170),
    )
    label(101, 'down', 'promo')
    label(102, 'down', 'promo')
    label(201, 'up')
    label(202, 'up')
    mgr = make_manager()
    ingest('foryou', bird_entry(301, 'a fresh take on rust lifetimes', 5))

    await mgr.run_once()

    assert feed_verdict(301) == 'positive'  # channel B still speaks
    assert 'c' not in verdict_meta(301)['channels']


# --- visibility ------------------------------------------------------------------


async def test_status_reports_the_enabled_channels(env, monkeypatch):
    from fastapi.testclient import TestClient

    from condenser.app import create_app

    seed_bait_world(monkeypatch, CONDENSER_VERDICT_CHANNELS='b,d')

    with TestClient(create_app()) as client:
        assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200
        status = client.get('/api/x/status').json()

    assert status['verdict']['channels'] == ['b', 'd']
