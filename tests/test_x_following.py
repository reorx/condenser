"""Behavior tests for the X Following timeline (plan kb/plans/2026-07-30-x-following-feed.md).

Step 1 here is the **followed-accounts list**: the Following feed carries injected
ads that carry no structural marker at all (measured: `promoted` / `advertiser` /
`socialContext` hit 0/20 in bird's `--json-full` output), so the only reliable
filter is "is this author someone I follow". The list therefore has to live on the
server — it is the archive's owner, and a rule applied probe-side throws data away
that can never be recovered.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from condenser import db, x
from condenser.app import create_app

FIXTURES = Path(__file__).parent / 'fixtures' / 'x'


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _init():
    db.init_db(os.environ['CONDENSER_DB_PATH'])


def _push_following(client, users):
    return client.post('/api/sources/x/following', json={'users': users})


def _subscribe(client, channel_id, **body):
    return client.post('/api/sources/x/subscriptions', json={'channel_id': channel_id, **body})


def _ingest(client, channel_id, tweets):
    return client.post('/api/sources/x/ingest', json={'channel_id': channel_id, 'tweets': tweets})


def _users(*handles):
    return [{'id': str(100 + i), 'username': h, 'name': h.title()} for i, h in enumerate(handles)]


def feed_fixture():
    """bird's `home --following` output: 7 in-window tweets, 3 injected ads, and
    @zdyxry's two thread ancestors (2026-04 and 2025-09) — see the plan §2.4."""
    return json.loads((FIXTURES / 'following_feed.json').read_text())


def users_fixture():
    return json.loads((FIXTURES / 'following_users.json').read_text())['users']


def _stamp(hours_ago: float) -> str:
    """bird's legacy Twitter timestamp form, relative to now."""
    at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return at.strftime(x.CREATED_AT_FORMAT)


def _entry(tweet_id, handle, hours_ago=1.0, **extra):
    return {
        'id': str(tweet_id),
        'text': f'hello from @{handle}',
        'createdAt': _stamp(hours_ago),
        'author': {'username': handle, 'name': handle.title()},
        'authorId': '999',
        **extra,
    }


# --- schema -------------------------------------------------------------------


