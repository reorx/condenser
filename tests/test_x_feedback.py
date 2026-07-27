"""Behavior tests for the X source, Phase 3: the feedback loop.

Plan: kb/plans/2026-07-24-x-source-local-probe.md

Phase 3 is deliberately dumb: thumb up/down writes ``item_feedback`` and nothing
else happens — no verdict, no hiding, no read side effects. The point is to start
accumulating the labels Phase 4's embedding classifier will train on, which is
why every X tweet is markable (For You *and* followed accounts) even though the
verdict will only ever be computed for For You.

The state has to survive back to the reader, so the envelope carries a
``feedback`` field on both reading surfaces: the timeline (provider join) and
saved records (which replay from a snapshot and therefore need a live join).

**Down reasons** (2026-07-26, schema v9) close the credit-assignment hole the
algorithm note (kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md) named:
a bare down labels the whole tweet, but the thing you disliked is usually one
attribute of it — its topic, its marketing voice, its AI-slop phrasing, its
author. The optional one-tap chip says which, so a future multi-channel model can
route the label to the right channel instead of averaging it into one vector.
Skipping the chip is free: the label degrades to exactly the bag-level signal it
was before.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import get_args

from fastapi.testclient import TestClient

from condenser import db, types, x
from condenser.app import create_app
from condenser.items import x_key

FIXTURES = Path(__file__).parent / 'fixtures' / 'x'

USER_HANDLE = 'novoreorx'
PHOTO_TWEET = 2080526422410752155  # in the For You fixture
USER_NEWEST = 2080215574957928545  # in the followed account's fixture


def home_fixture():
    return json.loads((FIXTURES / 'home_mixed.json').read_text())


def user_fixture():
    return json.loads((FIXTURES / 'user_tweets.json').read_text())


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _seed_both(client, monkeypatch):
    """For You + one followed account, both archived (mirrors the Phase 2 world)."""
    for channel_id in ('foryou', USER_HANDLE):
        assert client.post('/api/sources/x/subscriptions', json={'channel_id': channel_id}).status_code == 200
    monkeypatch.setattr(x, '_now', lambda: datetime(2026, 7, 24, 9, 0))
    assert (
        client.post('/api/sources/x/ingest', json={'channel_id': 'foryou', 'tweets': home_fixture()}).status_code == 200
    )
    assert (
        client.post('/api/sources/x/ingest', json={'channel_id': USER_HANDLE, 'tweets': user_fixture()}).status_code
        == 200
    )


def _feedback(client, key, verdict, reason=None):
    body = {'key': key, 'verdict': verdict}
    if reason is not None:
        body['reason'] = reason
    return client.post('/api/feedback', json=body)


def _x_timeline(client, **params):
    r = client.get('/api/timeline', params={'limit': 50, 'source': 'x', **params})
    assert r.status_code == 200, r.text
    return r.json()['items']


def _item(items, key):
    return next(i for i in items if i['key'] == key)


# --- writing feedback ---------------------------------------------------------


def test_up_feedback_shows_on_the_timeline_envelope(env, monkeypatch):
    """The card has to be able to highlight the side you picked, so the state round-trips."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)

        assert _item(_x_timeline(client, feed='foryou'), key)['feedback'] is None

        assert _feedback(client, key, 'up').status_code == 200
        assert _item(_x_timeline(client, feed='foryou'), key)['feedback'] == 'up'


def test_switching_sides_replaces_the_single_row(env, monkeypatch):
    """up -> down is a correction, not a second label: one row per item, latest wins."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)

        _feedback(client, key, 'up')
        _feedback(client, key, 'down')

        assert _item(_x_timeline(client, feed='foryou'), key)['feedback'] == 'down'
        assert db.ItemFeedback.select().where(db.ItemFeedback.ref1 == PHOTO_TWEET).count() == 1


def test_repeating_the_same_verdict_is_idempotent(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)

        assert _feedback(client, key, 'up').status_code == 200
        assert _feedback(client, key, 'up').status_code == 200

        assert db.ItemFeedback.select().count() == 1
        assert _item(_x_timeline(client, feed='foryou'), key)['feedback'] == 'up'


def test_feedback_can_be_undone(env, monkeypatch):
    """Clicking the highlighted thumb again clears the label (and drops it from training)."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)
        _feedback(client, key, 'down')

        assert client.delete(f'/api/feedback/{key}').status_code == 200

        assert _item(_x_timeline(client, feed='foryou'), key)['feedback'] is None
        assert db.ItemFeedback.select().count() == 0


