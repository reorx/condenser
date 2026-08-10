"""Behavior tests for the For You language filter.

X's algorithm recommends foreign-language tweets (a production `lang: ar` tweet
started this), so For You gets a language whitelist: the global preference lives
in app_meta `languages`, the For You subscription's `config.lang_filter` switch
turns it on, and a tweet outside the list is dropped whole at ingest — the ad
filter's path (`_apply_following_rules`), not a display-time rule.

Fail-open is the design: a missing `lang` (pre-1.1.0 probe) or a non-language
code (`und`/`zxx`, media-only tweets) always passes, so an un-upgraded probe
disarms the filter instead of emptying the timeline.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from condenser import db, x
from condenser.app import create_app


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _init():
    db.init_db(os.environ['CONDENSER_DB_PATH'])


def _subscribe(client, channel_id, **body):
    return client.post('/api/sources/x/subscriptions', json={'channel_id': channel_id, **body})


def _ingest(client, channel_id, tweets):
    return client.post('/api/sources/x/ingest', json={'channel_id': channel_id, 'tweets': tweets})


def _set_languages(client, languages):
    return client.patch('/api/app/meta', json={'languages': languages})


def _enable_filter(client):
    return client.patch('/api/sources/x/subscriptions/foryou', json={'config': {'lang_filter': True}})


def _entry(tweet_id, lang=None, **extra):
    # fresh timestamp, so Following's age rule never mistakes an entry for a
    # thread ancestor — this file is about the language rule only
    at = datetime.now(timezone.utc) - timedelta(hours=1)
    entry = {
        'id': str(tweet_id),
        'text': f'tweet {tweet_id}',
        'createdAt': at.strftime(x.CREATED_AT_FORMAT),
        'author': {'username': 'someone', 'name': 'Someone'},
        'authorId': '999',
        **extra,
    }
    if lang is not None:
        entry['lang'] = lang
    return entry


def _search_hit(tweet_id) -> bool:
    rows = db.tdb.db.execute_sql(
        "SELECT count(*) FROM search_index WHERE source = 'x' AND ref1 = ?", (str(tweet_id),)
    ).fetchone()
    return bool(rows[0])


def _armed_client():
    """A logged-in client with the filter fully armed: For You subscribed,
    lang_filter on, global languages = zh+en."""
    client = _client()
    client.__enter__()
    _login(client)
    _subscribe(client, 'foryou')
    assert _enable_filter(client).status_code == 200
    assert _set_languages(client, ['zh', 'en']).status_code == 200
    return client


# --- the filter ----------------------------------------------------------------


def test_foreign_language_tweet_is_dropped_whole(env):
    """Not in x_tweets, not in the feed, not in the search index — the ad
    filter's semantics, and only the counter records it happened."""
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _enable_filter(client)
        _set_languages(client, ['zh', 'en'])
        result = _ingest(client, 'foryou', [_entry(101, lang='ar'), _entry(102, lang='zh')]).json()

    assert result['filtered_lang'] == 1
    assert result['new_items'] == 1
    assert db.get_x_tweet(101) is None
    assert not db.existing_x_feed_item_ids('foryou', [101])
    assert not _search_hit(101)
    assert db.get_x_tweet(102) is not None


def test_whitelisted_languages_pass(env):
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _enable_filter(client)
        _set_languages(client, ['zh', 'en'])
        result = _ingest(client, 'foryou', [_entry(111, lang='zh'), _entry(112, lang='en')]).json()
    assert result['filtered_lang'] == 0 and result['new_items'] == 2


def test_missing_lang_passes(env):
    """Fail-open: a pre-1.1.0 probe sends no lang at all, and that must disarm
    the filter, not empty the timeline."""
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _enable_filter(client)
        _set_languages(client, ['zh', 'en'])
        result = _ingest(client, 'foryou', [_entry(121)]).json()
    assert result['filtered_lang'] == 0 and result['new_items'] == 1


def test_non_language_codes_pass(env):
    """`und`/`zxx` mark media-only or undetermined tweets, not a language the
    reader opted out of (measured: 2 of 40 real home tweets carry `zxx`)."""
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _enable_filter(client)
        _set_languages(client, ['zh', 'en'])
        result = _ingest(client, 'foryou', [_entry(131, lang='und'), _entry(132, lang='zxx')]).json()
    assert result['filtered_lang'] == 0 and result['new_items'] == 2


