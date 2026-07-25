"""Behavior tests for the X source, Phase 4: the embedding verdict.

Plan: kb/plans/2026-07-24-x-source-local-probe.md

Phase 3 collected labels; Phase 4 turns them into a judgement on *new* For You
tweets. The design is defensive by construction — the default answer is
``neutral`` and two gates keep it there: the cold-start gate (too few labels to
generalize) and the OOD gate (this tweet is far from everything you ever
labelled). Only when there is real evidence does a verdict get written, and even
then it is only a badge: nothing is hidden or re-ranked in this phase.

The tests below are about those guarantees, not about classifier quality —
accuracy is a question for the leave-one-out backtest once real labels exist.
Embeddings come from an injected fake whose vectors are hand-placed on a few
orthogonal "topic" axes, so every distance in these tests is one we chose.
"""

import json
import math
import os
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from condenser import db, vectors, verdict as verdict_mod, x
from condenser.app import create_app
from condenser.config import get_settings
from condenser.items import x_key
from telememo import db as tdb

NOW = datetime(2026, 7, 25, 12, 0)

# Topic axes the fake embedder places vectors on. Orthogonal, so a tweet on one
# topic sits at cosine distance 1.0 from a tweet on another — comfortably past
# the OOD gate — while mixtures give us any distance in between.
AXES = ('crypto', 'rust', 'cooking', 'ads')


def unit(**weights: float) -> list[float]:
    """A unit vector over ``AXES``, zero-padded to the configured dimension."""
    vec = [0.0] * get_settings().condenser_embedding_dimensions
    for axis, weight in weights.items():
        vec[AXES.index(axis)] = weight
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeEmbedder:
    """Judge text -> vector, by the first topic word found in the text.

    Records every call so a test can assert the API was *not* touched (the
    cold-start gate's whole point is to not spend money before it can be useful).
    """

    def __init__(self, topics: dict[str, dict] | None = None):
        # topic word -> axis weights; the default puts each word on its own axis
        self.topics = topics or {axis: {axis: 1.0} for axis in AXES}
        self.calls: list[list[str]] = []
        self.error: Exception | None = None

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        return [unit(**self._weights(text)) for text in texts]

    def _weights(self, text: str) -> dict:
        for word, weights in self.topics.items():
            if word in text:
                return weights
        return {'ads': 1.0}  # off-topic: an axis nothing is labeled on

    @property
    def embedded(self) -> list[str]:
        return [text for call in self.calls for text in call]


def bird_entry(tweet_id: int, text: str, minutes: int = 0, **over) -> dict:
    """One bird feed entry (the shape ingest parses)."""
    created = NOW - timedelta(minutes=minutes)
    entry = {
        'id': str(tweet_id),
        'text': text,
        'createdAt': created.strftime('%a %b %d %H:%M:%S +0000 %Y'),
        'replyCount': 1,
        'retweetCount': 2,
        'likeCount': 3,
        'author': {'username': 'someone', 'name': 'Some One'},
        'authorId': '12345',
    }
    entry.update(over)
    return entry