def test_fresh_db_creates_the_following_table(env):
    _init()
    assert db.get_meta('schema_version') == str(db.SCHEMA_VERSION)
    tables = {r[0] for r in db.tdb.db.execute_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert 'x_following' in tables


def test_existing_v10_database_gains_the_following_table(env):
    """v11 is purely additive — the upgrade is plain create_tables, no data touched."""
    _init()
    db.set_meta('schema_version', '10')
    db.XTweet.create(id=1, fetched_at=datetime(2026, 7, 29, 12, 0), text='kept')
    db.tdb.db.close()

    _init()
    assert db.get_meta('schema_version') == str(db.SCHEMA_VERSION)
    assert db.get_x_tweet(1).text == 'kept'
    assert db.x_following_handles() == set()


# --- the list itself ----------------------------------------------------------


def test_push_replaces_the_whole_list(env):
    """Full-replace semantics: an account you unfollowed has to disappear, and an
    incremental merge cannot express that."""
    _init()
    with _client() as client:
        _login(client)
        assert _push_following(client, _users('alice', 'bob')).status_code == 200
        assert db.x_following_handles() == {'alice', 'bob'}

        resp = _push_following(client, _users('bob', 'carol'))
        assert resp.status_code == 200 and resp.json()['stored'] == 2
        assert db.x_following_handles() == {'bob', 'carol'}


def test_handles_are_stored_lowercased(env):
    """The feed's author handle is matched against this set, and X preserves the
    account's own capitalization in both places but not consistently."""
    _init()
    with _client() as client:
        _login(client)
        _push_following(client, [{'id': '1', 'username': '@NovoReorx', 'name': 'Reorx'}])
    assert db.x_following_handles() == {'novoreorx'}
    assert db.x_following_user('novoreorx').name == 'Reorx'


def test_unusable_entries_are_dropped_not_fatal(env):
    """bird's output tracks X's internal API; one drifted entry must not reject the
    whole list (the XIngestBody stance, for the same reason)."""
    _init()
    with _client() as client:
        _login(client)
        resp = _push_following(
            client,
            [{'id': '1', 'username': 'alice'}, {'id': '2'}, 'nonsense', {'username': ''}, None],
        )
    assert resp.status_code == 200
    assert resp.json() == {'received': 5, 'stored': 1, 'synced_at': db.x_following_synced_at().isoformat(sep=' ')}
    assert db.x_following_handles() == {'alice'}


def test_an_empty_push_never_wipes_an_existing_list(env):
    """A transient bird failure that yields `[]` would otherwise disable the ad
    filter for a whole sync interval — silently, since an empty list means "do not
    filter" (see the ingest rule)."""
    _init()
    with _client() as client:
        _login(client)
        _push_following(client, _users('alice'))
        resp = _push_following(client, [])
        assert resp.status_code == 422
    assert db.x_following_handles() == {'alice'}


def test_an_empty_push_is_accepted_while_the_list_is_empty(env):
    """Nothing to lose, and stamping the sync stops the probe retrying every round."""
    _init()
    with _client() as client:
        _login(client)
        resp = _push_following(client, [])
        assert resp.status_code == 200 and resp.json()['stored'] == 0
    assert db.x_following_synced_at() is not None


def test_push_is_refused_while_the_source_is_disabled(env, monkeypatch):
    monkeypatch.setenv('CONDENSER_X_ENABLED', 'false')
    from condenser.config import get_settings

    get_settings.cache_clear()
    _init()
    with _client() as client:
        _login(client)
        assert _push_following(client, _users('alice')).status_code == 503


# --- when the probe is asked to sync ------------------------------------------


def test_probe_config_asks_for_a_sync_when_the_list_has_never_been_synced(env):
    _init()
    db.add_x_subscription('foryou', name='X For You', config=x.default_config('foryou'))
    with _client() as client:
        _login(client)
        assert client.get('/api/sources/x/probe-config').json()['sync_following'] is True


def test_probe_config_stops_asking_once_the_list_is_fresh(env):
    _init()
    db.add_x_subscription('foryou', name='X For You', config=x.default_config('foryou'))
    with _client() as client:
        _login(client)
        _push_following(client, _users('alice'))
        assert client.get('/api/sources/x/probe-config').json()['sync_following'] is False

        stale = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=25)
        db.set_meta(db.FOLLOWING_SYNCED_META_KEY, stale.isoformat(sep=' ', timespec='seconds'))
        assert client.get('/api/sources/x/probe-config').json()['sync_following'] is True


def test_probe_config_does_not_ask_when_nothing_is_subscribed(env):
    """The probe idles entirely with no feeds; a 15-request follow-list crawl for a
    source nobody reads is pure cost."""
    _init()
    with _client() as client:
        _login(client)
        body = client.get('/api/sources/x/probe-config').json()
        assert body['feeds'] == [] and body['sync_following'] is False


def test_probe_config_does_not_ask_while_the_source_is_disabled(env, monkeypatch):
    monkeypatch.setenv('CONDENSER_X_ENABLED', 'false')
    from condenser.config import get_settings

    get_settings.cache_clear()
    _init()
    db.add_x_subscription('foryou', name='X For You', config=x.default_config('foryou'))
    with _client() as client:
        _login(client)
        assert client.get('/api/sources/x/probe-config').json()['sync_following'] is False


# --- real bird output ---------------------------------------------------------


def test_a_real_bird_following_page_is_stored(env):
    """The fixture is bird's own `following --all` output (the {users, nextCursor}
    shape), trimmed; the server accepts the user objects verbatim."""
    _init()
    entries = json.loads((FIXTURES / 'following_users.json').read_text())['users']
    with _client() as client:
        _login(client)
        resp = _push_following(client, entries)
    assert resp.status_code == 200
    assert resp.json()['stored'] == len(entries)
    assert 'scavin' in db.x_following_handles()
    assert db.x_following_user('scavin').user_id.isdigit()


# --- step 2: the Following feed itself ----------------------------------------


