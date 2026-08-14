"""Hidden items: per-item "never show this again" markers (hidden_items table).

Hiding is server-side (POST /api/hidden {key} / DELETE /api/hidden/{key}) and
excluded from every timeline surface — pages, the new-content poll, day counts,
and unread counts — so every client (web + iOS) stops seeing the item without
client-side logic. Saved records are user assets and keep hidden items.
"""

from fastapi.testclient import TestClient

from condenser import db
from condenser.app import create_app
from tests.conftest import md, seed_channel, seed_messages
from tests.test_multi_source import seed_hn, subscribe_hn


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def keys_of(items):
    return [it['key'] for it in items]


def tg_unread(client, channel_id):
    for group in client.get('/api/sources').json():
        if group['source'] == 'telegram':
            for sub in group['subscriptions']:
                if sub['channel_id'] == channel_id:
                    return sub['unread']
    raise AssertionError('channel not in /api/sources')


def hn_unread(client):
    for group in client.get('/api/sources').json():
        if group['source'] == 'hn':
            return group['subscriptions'][0]['unread']
    raise AssertionError('hn not in /api/sources')


# --- telegram ----------------------------------------------------------------


def test_hide_tg_message_removes_it_everywhere(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1, text='keep'), md(1, 11, 2, text='hide me')])
        db.add_subscription(1)

        assert keys_of(client.get('/api/timeline').json()['items']) == ['tg:1:11', 'tg:1:10']
        assert tg_unread(client, 1) == 2
        assert client.get('/api/timeline/days').json() == [{'date': '2026-06-01', 'count': 2}]

        assert client.post('/api/hidden', json={'key': 'tg:1:11'}).json() == {'ok': True}

        assert keys_of(client.get('/api/timeline').json()['items']) == ['tg:1:10']
        assert keys_of(client.get('/api/timeline', params={'unread_only': True}).json()['items']) == ['tg:1:10']
        assert tg_unread(client, 1) == 1
        assert client.get('/api/timeline/days').json() == [{'date': '2026-06-01', 'count': 1}]


def test_hide_tg_album_hides_every_sibling(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages(
            [
                md(1, 10, 1, text='solo'),
                md(1, 12, 3, text=None, grouped_id=99, has_media=True, media_type='photo'),
                md(1, 13, 3, text='album caption', grouped_id=99, has_media=True, media_type='photo'),
            ]
        )
        db.add_subscription(1)

        assert keys_of(client.get('/api/timeline').json()['items']) == ['tg:1:12', 'tg:1:10']

        # hiding the album's unit key hides every raw sibling row, not just the anchor
        client.post('/api/hidden', json={'key': 'tg:1:12'})

        assert keys_of(client.get('/api/timeline').json()['items']) == ['tg:1:10']
        assert tg_unread(client, 1) == 1


def test_hidden_excluded_from_new_content_poll(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1, text='old')])
        db.add_subscription(1)
        head = client.get('/api/timeline').json()['head_cursor']

        seed_messages([md(1, 11, 5, text='new but hidden')])
        client.post('/api/hidden', json={'key': 'tg:1:11'})

        assert client.get('/api/timeline/new', params={'after': head}).json()['count'] == 0


def test_unhide_restores_the_item(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1, text='x')])
        db.add_subscription(1)

        client.post('/api/hidden', json={'key': 'tg:1:10'})
        assert client.get('/api/timeline').json()['items'] == []

        assert client.delete('/api/hidden/tg:1:10').json() == {'ok': True}
        assert keys_of(client.get('/api/timeline').json()['items']) == ['tg:1:10']
        assert tg_unread(client, 1) == 1


def test_unhide_restores_the_whole_album(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages(
            [
                md(1, 12, 3, text=None, grouped_id=99, has_media=True, media_type='photo'),
                md(1, 13, 3, text='album caption', grouped_id=99, has_media=True, media_type='photo'),
            ]
        )
        db.add_subscription(1)

        client.post('/api/hidden', json={'key': 'tg:1:12'})
        client.delete('/api/hidden/tg:1:12')

        items = client.get('/api/timeline').json()['items']
        assert keys_of(items) == ['tg:1:12']
        # both raw rows are visible again — the album unit is complete
        assert items[0]['telegram']['raw_message_ids'] == [12, 13]


# --- hacker news -------------------------------------------------------------


def test_hide_hn_story_removes_it_without_promoting_others(env):
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'top10'})
        # 10 admitted stories plus one the judge never let in (v14: admission is a
        # stamp, so "below the cut" is now "unstamped")
        for i in range(10):
            seed_hn(100 + i, minutes=i, score=100 - i)
        seed_hn(110, minutes=10, score=90, qualified_at=None, qualified_rank=None)

        assert len(client.get('/api/timeline').json()['items']) == 10
        assert hn_unread(client) == 10

        # hide the day's #1 story
        client.post('/api/hidden', json={'key': 'hn:100'})

        items = client.get('/api/timeline').json()['items']
        # 9 items left: the hidden story is gone and #11 was NOT promoted into the top10
        assert len(items) == 9
        assert 'hn:100' not in keys_of(items) and 'hn:110' not in keys_of(items)
        assert hn_unread(client) == 9
        assert client.get('/api/timeline/days').json() == [{'date': '2026-06-01', 'count': 9}]


# --- cross-cutting -----------------------------------------------------------


def test_hidden_item_stays_in_saved_records(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1, text='saved then hidden')])
        db.add_subscription(1)

        assert client.post('/api/records', json={'key': 'tg:1:10'}).status_code == 200
        client.post('/api/hidden', json={'key': 'tg:1:10'})

        assert client.get('/api/timeline').json()['items'] == []
        assert keys_of(client.get('/api/records').json()) == ['tg:1:10']


def test_hide_is_idempotent(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1, text='x')])
        db.add_subscription(1)

        assert client.post('/api/hidden', json={'key': 'tg:1:10'}).status_code == 200
        assert client.post('/api/hidden', json={'key': 'tg:1:10'}).status_code == 200
        assert client.get('/api/timeline').json()['items'] == []


def test_hide_invalid_key_is_422(env):
    with _client() as client:
        _login(client)
        assert client.post('/api/hidden', json={'key': 'rss:1'}).status_code == 422
        assert client.delete('/api/hidden/garbage').status_code == 422
