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
"""

import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from condenser import db, x
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


def _feedback(client, key, verdict):
    return client.post('/api/feedback', json={'key': key, 'verdict': verdict})


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