def test_undoing_an_unlabeled_item_is_a_no_op(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        assert client.delete(f'/api/feedback/{x_key(PHOTO_TWEET)}').status_code == 200


def test_followed_account_tweets_are_markable_too(env, monkeypatch):
    """Decision: label everything (bigger training set); the verdict is what stays For You-only."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(USER_NEWEST)

        assert _feedback(client, key, 'up').status_code == 200

        assert _item(_x_timeline(client, feed=USER_HANDLE), key)['feedback'] == 'up'
        # and in the aggregate timeline, where a followed account does appear
        r = client.get('/api/timeline', params={'limit': 50, 'all': 1})
        assert _item(r.json()['items'], key)['feedback'] == 'up'


# --- what feedback must NOT do ------------------------------------------------


def test_feedback_does_not_hide_or_read_the_item(env, monkeypatch):
    """Phase 3 only labels. A down-voted tweet stays exactly where it was — hiding it
    is Phase 4's job, and only once the verdicts have earned trust."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)

        _feedback(client, key, 'down')

        item = _item(_x_timeline(client, feed='foryou'), key)
        assert item['is_read'] is False
        assert item['x']['verdict'] is None
        assert db.HiddenItem.select().count() == 0


# --- saved records ------------------------------------------------------------


def test_saved_records_carry_the_feedback_state(env, monkeypatch):
    """Saved X cards render from a snapshot, so their label comes from a live join —
    otherwise the same tweet would show an empty thumb in the Saved view."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)
        assert client.post('/api/records', json={'key': key}).status_code == 200
        _feedback(client, key, 'up')

        records = client.get('/api/records').json()

        assert _item(records, key)['feedback'] == 'up'


def test_a_saved_record_keeps_its_label_after_the_archive_is_gone(env, monkeypatch):
    """Feedback lives in its own table, so it outlives x_tweets exactly like the snapshot does."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)
        client.post('/api/records', json={'key': key})
        _feedback(client, key, 'down')

        db.XFeedItem.delete().execute()
        db.XTweet.delete().execute()

        assert _item(client.get('/api/records').json(), key)['feedback'] == 'down'


# --- down reasons (credit assignment, schema v9) -------------------------------


def test_a_down_without_a_reason_is_still_a_complete_label(env, monkeypatch):
    """The chip is skippable by design: no pick = the bag-level label we already had."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)

        assert _feedback(client, key, 'down').status_code == 200

        item = _item(_x_timeline(client, feed='foryou'), key)
        assert item['feedback'] == 'down'
        assert item['feedback_reason'] is None


def test_picking_a_chip_attaches_the_reason_to_the_same_row(env, monkeypatch):
    """The chip lands as a second call after the thumb, so it must update, not insert:
    the user made one judgement, and the row is that judgement."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)

        _feedback(client, key, 'down')
        assert _feedback(client, key, 'down', 'ai_slop').status_code == 200

        assert _item(_x_timeline(client, feed='foryou'), key)['feedback_reason'] == 'ai_slop'
        assert db.ItemFeedback.select().count() == 1


def test_every_chip_in_the_taxonomy_is_accepted(env, monkeypatch):
    """The chips map one-to-one onto the planned model channels — topic to the
    dense-kNN channel, promo/ai_slop/engagement_farming to the style channels,
    author to the author prior. Locking them here is what makes the stored labels
    re-routable later."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)

        for reason in ('topic', 'promo', 'ai_slop', 'engagement_farming', 'author'):
            assert _feedback(client, key, 'down', reason).status_code == 200
            assert _item(_x_timeline(client, feed='foryou'), key)['feedback_reason'] == reason


def test_engagement_farming_is_its_own_attribute_not_a_flavour_of_promo(env, monkeypatch):
    """Added 2026-07-27. The chip a reader reaches for on an influencer thread —
    the hook, the FOMO, the "save this 🔖", the payoff parked in the replies — is
    *not* the one they reach for on a plain advertisement, and the two must stay
    separable in the training set: `promo` is about selling something, this is
    about baiting interaction (X's own platform-manipulation vocabulary for it).
    They also feed different channels — a lexical/n-gram channel can learn bait
    phrasing outright, while `promo` is closer to intent — so a correction from
    one to the other has to land as a *replacement* on the same row, never as a
    second label the model would then see twice."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)

        _feedback(client, key, 'down', 'promo')
        assert _feedback(client, key, 'down', 'engagement_farming').status_code == 200

        assert _item(_x_timeline(client, feed='foryou'), key)['feedback_reason'] == 'engagement_farming'
        assert db.ItemFeedback.select().count() == 1


def test_switching_sides_drops_the_stale_reason(env, monkeypatch):
    """A POST states the whole label. Otherwise 'AI slop' would survive the correction
    to a thumbs-up and poison the training set with a positive labeled as slop."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)
        _feedback(client, key, 'down', 'ai_slop')

        _feedback(client, key, 'up')

        item = _item(_x_timeline(client, feed='foryou'), key)
        assert item['feedback'] == 'up'
        assert item['feedback_reason'] is None


def test_undo_takes_the_reason_with_it(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)
        _feedback(client, key, 'down', 'promo')

        client.delete(f'/api/feedback/{key}')

        item = _item(_x_timeline(client, feed='foryou'), key)
        assert item['feedback'] is None and item['feedback_reason'] is None


def test_a_reason_is_allowed_on_an_up_label(env, monkeypatch):
    """The column is verdict-agnostic even though only the down UI offers chips today —
    an up-side taxonomy later is a UI change, not a migration."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)

        assert _feedback(client, key, 'up', 'author').status_code == 200

        assert _item(_x_timeline(client, feed='foryou'), key)['feedback_reason'] == 'author'


def test_an_unknown_reason_is_rejected(env, monkeypatch):
    """A free-text reason would be unusable as a training feature, so the taxonomy is
    closed at the door like the verdict is."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        assert _feedback(client, x_key(PHOTO_TWEET), 'down', 'because-i-said-so').status_code == 422
        assert db.ItemFeedback.select().count() == 0


def test_the_request_schema_and_the_stored_taxonomy_cannot_drift():
    """The chip list is written twice — once as the door's validation (the pydantic
    Literal) and once as the vocabulary of what is in the column (FEEDBACK_REASONS).
    Adding a chip to only one of them fails in the worst possible direction: the
    endpoint accepts a value nothing else in the system knows how to route, and it
    is a stored label, so the damage is permanent. Pin them to each other."""
    annotation = types.FeedbackBody.model_fields['reason'].annotation  # Optional[Literal[...]]
    literal = next(arg for arg in get_args(annotation) if get_args(arg))

    assert set(get_args(literal)) == set(db.FEEDBACK_REASONS)


def test_saved_records_carry_the_reason_too(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)
        client.post('/api/records', json={'key': key})
        _feedback(client, key, 'down', 'topic')

        record = _item(client.get('/api/records').json(), key)

        assert record['feedback'] == 'down' and record['feedback_reason'] == 'topic'


def test_item_feedback_table_migrates_to_v9(env):
    """A pre-v9 item_feedback table gains the reason column in place, labels intact —
    the labels collected before the chips existed are the scarce ones."""
    path = os.environ['CONDENSER_DB_PATH']
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE item_feedback ('
        'source VARCHAR(255) NOT NULL, ref1 INTEGER NOT NULL, ref2 INTEGER NOT NULL, '
        'verdict VARCHAR(255) NOT NULL, created_at DATETIME NOT NULL, '
        'PRIMARY KEY (source, ref1, ref2))'
    )
    conn.execute(
        'INSERT INTO item_feedback (source, ref1, ref2, verdict, created_at) '
        "VALUES ('x', 42, 0, 'down', '2026-07-25 10:00:00')"
    )
    conn.commit()
    conn.close()

    db.init_db(path)

    assert db.get_feedback('x', 42) == ('down', None)
    assert db.SCHEMA_VERSION == 9
    # idempotent: init again on the migrated file
    db.init_db(path)
    assert db.get_feedback('x', 42) == ('down', None)


# --- contract ------------------------------------------------------------------


def test_bad_input_is_rejected(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        assert _feedback(client, 'x:notanid', 'up').status_code == 422
        assert _feedback(client, x_key(PHOTO_TWEET), 'meh').status_code == 422
        assert client.delete('/api/feedback/nope:1').status_code == 422


def test_feedback_requires_auth(env):
    with _client() as client:
        assert _feedback(client, x_key(PHOTO_TWEET), 'up').status_code == 401
        assert client.delete(f'/api/feedback/{x_key(PHOTO_TWEET)}').status_code == 401
