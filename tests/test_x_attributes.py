"""Behavior tests for LLM attribute extraction (plan v2 step 2, channel C's fuel).

Plan: kb/plans/2026-07-27-x-verdict-style-channels.md

What this step ships is a **feature extractor, not a judge**. An LLM reads each
tweet and answers two questions — what is it about, and how does it talk — and
that is all it does. Nothing scores yet (step 3), nothing is hidden, no verdict
changes. The point of landing it early is that attributes for tweets you have
already labeled are the training data channel C will need, and they can only be
collected forwards.

Two properties dominate the tests, because this is the first component in the
project that **costs money per item**:

* it is inert without an API key, and it never runs before the cold-start gate —
  a fresh install must not spend a cent producing attributes for a verdict that
  cannot be made yet;
* every round is capped, counted and visible in ``/api/x/status``.

The rest is about not trusting the model: only flags from the closed taxonomy are
stored, malformed JSON is dropped and counted rather than raised, and a
taxonomy change re-extracts instead of silently mixing vocabularies.

The extractor is injected (the ``FakeExtractor`` below), so no test touches the
network — the same pattern as ``FakeEmbedder`` in test_x_verdict.py.
"""

import json
import os
from datetime import datetime, timedelta

from condenser import attributes as attrs, db, verdict as verdict_mod, x
from condenser.config import get_settings
from condenser.items import x_key
from telememo import db as tdb

NOW = datetime(2026, 7, 28, 12, 0)


class FakeExtractor:
    """Judge text -> attributes, by keyword. Records calls so a test can assert the
    API was *not* touched, which is the whole point of the gates."""

    def __init__(self, answers: dict | None = None, error: Exception | None = None):
        self.answers = answers or {}
        self.error = error
        self.calls: list[str] = []

    async def __call__(self, texts: list[str]) -> list[dict | None]:
        self.calls.extend(texts)
        if self.error is not None:
            raise self.error
        return [self._answer(text) for text in texts]

    def _answer(self, text: str) -> dict | None:
        for keyword, answer in self.answers.items():
            if keyword in text:
                return answer
        return {'topics': ['misc'], 'style_flags': []}


