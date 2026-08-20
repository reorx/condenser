"""Behavior tests for ``GET /api/search`` (plan §5).

The endpoint's job is narrow and its edges are where the decisions live: it
returns the *same* item envelopes the timeline does (so the frontend needs no new
type), it reads the **archive** rather than the reading list (a paused channel and
a For You tweet the aggregate keeps out are both findable), and it excludes
exactly the two things that are judgements about an item rather than about a view
— hidden items and keyword-filtered ones.
"""

from datetime import timedelta

from fastapi.testclient import TestClient

from condenser import db, search, x
from condenser.app import create_app
from tests.conftest import BASE, md, seed_channel, seed_messages


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _search(client, q, **params):
    r = client.get('/api/search', params={'q': q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _keys(payload):
    return [it['key'] for it in payload['items']]


def _seed_tg(channel_id, message_id, text, minutes, title='Chan', **extra):
    seed_channel(channel_id, title)
    seed_messages([md(channel_id, message_id, minutes, text=text, **extra)])
    search.index_item('telegram', channel_id, message_id, text, BASE + timedelta(minutes=minutes))


def _seed_hn(story_id, title, minutes):
    stamp = (BASE + timedelta(minutes=minutes)).replace(tzinfo=None)
    db.insert_hn_story(id=story_id, title=title, url='https://ex.com/x', first_seen_at=stamp, day=str(stamp.date()))
    search.index_hn_story({'id': story_id, 'title': title, 'text': None, 'first_seen_at': stamp})


def _seed_x(tweet_id, text, feed='foryou', minutes=0):
    entry = {
        'id': str(tweet_id),
        'text': text,
        'createdAt': (BASE + timedelta(minutes=minutes)).strftime('%a %b %d %H:%M:%S +0000 %Y'),
        'authorId': '1',
        'author': {'username': 'someone', 'name': 'Some One'},
    }
    db.add_x_subscription(feed, name=feed, config={'kind': 'home' if feed == 'foryou' else 'user'})
    x.ingest_tweets(feed, [entry])


# --- shape --------------------------------------------------------------------


def test_search_returns_item_envelopes_from_every_source(env):
    """One page, three sources, the timeline's own envelope shape — which is what
    lets the frontend render results with the cards it already has."""
    with _client() as client:
        _login(client)
        _seed_tg(100, 1, '关于模型的文章', 0)
        _seed_hn(500, '模型 benchmarks', 10)
        _seed_x(9001, '推特上的模型讨论', minutes=20)

        payload = _search(client, '模型')
        assert payload['total'] == 3 and payload['has_more'] is False
        assert _keys(payload) == ['x:9001', 'hn:500', 'tg:100:1']
        by_source = {it['source']: it for it in payload['items']}
        assert by_source['telegram']['telegram']['text'] == '关于模型的文章'
        assert by_source['hn']['hn']['title'] == '模型 benchmarks'
        assert by_source['x']['x']['text'] == '推特上的模型讨论'
        assert all({'key', 'datetime', 'is_read', 'is_saved'} <= set(it) for it in payload['items'])


def test_search_returns_an_album_once_with_its_media(env):
    """An album is one index row under its anchor, so it needs no query-time
    de-duplication — and the envelope still carries every sibling's media."""
    with _client() as client:
        _login(client)
        seed_channel(100, 'Chan')
        seed_messages(
            [
                md(100, 10, 0, text=None, grouped_id=777, has_media=True, media_type='photo'),
                md(100, 11, 0, text='相册的模型说明', grouped_id=777, has_media=True, media_type='photo'),
            ]
        )
        search.rebuild()

        payload = _search(client, '模型')
        assert _keys(payload) == ['tg:100:10'] and payload['total'] == 1
        assert len(payload['items'][0]['telegram']['media_items']) == 2


# --- filters ------------------------------------------------------------------


def test_source_and_subscription_filters_narrow_the_scope(env):
    with _client() as client:
        _login(client)
        _seed_tg(100, 1, '模型 A', 0, title='A')
        _seed_tg(200, 1, '模型 B', 1, title='B')
        _seed_hn(500, '模型 story', 2)
        _seed_x(9001, '模型 tweet', minutes=3)

        assert _keys(_search(client, '模型', source='telegram')) == ['tg:200:1', 'tg:100:1']
        assert _keys(_search(client, '模型', source='hn')) == ['hn:500']
        assert _keys(_search(client, '模型', channel_id=100)) == ['tg:100:1']
        # a feed key only means something inside its own source, so it comes with one
        assert _keys(_search(client, '模型', source='x', feed='foryou')) == ['x:9001']
        assert _keys(_search(client, '模型', source='x', feed='@ForYou')) == ['x:9001']  # X keys normalize


def test_status_filter_selects_unread_or_saved(env):
    with _client() as client:
        _login(client)
        _seed_tg(100, 1, '模型 one', 0)
        _seed_tg(100, 2, '模型 two', 1)
        client.post('/api/read', json={'keys': ['tg:100:1']})
        client.post('/api/records', json={'key': 'tg:100:1'})

        assert _keys(_search(client, '模型')) == ['tg:100:2', 'tg:100:1']
        assert _keys(_search(client, '模型', status='unread')) == ['tg:100:2']
        assert _keys(_search(client, '模型', status='saved')) == ['tg:100:1']


def test_search_reads_the_archive_not_the_reading_list(env):
    """Two things the timeline hides for capacity reasons stay searchable: a
    paused subscription, and a For You tweet the aggregate mode keeps out. Search
    is where you go to find something you know exists."""
    with _client() as client:
        _login(client)
        _seed_tg(100, 1, '模型 paused', 0)
        db.add_subscription(100)
        db.set_subscription_enabled(100, False)
        _seed_x(9001, '模型 firehose', minutes=1)  # For You defaults to aggregate='none'

        assert client.get('/api/timeline').json()['items'] == []
        assert _keys(_search(client, '模型')) == ['x:9001', 'tg:100:1']


def test_hidden_and_keyword_filtered_items_never_appear(env):
    """The two exclusions that are judgements about the *item*: hidden means never
    again, and a keyword rule is a standing instruction about the very text a
    search matches on."""
    with _client() as client:
        _login(client)
        _seed_tg(100, 1, '模型 hidden', 0)
        _seed_tg(100, 2, '模型 filtered', 1)
        _seed_tg(100, 3, '模型 visible', 2)
        client.post('/api/hidden', json={'key': 'tg:100:1'})
        client.post('/api/filters', json={'pattern': 'filtered', 'channel_id': 100})

        payload = _search(client, '模型')
        assert _keys(payload) == ['tg:100:3'] and payload['total'] == 1
        # undoing the hide brings it straight back — no re-index needed
        client.delete('/api/hidden/tg:100:1')
        assert _keys(_search(client, '模型')) == ['tg:100:3', 'tg:100:1']


def test_a_filtered_album_caption_is_not_searchable_by_its_banned_keyword(env):
    """`is_filtered` is computed per row, and an album's caption usually lives on a
    sibling rather than on the anchor the index is keyed by. Testing only the anchor
    let the whole album through — and the card then rendered the very caption the
    rule exists to suppress, answering a query for the banned word itself."""
    with _client() as client:
        _login(client)
        seed_channel(100, 'Chan')
        seed_messages(
            [
                md(100, 10, 0, text=None, grouped_id=777),
                md(100, 11, 0, text='相册的模型 filtered', grouped_id=777),
            ]
        )
        search.rebuild()
        assert _search(client, '模型')['total'] == 1

        client.post('/api/filters', json={'pattern': 'filtered', 'channel_id': 100})
        assert _search(client, '模型')['total'] == 0
        assert _search(client, 'filtered')['total'] == 0


def test_hiding_an_album_removes_it_from_search(env):
    """Hide markers are album-expanded, so the anchor row carries one too."""
    with _client() as client:
        _login(client)
        seed_channel(100, 'Chan')
        seed_messages([md(100, 10, 0, text=None, grouped_id=777), md(100, 11, 0, text='相册的模型', grouped_id=777)])
        search.rebuild()
        client.post('/api/hidden', json={'key': 'tg:100:10'})
        assert _search(client, '模型')['total'] == 0


# --- sort + paging ------------------------------------------------------------


def test_sort_switches_between_time_and_relevance(env):
    with _client() as client:
        _login(client)
        _seed_hn(500, 'rust', 0)
        _seed_hn(501, 'a long headline about many things including rust and more', 10)

        assert _keys(_search(client, 'rust', sort='recent')) == ['hn:501', 'hn:500']
        assert _keys(_search(client, 'rust', sort='relevance')) == ['hn:500', 'hn:501']


def test_pagination_reports_total_and_has_more(env):
    with _client() as client:
        _login(client)
        for i in range(1, 6):
            _seed_hn(500 + i, f'rust {i}', i)

        first = _search(client, 'rust', limit=2)
        assert first['total'] == 5 and first['has_more'] is True and len(first['items']) == 2
        last = _search(client, 'rust', limit=2, offset=4)
        assert last['total'] == 5 and last['has_more'] is False and len(last['items']) == 1


# --- validation ---------------------------------------------------------------


def test_a_query_with_no_searchable_token_is_422(env):
    with _client() as client:
        _login(client)
        for junk in ('', '   ', '!!!', '🧵'):
            assert client.get('/api/search', params={'q': junk}).status_code == 422


def test_unknown_source_status_or_sort_is_422(env):
    with _client() as client:
        _login(client)
        assert client.get('/api/search', params={'q': 'x', 'source': 'mastodon'}).status_code == 422
        assert client.get('/api/search', params={'q': 'x', 'status': 'starred'}).status_code == 422
        assert client.get('/api/search', params={'q': 'x', 'sort': 'random'}).status_code == 422


def test_a_self_contradicting_scope_is_422_not_an_empty_page(env):
    """`source=hn&channel_id=5` can never match anything. Answering it with an
    empty 200 makes "you asked for something impossible" look like "nothing
    matched" — the same reason an unsearchable query is a 422."""
    with _client() as client:
        _login(client)
        assert client.get('/api/search', params={'q': 'x', 'source': 'hn', 'channel_id': 5}).status_code == 422
        assert client.get('/api/search', params={'q': 'x', 'source': 'telegram', 'feed': 'foryou'}).status_code == 422
        # the consistent pairs still work
        assert client.get('/api/search', params={'q': 'x', 'source': 'telegram', 'channel_id': 5}).status_code == 200
        assert client.get('/api/search', params={'q': 'x', 'channel_id': 5}).status_code == 200
        assert client.get('/api/search', params={'q': 'x', 'source': 'x', 'feed': 'foryou'}).status_code == 200


def test_search_requires_auth(env):
    with _client() as client:
        assert client.get('/api/search', params={'q': 'rust'}).status_code == 401


def test_search_is_503_when_the_engine_is_unavailable(env, monkeypatch):
    """A SQLite build without FTS5 costs the app search and nothing else — the
    ``vectors.py`` degradation, said out loud instead of returning zero hits."""
    with _client() as client:
        _login(client)
        monkeypatch.setattr(search, 'available', lambda: False)
        r = client.get('/api/search', params={'q': 'rust'})
        assert r.status_code == 503 and 'search' in r.json()['detail'].lower()


def test_search_survives_a_stale_index_row(env):
    """A document whose item is gone renders as one fewer result, not a 500."""
    with _client() as client:
        _login(client)
        _seed_tg(100, 1, '模型 gone', 0)
        db.tdb.db.execute_sql('DELETE FROM messages WHERE channel_id = 100')
        payload = _search(client, '模型')
        assert payload['items'] == [] and payload['total'] == 1