def setup_db(monkeypatch, **overrides) -> None:
    """Init the DB with verdict knobs dialed down to test-sized numbers."""
    env = {
        'CONDENSER_EMBEDDING_API_KEY': 'test-key',
        'CONDENSER_EMBEDDING_MODEL': 'text-embedding-v4',
        'CONDENSER_VERDICT_MIN_POSITIVE': '2',
        'CONDENSER_VERDICT_MIN_NEGATIVE': '2',
        'CONDENSER_VERDICT_MIN_NEIGHBORS': '1',
        **overrides,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    db.init_db(os.environ['CONDENSER_DB_PATH'])


def make_manager(embedder=None, now=NOW) -> verdict_mod.VerdictManager:
    mgr = verdict_mod.VerdictManager(get_settings(), embed=embedder or FakeEmbedder())
    mgr._now = lambda: now
    return mgr


def seed_foryou(*entries) -> None:
    db.add_x_subscription('foryou', name=x.FORYOU_NAME, config={'kind': 'home'})
    ingest('foryou', *entries)


def ingest(channel_id: str, *entries, at: datetime = NOW) -> None:
    original = x._now
    x._now = lambda: at
    try:
        x.ingest_tweets(channel_id, list(entries))
    finally:
        x._now = original


def label(tweet_id: int, verdict: str) -> None:
    db.set_feedback(db.ItemKey(source='x', ref1=tweet_id), verdict)


def save(tweet_id: int) -> None:
    db.add_saved_item('x', tweet_id, 0, {'source': 'x', 'key': x_key(tweet_id)})


def train(*, ups: list[int] = (), downs: list[int] = (), saves: list[int] = ()) -> None:
    """Label enough tweets to open the (test-sized) cold-start gate."""
    for tweet_id in ups:
        label(tweet_id, 'up')
    for tweet_id in downs:
        label(tweet_id, 'down')
    for tweet_id in saves:
        save(tweet_id)


def feed_verdict(tweet_id: int, channel_id: str = 'foryou'):
    row = db.XFeedItem.get_or_none((db.XFeedItem.channel_id == channel_id) & (db.XFeedItem.tweet_id == tweet_id))
    return None if row is None else row.verdict


def seed_labelled_world(monkeypatch, embedder=None):
    """The standard fixture: two crypto tweets downed, two rust tweets upped."""
    setup_db(monkeypatch)
    seed_foryou(
        bird_entry(101, 'crypto to the moon', minutes=200),
        bird_entry(102, 'crypto presale now', minutes=190),
        bird_entry(201, 'rust borrow checker notes', minutes=180),
        bird_entry(202, 'rust async runtimes compared', minutes=170),
    )
    train(downs=[101, 102], ups=[201, 202])
    return make_manager(embedder or FakeEmbedder())


# --- inertness: nothing happens until it can happen -----------------------------


async def test_without_an_api_key_the_whole_pipeline_is_inert(env, monkeypatch):
    """No key configured = the feature does not exist. Tweets still archive fine."""
    setup_db(monkeypatch, CONDENSER_EMBEDDING_API_KEY='')
    embedder = FakeEmbedder()
    seed_foryou(bird_entry(101, 'crypto to the moon'))
    train(downs=[101], ups=[])

    result = await make_manager(embedder).run_once()

    assert result.skipped_reason == 'unavailable'
    assert embedder.calls == []
    assert feed_verdict(101) is None


async def test_without_the_vector_extension_the_pipeline_is_inert(env, monkeypatch):
    """sqlite-vec is a loadable extension; an environment that cannot load it must
    degrade to no verdicts rather than break ingest."""
    mgr = seed_labelled_world(monkeypatch)
    monkeypatch.setattr(vectors, 'available', lambda: False)

    result = await mgr.run_once()

    assert result.skipped_reason == 'unavailable'


async def test_the_cold_start_gate_refuses_to_embed_at_all(env, monkeypatch):
    """Too few labels to generalize -> don't pretend, and don't spend: the gate sits
    *before* the embedding call, so a fresh install never touches the API."""
    setup_db(monkeypatch)
    embedder = FakeEmbedder()
    seed_foryou(
        bird_entry(101, 'crypto to the moon', minutes=100),
        bird_entry(301, 'cooking sourdough', minutes=10),
    )
    train(downs=[101])  # one negative, zero positives

    result = await make_manager(embedder).run_once()

    assert result.skipped_reason == 'cold_start'
    assert embedder.calls == []
    assert feed_verdict(301) is None


async def test_the_gate_opens_once_both_sides_have_evidence(env, monkeypatch):
    mgr = seed_labelled_world(monkeypatch)
    ingest('foryou', bird_entry(301, 'rust lifetimes explained', minutes=5))

    result = await mgr.run_once()

    assert result.skipped_reason is None
    assert feed_verdict(301) == 'positive'


# --- the training index tracks the labels ---------------------------------------


async def test_labelling_a_tweet_puts_its_vector_in_the_training_index(env, monkeypatch):
    mgr = seed_labelled_world(monkeypatch)

    await mgr.run_once()

    assert vectors.labeled_ids() == {101, 102, 201, 202}
    assert db.x_embedding_ids({101, 102, 201, 202}) == {101, 102, 201, 202}


async def test_undoing_a_label_drops_it_from_training(env, monkeypatch):
    """The label table is the truth; the index reconciles to it, so an undo removes
    the sample without any bespoke sync code on the endpoint."""
    mgr = seed_labelled_world(monkeypatch)
    await mgr.run_once()

    db.clear_feedback(db.ItemKey(source='x', ref1=101))
    result = await mgr.run_once()

    assert result.dropped == 1
    assert vectors.labeled_ids() == {102, 201, 202}


async def test_unsaving_drops_the_saved_positive(env, monkeypatch):
    """Saves are strong positives read live from saved_items — unsaving retracts them."""
    setup_db(monkeypatch)
    seed_foryou(
        bird_entry(101, 'crypto to the moon', minutes=200),
        bird_entry(102, 'crypto presale now', minutes=190),
        bird_entry(201, 'rust borrow checker notes', minutes=180),
        bird_entry(202, 'rust async runtimes compared', minutes=170),
    )
    train(downs=[101, 102], saves=[201, 202])
    mgr = make_manager()
    await mgr.run_once()
    assert 201 in vectors.labeled_ids()

    db.delete_saved_item('x', 201, 0)
    await mgr.run_once()

    assert 201 not in vectors.labeled_ids()


async def test_a_saved_but_downvoted_tweet_is_a_contradiction_and_is_excluded(env, monkeypatch):
    """Both signals on one tweet cancel: a contradictory sample teaches nothing and
    would silently pull the boundary in whichever direction the tie-break picked."""
    setup_db(monkeypatch)
    seed_foryou(
        bird_entry(101, 'crypto to the moon', minutes=200),
        bird_entry(102, 'crypto presale now', minutes=190),
        bird_entry(201, 'rust borrow checker notes', minutes=180),
        bird_entry(202, 'rust async runtimes compared', minutes=170),
    )
    train(downs=[101, 102], ups=[201, 202])
    save(101)  # saved *and* downvoted
    mgr = make_manager()

    await mgr.run_once()

    assert 101 not in vectors.labeled_ids()


async def test_rebuilding_the_index_restores_it_from_the_tables(env, monkeypatch):
    """vec0 is a rebuildable cache: the vectors live in x_embeddings and the labels in
    item_feedback / saved_items, so a wiped index is a non-event (sqlite-vec upgrades)."""
    mgr = seed_labelled_world(monkeypatch)
    await mgr.run_once()

    vectors.clear()
    assert vectors.labeled_ids() == set()
    verdict_mod.rebuild_labeled_index()

    assert vectors.labeled_ids() == {101, 102, 201, 202}


async def test_rebuilding_does_not_re_embed(env, monkeypatch):
    """The rebuild reads stored vectors — it must not turn into an API bill."""
    embedder = FakeEmbedder()
    mgr = seed_labelled_world(monkeypatch, embedder)
    await mgr.run_once()
    before = len(embedder.calls)

    vectors.clear()
    verdict_mod.rebuild_labeled_index()

    assert len(embedder.calls) == before


# --- judging --------------------------------------------------------------------


async def test_a_tweet_like_your_upvotes_is_positive(env, monkeypatch):
    mgr = seed_labelled_world(monkeypatch)
    ingest('foryou', bird_entry(301, 'rust trait objects', minutes=5))

    await mgr.run_once()

    assert feed_verdict(301) == 'positive'


async def test_a_tweet_like_your_downvotes_is_negative(env, monkeypatch):
    mgr = seed_labelled_world(monkeypatch)
    ingest('foryou', bird_entry(301, 'crypto airdrop live', minutes=5))

    await mgr.run_once()

    assert feed_verdict(301) == 'negative'


async def test_one_down_neighbour_is_not_enough_to_go_negative(env, monkeypatch):
    """Asymmetric by design: a mis-clicked down must not blacklist a whole
    neighbourhood, so negative needs corroboration from a second down sample."""
    setup_db(monkeypatch, CONDENSER_VERDICT_MIN_NEGATIVE='1')
    seed_foryou(
        bird_entry(101, 'crypto to the moon', minutes=200),
        bird_entry(201, 'rust borrow checker notes', minutes=180),
        bird_entry(202, 'rust async runtimes compared', minutes=170),
    )
    train(downs=[101], ups=[201, 202])
    mgr = make_manager()
    ingest('foryou', bird_entry(301, 'crypto airdrop live', minutes=5))

    await mgr.run_once()

    assert feed_verdict(301) == 'neutral'


async def test_a_tweet_far_from_every_label_stays_neutral(env, monkeypatch):
    """The OOD gate. Without it kNN always returns k neighbours and every tweet gets
    scored off whatever happened to be nearest — the most important gate of the two."""
    mgr = seed_labelled_world(monkeypatch)
    ingest('foryou', bird_entry(301, 'cooking sourdough at home', minutes=5))

    await mgr.run_once()

    assert feed_verdict(301) == 'neutral'
    meta = verdict_meta(301)
    assert meta['reason'] == 'out_of_domain'
    assert meta['neighbors'] == []


def verdict_meta(tweet_id: int, channel_id: str = 'foryou') -> dict:
    row = db.XFeedItem.get((db.XFeedItem.channel_id == channel_id) & (db.XFeedItem.tweet_id == tweet_id))
    return json.loads(row.verdict_meta)


async def test_a_save_counts_double_an_up(env, monkeypatch):
    """Saving is a higher-grade positive than a thumb — it costs an intent, not a
    reflex — so it carries twice the sample weight.

    One save and one down at the same distance therefore score +1/3 rather than the
    0.0 an up would have produced. Asserting the score, not the verdict, keeps this
    about the weighting: +1/3 is still below the positive threshold, and it should
    stay that way — a tilt is not evidence.
    """
    setup_db(monkeypatch, CONDENSER_VERDICT_MIN_POSITIVE='1', CONDENSER_VERDICT_MIN_NEGATIVE='1')
    seed_foryou(
        bird_entry(101, 'rust macro hygiene', minutes=200),
        bird_entry(102, 'rust pin and unpin', minutes=190),
    )
    train(downs=[101], saves=[102])
    mgr = make_manager()
    ingest('foryou', bird_entry(301, 'rust trait objects', minutes=5))

    await mgr.run_once()

    assert verdict_meta(301)['score'] == round(1 / 3, 4)
    assert feed_verdict(301) == 'neutral'


async def test_verdict_meta_records_the_evidence(env, monkeypatch):
    """'Badge, don't hide' only works if the badge can explain itself — and the
    explanation is also what makes a wrong verdict correctable by one click."""
    mgr = seed_labelled_world(monkeypatch)
    ingest('foryou', bird_entry(301, 'crypto airdrop live', minutes=5))

    await mgr.run_once()

    meta = verdict_meta(301)
    assert meta['algo'] == verdict_mod.ALGO_VERSION
    assert meta['model'] == 'text-embedding-v4@256'
    assert {n['label'] for n in meta['neighbors']} == {'down'}
    # snowflake ids cross the API as strings (int64 > JS safe range)
    assert all(isinstance(n['tweet_id'], str) for n in meta['neighbors'])
    # the author is what makes the evidence readable to a person
    assert {n['handle'] for n in meta['neighbors']} == {'someone'}


async def test_stored_evidence_is_capped(env, monkeypatch):
    """Every close neighbour votes, but only the nearest few are archived: this row
    is written ~1000x/day on For You, and an unbounded list of ids would outgrow the
    tweets it explains."""
    setup_db(monkeypatch)
    crypto = [bird_entry(100 + i, f'crypto shill number {i}', minutes=200 - i) for i in range(8)]
    seed_foryou(*crypto, bird_entry(201, 'rust borrow checker notes', minutes=180))
    train(downs=[100 + i for i in range(8)], ups=[201])
    monkeypatch.setenv('CONDENSER_VERDICT_MIN_POSITIVE', '1')
    get_settings.cache_clear()
    mgr = make_manager()
    ingest('foryou', bird_entry(301, 'crypto airdrop live', minutes=5))

    await mgr.run_once()

    # all 8 downs are within range and drive the verdict...
    assert feed_verdict(301) == 'negative'
    # ...but the stored explanation keeps only the nearest few
    assert len(verdict_meta(301)['neighbors']) == verdict_mod.META_NEIGHBOURS


async def test_only_for_you_gets_a_verdict(env, monkeypatch):
    """You chose to follow the account; an algorithm second-guessing that choice is
    noise. Followed feeds are still labellable — that is training data, not ranking."""
    mgr = seed_labelled_world(monkeypatch)
    db.add_x_subscription('someone', name=None, config={'kind': 'user', 'handle': 'someone'})
    ingest('someone', bird_entry(401, 'crypto airdrop live', minutes=5))

    await mgr.run_once()

    assert feed_verdict(401, 'someone') is None


async def test_judging_is_idempotent(env, monkeypatch):
    """A judged row is done: verdicts are computed once at ingest, not re-litigated
    every round (For You is consumed streaming — a retro-verdict helps nobody)."""
    embedder = FakeEmbedder()
    mgr = seed_labelled_world(monkeypatch, embedder)
    ingest('foryou', bird_entry(301, 'rust trait objects', minutes=5))
    await mgr.run_once()
    embedded_once = embedder.embedded

    result = await mgr.run_once()

    assert result.judged == 0
    assert embedder.embedded == embedded_once


async def test_tweets_older_than_the_window_are_left_unjudged(env, monkeypatch):
    """A backlog from a probe that was offline for a week is stale reading anyway;
    judging it would embed the whole backlog for nothing."""
    mgr = seed_labelled_world(monkeypatch)
    ingest('foryou', bird_entry(301, 'rust trait objects'), at=NOW - timedelta(hours=72))

    await mgr.run_once()

    assert feed_verdict(301) is None


async def test_a_tweet_with_no_judgeable_text_is_terminally_neutral(env, monkeypatch):
    """Media-only tweets have nothing to embed. Mark them decided so the sweep does
    not reconsider them forever."""
    mgr = seed_labelled_world(monkeypatch)
    ingest('foryou', bird_entry(301, '', minutes=5))

    await mgr.run_once()

    assert feed_verdict(301) == 'neutral'
    assert verdict_meta(301)['reason'] == 'no_text'


# --- what text gets judged ------------------------------------------------------


def test_judge_text_strips_the_retweet_prefix():
    """bird flattens a retweet to 'RT @orig: <text>'; the judgement is about the
    original's content, not about the word 'RT'."""
    row = {'text': 'RT @someone: rust trait objects explained', 'rt_of_handle': 'someone'}
    assert verdict_mod.judge_text(row) == 'rust trait objects explained'


def test_judge_text_appends_the_quoted_tweet():
    """A quote tweet's meaning lives in both halves ('look at this nonsense' + the
    nonsense), so both are embedded."""
    row = {'text': 'this is why we cannot have nice things', 'quote_text': 'crypto to the moon'}
    assert verdict_mod.judge_text(row) == 'this is why we cannot have nice things\ncrypto to the moon'


def test_judge_text_uses_article_title_and_preview():
    """X long-form only exposes title + a truncated preview; the tweet's own `text`
    is just the title again, so printing it twice would double-weight it."""
    row = {
        'text': 'The State of Async Rust',
        'article': '{"title": "The State of Async Rust", "previewText": "A survey of runtimes."}',
    }
    assert verdict_mod.judge_text(row) == 'The State of Async Rust\nA survey of runtimes.'


def test_judge_text_is_none_when_there_is_nothing_to_read():
    assert verdict_mod.judge_text({'text': None}) is None
    assert verdict_mod.judge_text({'text': '   '}) is None


# --- robustness -----------------------------------------------------------------


async def test_an_embedding_failure_leaves_the_row_pending(env, monkeypatch):
    """The verdict is an async enhancement: if the API is down the tweet is archived
    and readable, unjudged, and the next round picks it up."""
    embedder = FakeEmbedder()
    mgr = seed_labelled_world(monkeypatch, embedder)
    await mgr.run_once()  # index the training set while the API still works
    ingest('foryou', bird_entry(301, 'rust trait objects', minutes=5))
    embedder.error = RuntimeError('dashscope is down')

    result = await mgr.run_once()

    assert result.judged == 0
    assert feed_verdict(301) is None

    embedder.error = None
    await mgr.run_once()
    assert feed_verdict(301) == 'positive'


async def test_ingest_still_succeeds_when_judging_is_broken(env, monkeypatch):
    """The push endpoint's job is to archive. A verdict failure must never make the
    probe think its data was rejected."""

    def boom():
        raise RuntimeError('scheduling blew up')

    setup_db(monkeypatch)
    with TestClient(create_app()) as client:
        assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200
        client.post('/api/sources/x/subscriptions', json={'channel_id': 'foryou'})
        monkeypatch.setattr(client.app.state.verdict, 'kick', boom)

        r = client.post('/api/sources/x/ingest', json={'channel_id': 'foryou', 'tweets': [bird_entry(301, 'hi')]})

        assert r.status_code == 200
        assert db.XTweet.get_or_none(db.XTweet.id == 301) is not None


# --- storage --------------------------------------------------------------------


async def test_unlabelled_vectors_are_pruned_after_retention(env, monkeypatch):
    """For You embeds ~1000 tweets/day. Their vectors are used once, at judge time,
    and are re-derivable from x_tweets.text — so they expire."""
    mgr = seed_labelled_world(monkeypatch)
    ingest('foryou', bird_entry(301, 'rust trait objects', minutes=5))
    await mgr.run_once()
    assert db.x_embedding_ids({301}) == {301}

    stale = NOW + timedelta(days=100)
    mgr._now = lambda: stale
    result = await mgr.run_once()

    assert result.pruned == 1
    assert db.x_embedding_ids({301}) == set()
    # the labelled ones are the training set — they stay
    assert db.x_embedding_ids({101, 201}) == {101, 201}


def test_schema_v8_adds_the_vector_tables_without_touching_data(env, monkeypatch):
    """v8 is additive (new tables only), but the upgrade still has to be proven
    non-destructive on a database that already holds an archive and labels."""
    setup_db(monkeypatch)
    seed_foryou(bird_entry(101, 'crypto to the moon'))
    label(101, 'down')

    # roll the file back to the v7 shape: no vector tables, older version stamp
    tdb.db.execute_sql('DROP TABLE IF EXISTS x_embeddings')
    tdb.db.execute_sql(f'DROP TABLE IF EXISTS {vectors.TABLE}')
    db.set_meta('schema_version', '7')
    db.set_meta(vectors.DIMS_META_KEY, None)

    db.init_db(os.environ['CONDENSER_DB_PATH'], get_settings().condenser_embedding_dimensions)

    assert db.get_meta('schema_version') == '8'
    assert db.XTweet.get_or_none(db.XTweet.id == 101) is not None
    assert db.get_feedback('x', 101) == 'down'
    assert vectors.available()
    assert vectors.labeled_ids() == set()  # a fresh index, ready to be filled


# --- surfaces -------------------------------------------------------------------


async def test_the_verdict_reaches_the_timeline_envelope(env, monkeypatch):
    """The badge is rendered from the envelope, so both the label and its evidence
    have to survive the trip out."""
    mgr = seed_labelled_world(monkeypatch)
    ingest('foryou', bird_entry(301, 'crypto airdrop live', minutes=5))
    await mgr.run_once()

    with TestClient(create_app()) as client:
        assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200
        items = client.get('/api/timeline', params={'source': 'x', 'feed': 'foryou', 'limit': 50}).json()['items']

    item = next(i for i in items if i['key'] == x_key(301))
    assert item['x']['verdict'] == 'negative'
    assert item['x']['verdict_meta']['score'] < 0


async def test_status_reports_the_gate_and_the_counts(env, monkeypatch):
    """When no badges appear, the first question is 'is it broken or just waiting?' —
    the status line has to answer it without reading logs."""
    mgr = seed_labelled_world(monkeypatch)
    ingest('foryou', bird_entry(301, 'crypto airdrop live', minutes=5))
    await mgr.run_once()

    with TestClient(create_app()) as client:
        assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200
        status = client.get('/api/x/status').json()

    assert status['verdict']['ready'] is True
    assert status['verdict']['positives'] == 2
    assert status['verdict']['negatives'] == 2
    assert status['verdict']['judged']['negative'] == 1


async def test_status_says_when_it_is_only_waiting_for_labels(env, monkeypatch):
    setup_db(monkeypatch)
    seed_foryou(bird_entry(101, 'crypto to the moon'))
    train(downs=[101])

    with TestClient(create_app()) as client:
        assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200
        status = client.get('/api/x/status').json()

    assert status['verdict']['enabled'] is True
    assert status['verdict']['ready'] is False
    assert status['verdict']['positives'] == 0
