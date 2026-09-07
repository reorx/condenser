"""``GET /api/timeline/new/count`` — the count-only sibling of ``/timeline/new``
(plan 2026-09-07-ios-state-restore-new-content-pill.md §2).

The iOS "N 条新内容" pill only needs the number, so this endpoint runs each
source's ``fetch_new`` WHERE under a ``COUNT`` projection and never builds an
envelope. The contract pinned here: same number ``/timeline/new`` would report
(display units, not rows — an album is one), same ``unread_only`` mirroring, same
composite-cursor rules (a source without an anchor is skipped; garbage is 422).
"""

from fastapi.testclient import TestClient

from condenser import db, filters
from condenser.app import create_app
from tests.conftest import md, seed_channel, seed_messages
from tests.test_multi_source import _future_naive, seed_hn, subscribe_hn


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _count(client, head, **params):
    resp = client.get('/api/timeline/new/count', params={'after': head, **params})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {'count'}, 'count-only payload — no items'
    return body['count']


def test_count_is_zero_at_head_and_grows_with_new_messages(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1), md(1, 11, 2)])
        db.add_subscription(1)
        head = client.get('/api/timeline').json()['head_cursor']

        assert _count(client, head) == 0

        seed_messages([md(1, 12, 3), md(1, 13, 4)])
        filters.recompute_messages(1, [12, 13])
        assert _count(client, head) == 2
        # agrees with the full poll
        assert client.get(f'/api/timeline/new?after={head}').json()['count'] == 2


def test_count_telegram_album_is_one_unit(env):
    """Five photos of one album are one card on the timeline — and one in the count."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        head = client.get('/api/timeline').json()['head_cursor']

        seed_messages([md(1, 20 + i, 5, grouped_id=777, has_media=True, media_type='photo') for i in range(5)])
        seed_messages([md(1, 30, 6)])
        filters.recompute_messages(1, list(range(20, 25)) + [30])
        assert _count(client, head) == 2
        assert client.get(f'/api/timeline/new?after={head}').json()['count'] == 2


def test_count_respects_unread_only(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1), md(1, 11, 2), md(1, 12, 3)])
        db.add_subscription(1)
        client.post('/api/read', json={'keys': ['tg:1:12']})
        head = client.get('/api/timeline?unread_only=true').json()['head_cursor']

        # msg 12 is newer than the unread head but read → not new content
        assert _count(client, head, unread_only='true') == 0
        assert _count(client, head) == 1  # the all-items view does count it

        seed_messages([md(1, 13, 4)])
        filters.recompute_messages(1, [13])
        assert _count(client, head, unread_only='true') == 1


def test_count_sums_active_sources_and_honours_source_scope(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(100, 1)
        head = client.get('/api/timeline').json()['head_cursor']

        fs = _future_naive()
        for j in range(3):
            seed_hn(101 + j, 0, first_seen_at=fs, day=str(fs.date()))
        seed_messages([md(1, 11, 2)])
        filters.recompute_messages(1, [11])

        assert _count(client, head) == 4
        assert _count(client, head, source='hn') == 3
        assert _count(client, head, source='telegram') == 1
        assert _count(client, head, channel_id=1) == 1


def test_count_skips_source_without_anchor(env):
    """A source subscribed after the page was loaded has no anchor → not counted
    until the client refetches page 1 (query_new's rule)."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        head = client.get('/api/timeline').json()['head_cursor']  # telegram only

        subscribe_hn()
        fs = _future_naive()
        seed_hn(101, 0, first_seen_at=fs, day=str(fs.date()))
        assert _count(client, head) == 0


def test_count_rejects_bad_cursor(env):
    with _client() as client:
        _login(client)
        assert client.get('/api/timeline/new/count', params={'after': 'garbage'}).status_code == 422


def test_count_requires_auth(env):
    with _client() as client:
        assert client.get('/api/timeline/new/count', params={'after': 'x'}).status_code == 401