def test_following_is_its_own_feed_kind_not_an_account_called_following(env):
    """`HANDLE_RE` happily matches the string 'following', so without an explicit
    branch the feed would be configured as @following and the probe would run
    `bird user-tweets following`."""
    _init()
    with _client() as client:
        _login(client)
        body = _subscribe(client, 'following').json()
        assert body['channel_id'] == 'following' and body['kind'] == 'following'
        assert body['handle'] is None and body['name'] == x.FOLLOWING_NAME

        feed = client.get('/api/sources/x/probe-config').json()['feeds'][0]
        assert feed == {'channel_id': 'following', 'kind': 'following', 'handle': None, 'n': 50}


def test_following_feed_count_is_overridable_per_feed(env):
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'following', n=120)
        assert client.get('/api/sources/x/probe-config').json()['feeds'][0]['n'] == 120


def test_ads_are_dropped_whole(env, monkeypatch):
    """The injected ads carry no structural marker, so the follow list is the only
    filter — and an ad is pure noise, so not even its body is worth archiving."""
    _init()
    monkeypatch.setattr(x, '_now', _fixture_now)
    entries = feed_fixture()
    ad_ids = [int(e['id']) for e in entries if e['author']['username'].lower() not in _fixture_handles()]
    assert ad_ids, 'fixture should contain injected ads'

    with _client() as client:
        _login(client)
        _push_following(client, users_fixture())
        _subscribe(client, 'following')
        result = _ingest(client, 'following', entries).json()

    assert result['filtered_ads'] == len(ad_ids)
    for tid in ad_ids:
        assert db.get_x_tweet(tid) is None
        assert not db.existing_x_feed_item_ids('following', [tid])


def test_a_fresh_ad_is_caught_by_the_list_not_by_the_age_rule(env):
    """Every ad in the sample happened to be older than 24h, so the age rule would
    have hidden this: X can inject one posted minutes ago."""
    _init()
    with _client() as client:
        _login(client)
        _push_following(client, _users('alice'))
        _subscribe(client, 'following')
        result = _ingest(client, 'following', [_entry(11, 'alice'), _entry(12, 'someadco', hours_ago=0.2)]).json()

    assert result['filtered_ads'] == 1 and result['new_items'] == 1
    assert db.get_x_tweet(12) is None and db.get_x_tweet(11) is not None


def test_an_empty_follow_list_disables_the_filter_entirely(env):
    """Otherwise the very first round — before the list has ever been synced —
    silently discards every tweet as advertising."""
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'following')
        result = _ingest(client, 'following', [_entry(21, 'alice'), _entry(22, 'someadco')]).json()

    assert result['filtered_ads'] == 0 and result['new_items'] == 2


def test_thread_ancestors_are_archived_but_never_enter_the_timeline(env, monkeypatch):
    """X drags a thread's older tweets in for context. Storing them as feed items
    would insert them into 2025-09 and 2026-04 timeline history — invisible on
    screen, but +2 on the unread badge. The body is kept (the reply chain stays
    complete, and it costs a few hundred bytes) exactly like a quoted tweet."""
    _init()
    monkeypatch.setattr(x, '_now', _fixture_now)
    entries = feed_fixture()
    old = [e for e in entries if _age_hours(e) >= 24 and e['author']['username'].lower() in _fixture_handles()]
    assert old, 'fixture should contain the thread ancestors'

    with _client() as client:
        _login(client)
        _push_following(client, users_fixture())
        _subscribe(client, 'following')
        result = _ingest(client, 'following', entries).json()

    assert result['filtered_old'] == len(old)
    for entry in old:
        tid = int(entry['id'])
        assert db.get_x_tweet(tid) is not None  # body archived
        assert not db.existing_x_feed_item_ids('following', [tid])  # but not in the feed


def test_the_age_rule_uses_a_configurable_window(env, monkeypatch):
    monkeypatch.setenv('CONDENSER_X_FOLLOWING_MAX_AGE_HOURS', '48')
    from condenser.config import get_settings

    get_settings.cache_clear()
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'following')
        result = _ingest(client, 'following', [_entry(31, 'alice', hours_ago=30)]).json()
    assert result['filtered_old'] == 0 and result['new_items'] == 1


