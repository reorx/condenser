"""Behavior tests for the X source, Phase 2: the reading surfaces.

Plan: kb/plans/2026-07-24-x-source-local-probe.md

Capacity decision (2026-07-24, after the Phase 1 measurement that For You
re-samples on every call — ~2400 tweets/day): **For You stays out of the
aggregate timeline**. It is only visible in the X-scoped views the user opens on
purpose (``?source=x``, ``?source=x&feed=foryou``). A followed account's feed
behaves like a TG channel and merges into everything.

Ingest goes through the real HTTP contract with real bird output (Phase 1
fixtures); ``x._now`` is the documented seam for controlling ``first_seen_at``.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from condenser import db, preview, x
from condenser.app import create_app
from condenser.items import parse_key, x_key

FIXTURES = Path(__file__).parent / 'fixtures' / 'x'

USER_HANDLE = 'novoreorx'
PHOTO_TWEET = 2080526422410752155  # NiallxYoung, Fri Jul 24 05:32:08
QUOTE_TWEET = 2080301572739695041  # recatm, quotes 2080267011654144075
QUOTED_TWEET = 2080267011654144075
RT_TWEET = 2080433142456864773  # 'RT @colebemis: ...'
ARTICLE_TWEET = 2080441004881215520
OLD_TWEET = 2059700843507503328  # RobinhoodApp, Wed May 27 — the For You "old resurface"
USER_NEWEST = 2080215574957928545  # novoreorx, Thu Jul 23 08:56:56
USER_OLDEST = 2079732304914862528  # novoreorx, Wed Jul 22 00:56:35


def home_fixture():
    return json.loads((FIXTURES / 'home_mixed.json').read_text())


def user_fixture():
    return json.loads((FIXTURES / 'user_tweets.json').read_text())


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _subscribe(client, channel_id):
    r = client.post('/api/sources/x/subscriptions', json={'channel_id': channel_id})
    assert r.status_code == 200, r.text
    return r.json()


def _ingest(client, monkeypatch, channel_id, tweets, at):
    """Push a batch with a pinned first_seen_at (the For You sort key)."""
    monkeypatch.setattr(x, '_now', lambda: at)
    r = client.post('/api/sources/x/ingest', json={'channel_id': channel_id, 'tweets': tweets})
    assert r.status_code == 200, r.text
    return r.json()


def _seed_both(client, monkeypatch):
    """The standard fixture world: For You + one followed account, both archived."""
    _subscribe(client, 'foryou')
    _subscribe(client, USER_HANDLE)
    _ingest(client, monkeypatch, 'foryou', home_fixture(), datetime(2026, 7, 24, 9, 0))
    _ingest(client, monkeypatch, USER_HANDLE, user_fixture(), datetime(2026, 7, 24, 9, 1))


def _timeline(client, **params):
    r = client.get('/api/timeline', params={'limit': 50, **params})
    assert r.status_code == 200, r.text
    return r.json()


def keys_of(items):
    return [i['key'] for i in items]


def x_items(page):
    return [i for i in page['items'] if i['source'] == 'x']


# --- item key ----------------------------------------------------------------


def test_x_item_key_roundtrip():
    k = parse_key('x:2080526422410752155')
    assert (k.source, k.ref1, k.ref2) == ('x', PHOTO_TWEET, 0)
    assert k.key == 'x:2080526422410752155'
    assert x_key(PHOTO_TWEET) == 'x:2080526422410752155'

    for bad in ('x:', 'x:abc', 'x:1:2'):
        with pytest.raises(ValueError):
            parse_key(bad)


# --- capacity decision: For You is opt-in --------------------------------------


def test_foryou_stays_out_of_the_aggregate_timeline(env, monkeypatch):
    """The measured firehose would drown TG/HN, so only followed accounts merge in."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        page = _timeline(client, all=1)
        feeds = {i['x']['feed'] for i in x_items(page)}
        assert feeds == {USER_HANDLE}
        assert x_key(USER_NEWEST) in keys_of(page['items'])
        assert x_key(PHOTO_TWEET) not in keys_of(page['items'])


