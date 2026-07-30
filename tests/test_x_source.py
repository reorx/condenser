"""Behavior tests for the X (Twitter) source, Phase 1: probe config, ingest, archive.

Plan: kb/plans/2026-07-24-x-source-local-probe.md

The probe is the only thing that talks to X (bird CLI on the user's machine), so
the server side is exercised purely through its HTTP contract, with real bird
output as fixtures (tests/fixtures/x/, curated from tmp/2026-07-24-bird-samples
by tmp/make_x_fixtures.py).
"""

import copy
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from condenser import db, x
from condenser.app import create_app

FIXTURES = Path(__file__).parent / 'fixtures' / 'x'

# Ids of the curated home_mixed.json fixture, by shape.
QUOTE_TWEET = 2080301572739695041  # quotes 2080267011654144075 (@MaxForAI)
QUOTED_TWEET = 2080267011654144075
PHOTO_TWEET = 2080526422410752155
ARTICLE_TWEET = 2080441004881215520
RT_TWEET = 2080433142456864773  # 'RT @colebemis: ...'
REPLY_TWEET = 2080496148192919869  # inReplyToStatusId 2080481666305593363

USER_HANDLE = 'novoreorx'
USER_ID = 132736859


def home_fixture():
    return json.loads((FIXTURES / 'home_mixed.json').read_text())


def user_fixture():
    return json.loads((FIXTURES / 'user_tweets.json').read_text())


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _subscribe(client, channel_id, **body):
    return client.post('/api/sources/x/subscriptions', json={'channel_id': channel_id, **body})


def _ingest(client, channel_id, tweets):
    return client.post('/api/sources/x/ingest', json={'channel_id': channel_id, 'tweets': tweets})


def _init():
    db.init_db(os.environ['CONDENSER_DB_PATH'])


# --- schema ------------------------------------------------------------------