def test_regional_subtag_matches_its_primary_language(env):
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _enable_filter(client)
        _set_languages(client, ['zh', 'en'])
        result = _ingest(client, 'foryou', [_entry(141, lang='zh-cn'), _entry(142, lang='pt-BR')]).json()
    assert result['filtered_lang'] == 1
    assert db.get_x_tweet(141) is not None and db.get_x_tweet(142) is None


# --- when the filter must stay inert --------------------------------------------


def test_switch_off_keeps_everything(env):
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _set_languages(client, ['zh', 'en'])
        result = _ingest(client, 'foryou', [_entry(201, lang='ar')]).json()
    assert result['filtered_lang'] == 0 and result['new_items'] == 1


def test_switch_on_without_global_languages_keeps_everything(env):
    """The switch says 'filter by the global preference'; with no preference set
    there is nothing to filter by — fail-open, not fail-closed."""
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        _enable_filter(client)
        result = _ingest(client, 'foryou', [_entry(211, lang='ar')]).json()
    assert result['filtered_lang'] == 0 and result['new_items'] == 1


def test_other_feeds_are_never_language_filtered(env):
    """You chose to follow these accounts; posting in another language does not
    un-choose them. Only algorithm-picked strangers (For You) are filtered."""
    _init()
    with _client() as client:
        _login(client)
        _set_languages(client, ['zh', 'en'])
        _subscribe(client, 'following')
        _subscribe(client, 'somebody')
        following = _ingest(client, 'following', [_entry(221, lang='ar')]).json()
        user = _ingest(
            client, 'somebody', [_entry(222, lang='ar', author={'username': 'somebody', 'name': 'S'})]
        ).json()
    assert following['filtered_lang'] == 0 and following['new_items'] == 1
    assert user['filtered_lang'] == 0 and user['new_items'] == 1


# --- quoted tweets ---------------------------------------------------------------


def test_a_dropped_tweets_quote_vanishes_with_it(env):
    client = _armed_client()
    try:
        _ingest(client, 'foryou', [_entry(301, lang='ar', quotedTweet=_entry(302, lang='en'))])
    finally:
        client.__exit__(None, None, None)
    assert db.get_x_tweet(301) is None and db.get_x_tweet(302) is None


def test_a_kept_tweets_foreign_quote_is_archived(env):
    """The quote is part of the display unit the reader will see; its language
    was never independently recommended by the algorithm."""
    client = _armed_client()
    try:
        result = _ingest(client, 'foryou', [_entry(311, lang='en', quotedTweet=_entry(312, lang='ar'))]).json()
    finally:
        client.__exit__(None, None, None)
    assert result['filtered_lang'] == 0
    assert db.get_x_tweet(312) is not None
    assert not db.existing_x_feed_item_ids('foryou', [312])


# --- configuration surfaces -------------------------------------------------------


def test_global_languages_roundtrip(env):
    _init()
    with _client() as client:
        _login(client)
        assert client.get('/api/app/meta').json()['languages'] == []
        assert _set_languages(client, ['ZH', 'en']).json()['languages'] == ['zh', 'en']
        assert client.get('/api/app/meta').json()['languages'] == ['zh', 'en']
        # [] clears
        assert _set_languages(client, []).json()['languages'] == []


def test_invalid_language_codes_are_rejected(env):
    _init()
    with _client() as client:
        _login(client)
        for bad in (['zh-cn'], ['english'], [''], ['z1']):
            assert _set_languages(client, bad).status_code == 422, bad
        # nothing was stored
        assert client.get('/api/app/meta').json()['languages'] == []


def test_lang_filter_switch_roundtrips_through_subscription_config(env):
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'foryou')
        subs = client.get('/api/sources/x/subscriptions').json()
        assert subs[0]['lang_filter'] is False
        assert _enable_filter(client).status_code == 200
        subs = client.get('/api/sources/x/subscriptions').json()
        assert subs[0]['lang_filter'] is True


def test_status_reports_the_filtered_count(env):
    client = _armed_client()
    try:
        _ingest(client, 'foryou', [_entry(401, lang='ar'), _entry(402, lang='ko')])
        counts = client.get('/api/x/status').json()['last_push_counts']['foryou']
    finally:
        client.__exit__(None, None, None)
    assert counts['filtered_lang'] == 2


def test_languages_survive_as_plain_json_in_app_meta(env):
    """The key is deliberately generic (`languages`, no x_ prefix) — a global
    preference other sources can reuse."""
    _init()
    with _client() as client:
        _login(client)
        _set_languages(client, ['zh', 'en'])
    assert json.loads(db.get_meta('languages')) == ['zh', 'en']
    assert db.get_languages() == ['zh', 'en']