def test_source_scoped_view_shows_both_feeds(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        page = _timeline(client, source='x')
        feeds = {i['x']['feed'] for i in page['items']}
        assert feeds == {'foryou', USER_HANDLE}


def test_feed_scoped_view_narrows_to_one_feed(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        foryou = _timeline(client, source='x', feed='foryou')
        assert {i['x']['feed'] for i in foryou['items']} == {'foryou'}
        assert x_key(PHOTO_TWEET) in keys_of(foryou['items'])

        # a handle feed, accepted in any of the ways the user might type it
        for typed in (USER_HANDLE, f'@{USER_HANDLE}', USER_HANDLE.upper()):
            mine = _timeline(client, source='x', feed=typed)
            assert {i['x']['feed'] for i in mine['items']} == {USER_HANDLE}, typed
            assert len(mine['items']) == 4

        assert _timeline(client, source='x', feed='nobody')['items'] == []


def test_a_foryou_only_subscription_leaves_the_aggregate_empty(env, monkeypatch):
    """Subscribing to For You alone must not put anything in the All view."""
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _ingest(client, monkeypatch, 'foryou', home_fixture(), datetime(2026, 7, 24, 9, 0))

        assert _timeline(client, all=1)['items'] == []
        assert client.get('/api/timeline/days').json() == []
        assert len(_timeline(client, source='x')['items']) == 8


def test_paused_feed_disappears_from_every_view(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        assert client.patch(f'/api/sources/x/subscriptions/{USER_HANDLE}', json={'enabled': False}).status_code == 200

        assert x_items(_timeline(client, all=1)) == []
        assert {i['x']['feed'] for i in _timeline(client, source='x')['items']} == {'foryou'}


# --- sort keys ----------------------------------------------------------------


def test_foryou_sorts_by_first_seen_and_a_followed_feed_by_created_at(env, monkeypatch):
    """For You uses first_seen_at (the algorithm resurfaces old tweets — created_at
    would splice them into timeline history); a followed account is a time series."""
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _subscribe(client, USER_HANDLE)
        entries = home_fixture()
        first, rest = entries[:1], entries[1:]
        # the May tweet arrives in the *second* push -> newest by first_seen_at
        _ingest(client, monkeypatch, 'foryou', rest, datetime(2026, 7, 24, 9, 0))
        _ingest(
            client,
            monkeypatch,
            'foryou',
            first + [e for e in entries if int(e['id']) == OLD_TWEET],
            datetime(2026, 7, 24, 10, 0),
        )
        _ingest(client, monkeypatch, USER_HANDLE, user_fixture(), datetime(2026, 7, 24, 9, 30))

        foryou = _timeline(client, source='x', feed='foryou')
        # OLD_TWEET was archived in the first push, so its first_seen_at is the older one
        by_key = {i['key']: i for i in foryou['items']}
        assert by_key[x_key(OLD_TWEET)]['datetime'].startswith('2026-07-24T09:00')
        assert by_key[x_key(QUOTE_TWEET)]['datetime'].startswith('2026-07-24T10:00')
        # the whole page is ordered by that timestamp, newest first
        stamps = [i['datetime'] for i in foryou['items']]
        assert stamps == sorted(stamps, reverse=True)

        mine = _timeline(client, source='x', feed=USER_HANDLE)
        assert keys_of(mine['items'])[0] == x_key(USER_NEWEST)
        assert keys_of(mine['items'])[-1] == x_key(USER_OLDEST)
        # created_at, not the push time
        assert mine['items'][0]['datetime'] == '2026-07-23T08:56:56Z'


def test_a_tweet_in_both_feeds_appears_once_as_the_followed_appearance(env, monkeypatch):
    """X's For You includes people you follow, so the same tweet lands in both feeds.
    The followed appearance wins: one card, sorted by created_at like its siblings."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        _ingest(client, monkeypatch, 'foryou', user_fixture(), datetime(2026, 7, 24, 11, 0))

        page = _timeline(client, source='x')
        assert keys_of(page['items']).count(x_key(USER_NEWEST)) == 1
        item = next(i for i in page['items'] if i['key'] == x_key(USER_NEWEST))
        assert item['x']['feed'] == USER_HANDLE
        assert item['datetime'] == '2026-07-23T08:56:56Z'


def test_deduplication_is_scoped_to_the_query(env, monkeypatch):
    """A cross-feed tweet must still appear when For You is the *only* feed queried —
    de-duplication ranks within the query's scope, not across the whole archive."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        _ingest(client, monkeypatch, 'foryou', user_fixture(), datetime(2026, 7, 24, 11, 0))

        foryou = _timeline(client, source='x', feed='foryou')
        assert x_key(USER_NEWEST) in keys_of(foryou['items'])
        # in its own view it is a For You unit, sorted by the sighting
        item = next(i for i in foryou['items'] if i['key'] == x_key(USER_NEWEST))
        assert item['x']['feed'] == 'foryou'
        assert item['datetime'] == '2026-07-24T11:00:00Z'
        # and the day counts agree with the page
        days = {d['date']: d['count'] for d in client.get('/api/timeline/days?source=x&feed=foryou').json()}
        assert sum(days.values()) == len(foryou['items'])


# --- envelope shape -----------------------------------------------------------


def test_x_envelope_carries_the_tweet_payload(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        page = _timeline(client, source='x', feed='foryou')
        by_key = {i['key']: i for i in page['items']}

        photo = by_key[x_key(PHOTO_TWEET)]
        assert photo['source'] == 'x' and photo['is_read'] is False and photo['is_saved'] is False
        t = photo['x']
        # snowflake ids exceed JS's safe integer range -> strings on the wire
        assert t['id'] == str(PHOTO_TWEET) and isinstance(t['id'], str)
        assert isinstance(t['author_id'], str)
        assert t['author_handle'] == 'NiallxYoung' and t['author_name']
        assert t['created_at'] == '2026-07-24T05:32:08Z'
        assert t['first_seen_at'] == '2026-07-24T09:00:00Z'
        assert t['metrics'] == {'reply_count': 16, 'retweet_count': 5, 'like_count': 82}
        assert t['media'][0]['type'] == 'photo' and (t['media'][0]['width'], t['media'][0]['height']) == (2048, 1350)
        assert t['feed'] == 'foryou' and t['feed_kind'] == 'home'
        assert t['verdict'] is None  # Phase 4

        quote = by_key[x_key(QUOTE_TWEET)]['x']['quote']
        assert quote['id'] == str(QUOTED_TWEET)
        assert quote['author_handle'] == 'MaxForAI' and quote['text']
        assert quote['media'][0]['type'] == 'photo'

        assert by_key[x_key(RT_TWEET)]['x']['rt_of_handle'] == 'colebemis'
        assert by_key[x_key(ARTICLE_TWEET)]['x']['article']['title'].startswith('Superrepos')


def test_quoted_tweets_are_not_timeline_items_of_their_own(env, monkeypatch):
    """Embedded quotes are archived rows without a feed appearance — they render
    inside the quoting card, never as a standalone item."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        assert db.get_x_tweet(QUOTED_TWEET) is not None
        assert x_key(QUOTED_TWEET) not in keys_of(_timeline(client, source='x')['items'])


# --- read / save / hide reuse the generic item plumbing -----------------------


def test_read_save_and_hide_work_on_x_keys(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(PHOTO_TWEET)

        assert client.post('/api/read', json={'keys': [key]}).status_code == 200
        assert client.post('/api/records', json={'key': key}).status_code == 200
        item = next(i for i in _timeline(client, source='x', feed='foryou')['items'] if i['key'] == key)
        assert item['is_read'] is True and item['is_saved'] is True

        unread = _timeline(client, source='x', feed='foryou', unread_only=True)
        assert key not in keys_of(unread['items'])

        assert client.post('/api/hidden', json={'key': key}).status_code == 200
        assert key not in keys_of(_timeline(client, source='x')['items'])
        assert client.delete(f'/api/hidden/{key}').status_code == 200
        assert key in keys_of(_timeline(client, source='x')['items'])


def test_saved_x_record_renders_from_its_snapshot(env, monkeypatch):
    """A saved record must survive the archive being cleared (source-decoupled)."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        key = x_key(QUOTE_TWEET)
        assert client.post('/api/records', json={'key': key}).status_code == 200

        db.XTweet.delete().execute()
        db.XFeedItem.delete().execute()

        records = client.get('/api/records').json()
        rec = next(r for r in records if r['key'] == key)
        assert rec['source'] == 'x' and rec['is_saved'] is True
        assert rec['x']['author_handle'] == 'recatm'
        assert rec['x']['quote']['id'] == str(QUOTED_TWEET)
        assert rec['x']['feed'] == 'foryou'


def test_saving_an_unknown_tweet_is_a_404(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)
        assert client.post('/api/records', json={'key': 'x:999'}).status_code == 404


def test_bulk_read_scoped_to_x_does_not_leak_to_other_sources(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        assert client.post('/api/read/bulk', json={'source': 'x'}).status_code == 200
        assert _timeline(client, source='x', unread_only=True)['items'] == []
        # For You is archived-but-hidden from the aggregate; marking it read is still
        # correct (the user asked for "all of X"), and nothing else was touched
        assert db.ReadItem.select().where(db.ReadItem.source == 'x').count() == 12
        assert db.ReadItem.select().where(db.ReadItem.source != 'x').count() == 0


def test_aggregate_bulk_read_leaves_foryou_alone(env, monkeypatch):
    """ "Mark all read" in the All view must not burn a feed that view never showed."""
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        assert client.post('/api/read/bulk', json={}).status_code == 200
        assert _timeline(client, all=1, unread_only=True)['items'] == []
        assert len(_timeline(client, source='x', feed='foryou', unread_only=True)['items']) == 8


def test_bulk_read_can_be_scoped_to_one_x_feed(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        assert client.post('/api/read/bulk', json={'source': 'x', 'feed': 'foryou'}).status_code == 200
        assert _timeline(client, source='x', feed='foryou', unread_only=True)['items'] == []
        assert len(_timeline(client, source='x', feed=USER_HANDLE, unread_only=True)['items']) == 4


# --- days + new-content polling ------------------------------------------------


def test_days_are_scoped_like_the_timeline(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        agg = {d['date']: d['count'] for d in client.get('/api/timeline/days').json()}
        assert agg == {'2026-07-23': 1, '2026-07-22': 3}  # the followed account only

        foryou = {d['date']: d['count'] for d in client.get('/api/timeline/days?source=x&feed=foryou').json()}
        assert foryou == {'2026-07-24': 8}  # every For You unit sits on its push day


def test_date_filter_uses_the_same_sort_day(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        page = _timeline(client, source='x', feed=USER_HANDLE, date='2026-07-22')
        assert len(page['items']) == 3


def test_new_content_poll_reports_x_arrivals(env, monkeypatch):
    with _client() as client:
        _login(client)
        _subscribe(client, USER_HANDLE)
        _ingest(client, monkeypatch, USER_HANDLE, user_fixture()[1:], datetime(2026, 7, 24, 9, 0))

        head = _timeline(client, all=1)['head_cursor']
        assert client.get('/api/timeline/new', params={'after': head}).json()['count'] == 0

        _ingest(client, monkeypatch, USER_HANDLE, user_fixture()[:1], datetime(2026, 7, 24, 10, 0))
        new = client.get('/api/timeline/new', params={'after': head}).json()
        assert new['count'] == 1 and new['items'][0]['key'] == x_key(USER_NEWEST)


# --- /api/sources listing ------------------------------------------------------


def test_sources_listing_gains_an_x_group_with_per_feed_unread(env, monkeypatch):
    with _client() as client:
        _login(client)
        _seed_both(client, monkeypatch)

        groups = {g['source']: g for g in client.get('/api/sources').json()}
        assert 'x' in groups
        by_id = {s['channel_id']: s for s in groups['x']['subscriptions']}
        assert by_id['foryou']['unread'] == 8
        assert by_id['foryou']['name'] == x.FORYOU_NAME
        assert by_id[USER_HANDLE]['unread'] == 4
        # the handle rides along as `username` so a client can label the row before
        # the first push teaches it the account's real display name
        assert by_id[USER_HANDLE]['username'] == USER_HANDLE
        assert by_id[USER_HANDLE]['config']['kind'] == 'user'

        client.post('/api/read', json={'keys': [x_key(USER_NEWEST)]})
        groups = {g['source']: g for g in client.get('/api/sources').json()}
        assert next(s for s in groups['x']['subscriptions'] if s['channel_id'] == USER_HANDLE)['unread'] == 3


# --- author avatars (bird gives no avatar URL) --------------------------------


def test_avatar_endpoint_proxies_unavatar(env, monkeypatch):
    calls = []

    async def fake_fetch_image(url):
        calls.append(url)
        return b'\x89PNG-bytes', 'image/png'

    monkeypatch.setattr(preview, 'fetch_image', fake_fetch_image)
    with _client() as client:
        _login(client)
        r = client.get(f'/api/x/avatar/@{USER_HANDLE.upper()}')

        assert r.status_code == 200 and r.content == b'\x89PNG-bytes'
        assert r.headers['content-type'] == 'image/png'
        assert calls == [f'https://unavatar.io/x/{USER_HANDLE}?fallback=false']


def test_avatar_endpoint_404s_so_clients_fall_back_to_a_letter(env, monkeypatch):
    async def boom(url):
        raise httpx.HTTPStatusError('404', request=httpx.Request('GET', url), response=httpx.Response(404))

    monkeypatch.setattr(preview, 'fetch_image', boom)
    with _client() as client:
        _login(client)
        assert client.get(f'/api/x/avatar/{USER_HANDLE}').status_code == 404
        assert client.get('/api/x/avatar/not a handle').status_code == 422


# --- probe capacity default ----------------------------------------------------


def test_home_fetch_count_defaults_to_the_reduced_capacity(env):
    """For You re-samples every call, so the default n is the capacity lever."""
    from condenser.config import get_settings

    assert get_settings().condenser_x_home_count == 20
    _ = os.environ  # (env fixture pins the rest of the config)