def test_a_quoted_tweet_is_not_judged_by_either_rule(env):
    """A quote's author is usually someone you don't follow and its timestamp is
    arbitrary — but it was never a feed entry, and its path (body only, no feed
    row) is already what both rules produce."""
    _init()
    quoted = _entry(42, 'strangerco', hours_ago=900)
    with _client() as client:
        _login(client)
        _push_following(client, _users('alice'))
        _subscribe(client, 'following')
        result = _ingest(client, 'following', [_entry(41, 'alice', quotedTweet=quoted)]).json()

    assert result['filtered_ads'] == 0 and result['filtered_old'] == 0
    assert db.get_x_tweet(42) is not None
    assert not db.existing_x_feed_item_ids('following', [42])


def test_an_ads_quoted_tweet_is_dropped_with_it(env):
    _init()
    with _client() as client:
        _login(client)
        _push_following(client, _users('alice'))
        _subscribe(client, 'following')
        _ingest(client, 'following', [_entry(51, 'someadco', quotedTweet=_entry(52, 'alice'))])
    assert db.get_x_tweet(51) is None and db.get_x_tweet(52) is None


def test_neither_rule_applies_to_the_other_feeds(env):
    """For You's whole job is showing you accounts you don't follow, and it
    resurfaces old tweets by design (which is why it sorts by first_seen_at)."""
    _init()
    with _client() as client:
        _login(client)
        _push_following(client, _users('alice'))
        _subscribe(client, 'foryou')
        _subscribe(client, 'bob')
        foryou = _ingest(client, 'foryou', [_entry(61, 'someadco', hours_ago=900)]).json()
        user = _ingest(client, 'bob', [_entry(62, 'bob', hours_ago=900)]).json()

    assert foryou['filtered_ads'] == 0 and foryou['filtered_old'] == 0 and foryou['new_items'] == 1
    assert user['new_items'] == 1


def test_a_following_push_never_renames_the_feed(env):
    """`_learn_user_identity` fills a followed account's numeric id and display name
    from the tweets it authored. Following has no single author, so the first
    entry's name would become the feed's name."""
    _init()
    with _client() as client:
        _login(client)
        _subscribe(client, 'following')
        _ingest(client, 'following', [_entry(71, 'alice')])
        sub = client.get('/api/sources/x/subscriptions').json()[0]

    assert sub['name'] == x.FOLLOWING_NAME
    assert sub['handle'] is None and sub['user_id'] is None


# --- step 3: the timeline -----------------------------------------------------