def test_fresh_db_creates_the_x_tables(env):
    _init()
    assert db.get_meta('schema_version') == str(db.SCHEMA_VERSION)
    # new tables exist; no data migration is involved
    tables = {r[0] for r in db.tdb.db.execute_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {'x_tweets', 'x_feed_items', 'item_feedback'} <= tables


def test_existing_v6_database_gains_the_new_tables(env):
    """v7 is additive — an upgrade is plain create_tables, no data touched."""
    path = os.environ['CONDENSER_DB_PATH']
    _init()
    db.set_meta('schema_version', '6')
    db.HNStory.create(id=1, title='kept', first_seen_at=datetime(2026, 7, 1, 10, 0), day='2026-07-01')
    for table in ('x_tweets', 'x_feed_items', 'item_feedback'):
        db.tdb.db.execute_sql(f'DROP TABLE {table}')
    db.close_db()

    db.init_db(path)

    assert db.get_meta('schema_version') == str(db.SCHEMA_VERSION)
    assert db.get_hn_story(1).title == 'kept'
    assert db.XTweet.select().count() == 0


# --- parsing (bird output is not a stable contract: tolerate + keep raw) ------


def test_parse_tweet_reads_real_bird_output(env):
    entry = next(e for e in home_fixture() if int(e['id']) == PHOTO_TWEET)
    t = x.parse_tweet(entry)

    assert t.id == PHOTO_TWEET  # string ids in JSON -> int64 in storage
    assert t.author_id == 1511658122149961730
    assert t.author_handle == 'NiallxYoung'
    assert t.author_name
    # legacy 'Thu Jul 24 05:32:08 +0000 2026' format -> naive UTC
    assert t.created_at == datetime(2026, 7, 24, 5, 32, 8)
    assert t.metrics == {'reply_count': 16, 'retweet_count': 5, 'like_count': 82}
    assert t.media and t.media[0]['type'] == 'photo'
    assert (t.media[0]['width'], t.media[0]['height']) == (2048, 1350)
    assert t.quote_of is None and t.rt_of_handle is None and t.reply_to_id is None
    assert t.raw == entry  # raw kept verbatim for a re-parse after a format drift


def test_parse_tweet_extracts_quote_reply_rt_and_article(env):
    by_id = {int(e['id']): x.parse_tweet(e) for e in home_fixture()}

    assert by_id[QUOTE_TWEET].quote_of == QUOTED_TWEET
    assert by_id[REPLY_TWEET].reply_to_id == 2080481666305593363
    # bird flattens retweets to an 'RT @orig: ...' text prefix — no structured field
    assert by_id[RT_TWEET].rt_of_handle == 'colebemis'
    assert by_id[ARTICLE_TWEET].article['title'].startswith('Superrepos')
    assert by_id[ARTICLE_TWEET].article['previewText']


def test_parse_tweet_tolerates_missing_fields(env):
    t = x.parse_tweet({'id': '123', 'text': 'bare'})
    assert t.id == 123 and t.text == 'bare'
    assert t.author_handle is None and t.created_at is None and t.media is None
    assert t.metrics == {'reply_count': 0, 'retweet_count': 0, 'like_count': 0}


def test_parse_tweet_rejects_entries_without_a_usable_id(env):
    for bad in ({'text': 'no id'}, {'id': 'not-a-number', 'text': 'x'}, {'id': None}):
        try:
            x.parse_tweet(bad)
        except x.XParseError:
            continue
        raise AssertionError(f'expected XParseError for {bad!r}')


# --- probe config (subscription-driven, like HN sampling) --------------------


def test_probe_config_is_empty_without_enabled_subscriptions(env):
    with _client() as client:
        _login(client)
        assert client.get('/api/sources/x/probe-config').json() == {'feeds': [], 'sync_following': False}

        _subscribe(client, 'foryou')
        client.patch('/api/sources/x/subscriptions/foryou', json={'enabled': False})
        assert client.get('/api/sources/x/probe-config').json() == {'feeds': [], 'sync_following': False}


def test_probe_config_lists_enabled_feeds(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _subscribe(client, f'@{USER_HANDLE}')

        feeds = client.get('/api/sources/x/probe-config').json()['feeds']
        by_id = {f['channel_id']: f for f in feeds}
        # For You re-samples every call, so the default n is the capacity lever (Phase 2)
        assert by_id['foryou'] == {'channel_id': 'foryou', 'kind': 'home', 'handle': None, 'n': 20}
        assert by_id[USER_HANDLE] == {
            'channel_id': USER_HANDLE,
            'kind': 'user',
            'handle': USER_HANDLE,
            'n': 10,
        }


def test_probe_config_honours_per_feed_count_override(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou', n=20)
        assert client.get('/api/sources/x/probe-config').json()['feeds'][0]['n'] == 20

        client.patch('/api/sources/x/subscriptions/foryou', json={'config': {'n': 80}})
        assert client.get('/api/sources/x/probe-config').json()['feeds'][0]['n'] == 80


# --- subscriptions -----------------------------------------------------------


def test_subscribe_normalizes_handles_and_rejects_junk(env):
    with _client() as client:
        _login(client)
        r = _subscribe(client, ' @NovoReorx ')
        assert r.status_code == 200
        body = r.json()
        assert body['channel_id'] == USER_HANDLE  # '@' stripped, lowercased
        assert body['kind'] == 'user' and body['enabled'] is True

        # same handle in another casing is the same subscription, not a second row
        assert _subscribe(client, 'NOVOREORX').status_code == 200
        assert len(client.get('/api/sources/x/subscriptions').json()) == 1

        assert _subscribe(client, 'not a handle!').status_code == 422
        assert _subscribe(client, '').status_code == 422


def test_resubscribe_reenables_a_paused_feed(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        client.patch('/api/sources/x/subscriptions/foryou', json={'enabled': False})
        assert _subscribe(client, 'foryou').json()['enabled'] is True
        assert client.get('/api/sources/x/probe-config').json()['feeds'][0]['channel_id'] == 'foryou'


def test_patch_and_delete_unknown_feed_404(env):
    with _client() as client:
        _login(client)
        assert client.patch('/api/sources/x/subscriptions/foryou', json={'enabled': True}).status_code == 404
        assert client.delete('/api/sources/x/subscriptions/foryou').status_code == 404


def test_unsubscribe_keeps_the_archive(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _ingest(client, 'foryou', home_fixture())

        assert client.delete('/api/sources/x/subscriptions/foryou').status_code == 200
        assert client.get('/api/sources/x/probe-config').json() == {'feeds': [], 'sync_following': False}
        # tweets + feed rows survive (same semantics as a TG/HN unsubscribe)
        assert db.XTweet.select().count() > 0
        assert db.XFeedItem.select().where(db.XFeedItem.channel_id == 'foryou').count() > 0


def test_source_disabled_by_config_refuses_subscribe_and_ingest(env, monkeypatch):
    monkeypatch.setenv('CONDENSER_X_ENABLED', 'false')
    from condenser.config import get_settings

    get_settings.cache_clear()
    with _client() as client:
        _login(client)
        assert _subscribe(client, 'foryou').status_code == 503
        assert _ingest(client, 'foryou', home_fixture()).status_code == 503
        assert client.get('/api/sources/x/probe-config').json() == {'feeds': [], 'sync_following': False}


# --- ingest ------------------------------------------------------------------


def test_ingest_stores_tweets_and_feed_items(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        r = _ingest(client, 'foryou', home_fixture())
        assert r.status_code == 200
        body = r.json()
        assert body['received'] == 8 and body['parse_errors'] == 0
        assert body['new_items'] == 8

        t = db.get_x_tweet(PHOTO_TWEET)
        assert t.author_handle == 'NiallxYoung'
        assert t.created_at == datetime(2026, 7, 24, 5, 32, 8)
        assert json.loads(t.metrics)['like_count'] == 82
        assert json.loads(t.media)[0]['type'] == 'photo'
        assert json.loads(t.raw)['id'] == str(PHOTO_TWEET)  # raw留底

        item = db.XFeedItem.get((db.XFeedItem.channel_id == 'foryou') & (db.XFeedItem.tweet_id == PHOTO_TWEET))
        assert item.first_seen_at is not None and item.verdict is None


def test_ingest_is_idempotent_and_keeps_first_seen_at(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        first = _ingest(client, 'foryou', home_fixture()).json()
        seen_at = db.XFeedItem.get(
            (db.XFeedItem.channel_id == 'foryou') & (db.XFeedItem.tweet_id == PHOTO_TWEET)
        ).first_seen_at

        again = _ingest(client, 'foryou', home_fixture()).json()
        assert again['received'] == first['received']
        assert again['new_items'] == 0 and again['new_tweets'] == 0
        assert db.XFeedItem.select().where(db.XFeedItem.channel_id == 'foryou').count() == first['new_items']
        # first_seen_at is the timeline sort key for For You — a re-push must not reset it
        assert (
            db.XFeedItem.get(
                (db.XFeedItem.channel_id == 'foryou') & (db.XFeedItem.tweet_id == PHOTO_TWEET)
            ).first_seen_at
            == seen_at
        )


def test_ingest_refreshes_metrics_of_a_known_tweet(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _ingest(client, 'foryou', home_fixture())

        hotter = copy.deepcopy(home_fixture())
        for e in hotter:
            if int(e['id']) == PHOTO_TWEET:
                e['likeCount'] = 999
        _ingest(client, 'foryou', hotter)

        assert json.loads(db.get_x_tweet(PHOTO_TWEET).metrics)['like_count'] == 999


def test_ingest_stores_the_quoted_tweet_as_its_own_row(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        r = _ingest(client, 'foryou', home_fixture()).json()

        quoted = db.get_x_tweet(QUOTED_TWEET)
        assert quoted is not None and quoted.author_handle == 'MaxForAI'
        assert json.loads(quoted.media)[0]['type'] == 'photo'
        # the quoted tweet is a self-referential archive row, not a feed entry
        assert db.get_x_tweet(QUOTE_TWEET).quote_of == QUOTED_TWEET
        assert (
            db.XFeedItem.select()
            .where((db.XFeedItem.channel_id == 'foryou') & (db.XFeedItem.tweet_id == QUOTED_TWEET))
            .count()
            == 0
        )
        assert r['new_tweets'] > r['new_items']  # quoted rows are extra tweets


def test_embedded_quote_does_not_clobber_a_richer_row(env):
    """A tweet stored from a full feed entry must not be downgraded when it later
    shows up as someone else's (depth-limited) embedded quote."""
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _ingest(client, 'foryou', home_fixture())
        assert db.get_x_tweet(QUOTE_TWEET).quote_of == QUOTED_TWEET

        quoting = copy.deepcopy(next(e for e in home_fixture() if int(e['id']) == PHOTO_TWEET))
        quoting['id'] = '2080999999999999999'
        quoting['quotedTweet'] = {
            'id': str(QUOTE_TWEET),
            'text': 'truncated embedded copy',
            'author': {'username': 'recatm', 'name': '西乔 XiQiao'},
            'authorId': '18824096',
        }
        _ingest(client, 'foryou', [quoting])

        kept = db.get_x_tweet(QUOTE_TWEET)
        assert kept.quote_of == QUOTED_TWEET  # not nulled by the shallower payload
        assert kept.text != 'truncated embedded copy'


def test_ingest_survives_malformed_entries(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        batch = home_fixture()
        batch.insert(0, {'garbage': True})
        batch.insert(3, {'id': 'not-a-number', 'text': 'broken'})

        r = _ingest(client, 'foryou', batch).json()
        assert r['received'] == 10 and r['parse_errors'] == 2
        assert r['new_items'] == 8  # the good entries still land
        assert db.get_x_tweet(PHOTO_TWEET) is not None

        status = client.get('/api/x/status').json()
        assert status['parse_errors'] == 2


def test_ingest_keeps_a_tweet_whose_timestamp_cannot_be_parsed(env):
    """Format drift in one field must not lose the tweet — raw is kept for a re-parse."""
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        entry = copy.deepcopy(next(e for e in home_fixture() if int(e['id']) == PHOTO_TWEET))
        entry['createdAt'] = '2026-07-24T05:32:08Z'  # not the legacy format

        r = _ingest(client, 'foryou', [entry]).json()
        assert r['new_items'] == 1 and r['parse_errors'] == 1
        stored = db.get_x_tweet(PHOTO_TWEET)
        assert stored.created_at is None
        assert json.loads(stored.raw)['createdAt'] == '2026-07-24T05:32:08Z'


def test_ingest_into_unknown_or_paused_feed_404(env):
    with _client() as client:
        _login(client)
        assert _ingest(client, 'foryou', home_fixture()).status_code == 404

        _subscribe(client, 'foryou')
        client.patch('/api/sources/x/subscriptions/foryou', json={'enabled': False})
        assert _ingest(client, 'foryou', home_fixture()).status_code == 404


def test_ingest_learns_user_id_and_display_name_for_a_followed_account(env):
    with _client() as client:
        _login(client)
        _subscribe(client, USER_HANDLE)
        before = client.get('/api/sources/x/subscriptions').json()[0]
        # nothing is invented before the first push: no numeric id, no display name
        assert before['user_id'] is None and before['name'] is None

        _ingest(client, USER_HANDLE, user_fixture())

        sub = client.get('/api/sources/x/subscriptions').json()[0]
        # the numeric id is what survives a handle rename — learned from the first push
        assert sub['user_id'] == str(USER_ID)
        assert sub['name'] == user_fixture()[0]['author']['name']


def test_same_tweet_in_two_feeds_shares_one_tweet_row(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _subscribe(client, USER_HANDLE)
        entry = next(e for e in home_fixture() if int(e['id']) == PHOTO_TWEET)

        _ingest(client, 'foryou', [entry])
        _ingest(client, USER_HANDLE, [entry])

        assert db.XTweet.select().where(db.XTweet.id == PHOTO_TWEET).count() == 1
        assert db.XFeedItem.select().where(db.XFeedItem.tweet_id == PHOTO_TWEET).count() == 2


# --- status ------------------------------------------------------------------


def test_status_reports_push_activity(env):
    with _client() as client:
        _login(client)
        status = client.get('/api/x/status').json()
        # the verdict block is Phase 4's and has its own tests (test_x_verdict.py)
        assert {k: v for k, v in status.items() if k != 'verdict'} == {
            'source_enabled': True,
            'subscribed': False,
            'tweets_total': 0,
            'feed_items_total': 0,
            'last_push_at': None,
            'last_push_counts': {},
            'parse_errors': 0,
        }

        _subscribe(client, 'foryou')
        _ingest(client, 'foryou', home_fixture())

        status = client.get('/api/x/status').json()
        assert status['subscribed'] is True
        assert status['tweets_total'] >= 8 and status['feed_items_total'] == 8
        assert status['last_push_at']
        assert status['last_push_counts']['foryou']['new_items'] == 8


# --- auth --------------------------------------------------------------------


def test_probe_endpoints_accept_a_device_bearer_token(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        token = client.post('/api/auth/device', json={'name': 'probe'}).json()['token']
        client.cookies.clear()

        headers = {'Authorization': f'Bearer {token}'}
        assert client.get('/api/sources/x/probe-config', headers=headers).status_code == 200
        r = client.post(
            '/api/sources/x/ingest',
            json={'channel_id': 'foryou', 'tweets': home_fixture()},
            headers=headers,
        )
        assert r.status_code == 200 and r.json()['new_items'] == 8


def test_probe_endpoints_reject_anonymous_calls(env):
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        client.cookies.clear()
        assert client.get('/api/sources/x/probe-config').status_code == 401
        assert _ingest(client, 'foryou', home_fixture()).status_code == 401
        assert client.get('/api/x/status').status_code == 401