def setup_db(monkeypatch, **overrides) -> None:
    env = {
        'CONDENSER_EMBEDDING_API_KEY': 'test-key',
        'CONDENSER_ATTR_API_KEY': 'test-key',
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


def seed_world(monkeypatch, extractor=None, labeled: bool = True, **overrides):
    """Four labeled For You tweets (two down, two up, so the gate is open) plus one
    unlabeled arrival — labeled tweets are never judged, so without it there is no
    verdict to assert the attribute channel did not disturb."""
    setup_db(monkeypatch, **overrides)
    db.add_x_subscription('foryou', name=x.FORYOU_NAME, config={'kind': 'home'})
    ingest(
        'foryou',
        bird_entry(101, 'save this thread on crypto presales', 200),
        bird_entry(102, 'a thread you must know about airdrops', 190),
        bird_entry(201, 'rust borrow checker notes', 180),
        bird_entry(202, 'postgres query plans explained', 170),
        bird_entry(301, 'a fresh unlabeled arrival about rust', 5),
    )
    if labeled:
        for tweet_id in (101, 102):
            db.set_feedback(db.ItemKey(source='x', ref1=tweet_id), 'down')
        for tweet_id in (201, 202):
            db.set_feedback(db.ItemKey(source='x', ref1=tweet_id), 'up')
    manager = verdict_mod.VerdictManager(get_settings(), embed=_flat_embedder, extract=extractor or FakeExtractor())
    manager._now = lambda: NOW
    return manager


async def _flat_embedder(texts: list[str]) -> list[list[float]]:
    """Vectors are irrelevant here; every tweet lands on the same point."""
    dims = get_settings().condenser_embedding_dimensions
    return [[1.0] + [0.0] * (dims - 1) for _ in texts]


def stored(tweet_id: int):
    return db.XAttribute.get_or_none(db.XAttribute.tweet_id == tweet_id)


# --- spending nothing until it can be useful ------------------------------------


async def test_without_an_api_key_nothing_is_extracted(env, monkeypatch):
    extractor = FakeExtractor()
    manager = seed_world(monkeypatch, extractor, CONDENSER_ATTR_API_KEY='')

    result = await manager.run_once()

    assert result.attributed == 0
    assert extractor.calls == []
    assert not attrs.available(get_settings())


async def test_nothing_is_extracted_before_the_cold_start_gate_opens(env, monkeypatch):
    """The same rule embeddings follow: with too few labels there is no verdict to
    make, so there is nothing worth paying to describe."""
    extractor = FakeExtractor()
    manager = seed_world(monkeypatch, extractor, labeled=False)

    result = await manager.run_once()

    assert result.skipped_reason == 'cold_start'
    assert extractor.calls == []


async def test_the_switch_turns_it_off_without_touching_the_verdict(env, monkeypatch):
    extractor = FakeExtractor()
    manager = seed_world(monkeypatch, extractor, CONDENSER_ATTR_ENABLED='0')

    result = await manager.run_once()

    assert extractor.calls == []
    assert result.judged > 0  # the verdict is unaffected by the attribute channel


async def test_a_round_extracts_at_most_the_configured_batch(env, monkeypatch):
    """The spend bound. Without it, a first run against a full archive is an
    unbounded bill."""
    extractor = FakeExtractor()
    manager = seed_world(monkeypatch, extractor, CONDENSER_ATTR_BATCH='2')

    result = await manager.run_once()

    assert result.attributed == 2
    assert len(extractor.calls) == 2


# --- what gets described --------------------------------------------------------


async def test_labeled_tweets_are_described_first(env, monkeypatch):
    """Labeled tweets are the training set channel C will score against, so they are
    the ones worth paying for first — an unlabeled tweet only ever gets *judged*."""
    extractor = FakeExtractor()
    manager = seed_world(monkeypatch, extractor, CONDENSER_ATTR_BATCH='4')

    await manager.run_once()

    assert {stored(tweet_id) is not None for tweet_id in (101, 102, 201, 202)} == {True}


async def test_attributes_are_stored_with_the_taxonomy_they_were_read_under(env, monkeypatch):
    manager = seed_world(
        monkeypatch,
        FakeExtractor({'crypto': {'topics': ['crypto'], 'style_flags': ['promo_cta']}}),
    )

    await manager.run_once()

    row = stored(101)
    assert json.loads(row.topics) == ['crypto']
    assert json.loads(row.style_flags) == ['promo_cta']
    assert row.model == attrs.model_tag(get_settings())


async def test_a_tweet_already_described_is_not_paid_for_twice(env, monkeypatch):
    extractor = FakeExtractor()
    manager = seed_world(monkeypatch, extractor)
    await manager.run_once()
    described = len(extractor.calls)

    await manager.run_once()

    assert len(extractor.calls) == described


async def test_a_taxonomy_change_re_reads_instead_of_mixing_vocabularies(env, monkeypatch):
    """``model@taxonomy`` is the identity an attribute is comparable within, exactly
    like ``embedding.model_tag``: a flag read under v1 rules and one read under v2
    are not the same feature, so the answer is re-extraction, never a migration."""
    extractor = FakeExtractor()
    manager = seed_world(monkeypatch, extractor)
    await manager.run_once()
    described = len(extractor.calls)

    monkeypatch.setattr(attrs, 'TAXONOMY_VERSION', 'not-the-current-one')
    await manager.run_once()

    assert len(extractor.calls) > described


# --- not trusting the model -----------------------------------------------------


async def test_flags_outside_the_taxonomy_are_dropped(env, monkeypatch):
    """The taxonomy is closed on purpose: an open vocabulary drifts every time the
    model does, and a flag nothing can score is a flag that costs money for nothing."""
    manager = seed_world(
        monkeypatch,
        FakeExtractor({'crypto': {'topics': ['crypto'], 'style_flags': ['promo_cta', 'vibes', 'SHOUTING']}}),
    )

    await manager.run_once()

    assert json.loads(stored(101).style_flags) == ['promo_cta']


async def test_an_unreadable_answer_is_dropped_not_raised(env, monkeypatch):
    """One malformed answer must not cost the round. The tweet stays undescribed and
    comes back next time — the same posture the embedding path takes."""
    manager = seed_world(monkeypatch, FakeExtractor({'crypto': None}))

    result = await manager.run_once()

    assert stored(101) is None
    assert stored(201) is not None
    assert result.attributed == 4  # the other four still land


async def test_a_failing_provider_leaves_the_verdict_intact(env, monkeypatch):
    manager = seed_world(monkeypatch, FakeExtractor(error=RuntimeError('provider down')))

    result = await manager.run_once()

    assert result.attributed == 0
    assert result.judged > 0  # verdicts are written even when the attribute call dies


# --- storage + visibility -------------------------------------------------------


def test_schema_v10_adds_the_attribute_table_without_touching_data(env, monkeypatch):
    """A new table, so the upgrade is plain ``create_tables`` — no migration, and the
    same 'rebuildable cache' contract as x_embeddings: the text is still in x_tweets."""
    monkeypatch.setenv('CONDENSER_DB_PATH', os.environ['CONDENSER_DB_PATH'])
    get_settings.cache_clear()
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    db.add_x_subscription('foryou', name=x.FORYOU_NAME, config={'kind': 'home'})
    ingest('foryou', bird_entry(303, 'a tweet that predates attributes'))

    db.init_db(os.environ['CONDENSER_DB_PATH'])  # re-init, as a restart would

    assert db.get_meta('schema_version') == str(db.SCHEMA_VERSION)
    assert db.SCHEMA_VERSION >= 10
    assert db.XTweet.get_by_id(303).text == 'a tweet that predates attributes'
    assert stored(303) is None


async def test_the_status_line_says_whether_attributes_are_flowing(env, monkeypatch):
    """When channel C eventually says nothing, the first question is 'broken, or just
    not configured?' — the status answers it without reading logs."""
    manager = seed_world(monkeypatch)
    await manager.run_once()

    status = verdict_mod.status(get_settings(), manager)['attributes']

    assert status['enabled'] is True
    assert status['configured'] is True
    assert status['described'] == 5
    assert status['model'] == attrs.model_tag(get_settings())


# --- the extractor itself (no network) ------------------------------------------


def test_the_prompt_carries_the_whole_closed_taxonomy(env):
    """The model can only answer with flags it was shown; a taxonomy edit that does
    not reach the prompt is a taxonomy edit that silently does nothing."""
    prompt = attrs.system_prompt()

    assert all(flag in prompt for flag in attrs.STYLE_FLAGS)


def test_the_prompt_defines_every_flag_it_offers(env):
    """A bare flag name is a guess, and the guess was measured (2026-07-29): the
    taxonomy's meanings lived in Python comments and only the *names* were ever sent,
    so `ai_slop` reached the model as a naked token. It read that as machine-written
    spam; the reader uses it for the LLM explainer register. **0 of 3** `ai_slop`
    chips landed on a tweet the extractor had flagged `ai_slop`. A closed taxonomy is
    only closed if its definitions travel with it."""
    prompt = attrs.system_prompt()

    for flag in attrs.STYLE_FLAGS:
        assert f'- {flag}:' in prompt
        assert attrs.FLAG_GUIDE[flag] in prompt


def test_a_malformed_payload_reads_as_no_attributes(env):
    assert attrs.parse_answer('not json at all') is None
    assert attrs.parse_answer('{"topics": "not a list"}') == {'topics': [], 'style_flags': []}
    assert attrs.parse_answer('{"topics": ["a"], "style_flags": ["promo_cta", 9]}') == {
        'topics': ['a'],
        'style_flags': ['promo_cta'],
    }


def test_topics_are_capped_so_one_verbose_answer_cannot_bloat_the_row(env):
    payload = json.dumps({'topics': [f'topic{index}' for index in range(50)], 'style_flags': []})

    assert len(attrs.parse_answer(payload)['topics']) == attrs.MAX_TOPICS