def _timeline(client, **params):
    r = client.get('/api/timeline', params={'limit': 50, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _seed(client, entries_by_feed):
    for feed in entries_by_feed:
        _subscribe(client, feed)
    for feed, entries in entries_by_feed.items():
        assert _ingest(client, feed, entries).status_code == 200


def _feeds_of(page):
    return [i['x']['feed'] for i in page['items'] if i['source'] == 'x']


def test_a_tweet_in_every_feed_is_shown_once_under_the_account_subscription(env):
    """Three feeds now, so the tie-break has to be explicit: whoever wins owns the
    tweet's sort timestamp, its aggregate-admission rule, its verdict badge and its
    unread count. Left on "first sighting wins" those would follow whichever feed
    the probe happened to reach first."""
    _init()
    tweet = _entry(101, 'alice')
    with _client() as client:
        _login(client)
        _seed(client, {'alice': [tweet], 'following': [tweet], 'foryou': [tweet]})
        page = _timeline(client, source='x', all=1)

    assert _feeds_of(page) == ['alice']


def test_following_outranks_foryou_for_an_account_you_have_not_subscribed_to(env):
    _init()
    tweet = _entry(102, 'bob')
    with _client() as client:
        _login(client)
        _seed(client, {'foryou': [tweet], 'following': [tweet]})
        page = _timeline(client, source='x', all=1)

    assert _feeds_of(page) == ['following']


def test_following_joins_the_aggregate_timeline_by_default(env):
    """Unlike For You this is not a firehose (~100-200/day against For You's 57-136
    of which ~13% are recommended), and "the people I follow" is a set the reader
    curated by hand — nothing to filter."""
    _init()
    with _client() as client:
        _login(client)
        _seed(client, {'following': [_entry(103, 'alice')], 'foryou': [_entry(104, 'stranger')]})
        page = _timeline(client, all=1)

    assert _feeds_of(page) == ['following']


def test_foryou_still_needs_a_verdict_to_join_the_aggregate(env):
    _init()
    with _client() as client:
        _login(client)
        _seed(client, {'foryou': [_entry(105, 'stranger'), _entry(106, 'stranger2')]})
        client.patch('/api/sources/x/subscriptions/foryou', json={'config': {'aggregate': 'positive'}})
        db.set_x_verdict('foryou', 105, 'positive', {})

        assert [i['x']['id'] for i in _timeline(client, all=1)['items']] == ['105']


def test_following_can_be_kept_out_of_the_aggregate_without_pausing_it(env):
    """Pausing the subscription would stop the archive too — and the archive is the
    training data every verdict channel learns from."""
    _init()
    with _client() as client:
        _login(client)
        _seed(client, {'following': [_entry(107, 'alice')]})
        client.patch('/api/sources/x/subscriptions/following', json={'config': {'aggregate': 'none'}})

        assert _timeline(client, all=1)['items'] == []
        assert len(_timeline(client, source='x', all=1)['items']) == 1
        assert len(_timeline(client, source='x', feed='following', all=1)['items']) == 1


def test_following_has_no_recommended_only_mode(env):
    """Following is never judged (the verdict exists to filter strangers the
    algorithm picked), so 'positive' would silently hide the whole feed."""
    _init()
    with _client() as client:
        _login(client)
        _seed(client, {'following': [_entry(108, 'alice')]})
        body = client.patch('/api/sources/x/subscriptions/following', json={'config': {'aggregate': 'positive'}}).json()

    assert body['aggregate'] == 'all'
    assert len(_timeline(client, all=1)['items']) == 1


def test_unread_attribution_does_not_drift_with_the_push_order(env):
    """The badge has to name the same feed whichever push landed first, or the
    sidebar count moves between two rows on its own."""
    _init()
    tweet = _entry(109, 'alice')
    with _client() as client:
        _login(client)
        _seed(client, {'following': [tweet], 'alice': [tweet]})
        by_feed = {s['channel_id']: s['unread'] for s in client.get('/api/sources').json()[0]['subscriptions']}

    assert by_feed == {'following': 0, 'alice': 1}


def test_mark_all_read_in_the_aggregate_spares_the_foryou_backlog(env):
    """ "Mark all read" must burn exactly what the aggregate showed: For You is the
    labeling queue the classifier is still learning from."""
    _init()
    with _client() as client:
        _login(client)
        _seed(client, {'following': [_entry(110, 'alice')], 'foryou': [_entry(111, 'stranger')]})
        assert client.post('/api/read/bulk', json={}).status_code == 200
        unread = {s['channel_id']: s['unread'] for s in client.get('/api/sources').json()[0]['subscriptions']}

    assert unread == {'following': 0, 'foryou': 1}


def test_the_calendar_and_the_new_poll_agree_with_the_page(env):
    """Every surface that counts derives from the same admission rule — the 2026-07-29
    aggregate-mode work landed because one of them did not."""
    _init()
    with _client() as client:
        _login(client)
        _seed(client, {'following': [_entry(112, 'alice')], 'foryou': [_entry(113, 'stranger')]})
        page = _timeline(client, all=1)
        days = client.get('/api/timeline/days', params={'all': 1}).json()
        fresh = client.get('/api/timeline/new', params={'after': page['head_cursor'], 'all': 1}).json()

    assert sum(d['count'] for d in days) == 1
    assert fresh['count'] == 0


def _fixture_handles():
    return {u['username'].lower() for u in users_fixture()}


def _created(entry):
    return x.parse_created_at(entry['createdAt'])


def _fixture_now():
    """ "Now" for the recorded sample: the moment its newest entry was posted.

    The fixture is a real feed page frozen on 2026-07-29, so the age rule has to be
    evaluated against the sample's own clock — otherwise its in-window tweets age
    out of the test a day after it was written.
    """
    return max(_created(e) for e in feed_fixture())


def _age_hours(entry):
    return (_fixture_now() - _created(entry)).total_seconds() / 3600
