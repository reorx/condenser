"""Behavior tests for the probe: round isolation, the seen cache, config loading.

X and the server are both stubbed — the probe's job is orchestration, and that is
what these pin down. How a feed entry becomes an X API call lives in
``test_xsource.py``.
"""

import json
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from condenser_probe import xsource
from condenser_probe.cache import SeenCache
from condenser_probe.client import ServerError
from condenser_probe.config import ConfigError, load_settings
from condenser_probe.runner import run_round

HOME = {'channel_id': 'foryou', 'kind': 'home', 'handle': None, 'n': 50}
USER = {'channel_id': 'novoreorx', 'kind': 'user', 'handle': 'novoreorx', 'n': 10}


class FakeClient:
    """Stands in for ProbeClient: canned probe-config, recorded ingests."""

    def __init__(self, feeds, fail_on=(), sync_following=False, following_fails=False):
        self.feeds = feeds
        self.fail_on = set(fail_on)
        self.sync_following = sync_following
        self.following_fails = following_fails
        self.pushed = []
        self.followed = None

    def probe_config(self):
        return {'feeds': self.feeds, 'sync_following': self.sync_following}

    def ingest(self, channel_id, tweets):
        if channel_id in self.fail_on:
            raise ServerError('boom')
        self.pushed.append((channel_id, tweets))
        return {'new_tweets': len(tweets), 'new_items': len(tweets), 'parse_errors': 0}

    def push_following(self, users):
        if self.following_fails:
            raise ServerError('nope')
        self.followed = users
        return {'received': len(users), 'stored': len(users)}


def tweets(n):
    return [{'id': str(1000 + i), 'text': f't{i}'} for i in range(n)]


# --- one round ----------------------------------------------------------------


def test_round_is_a_no_op_without_server_side_feeds():
    client = FakeClient([])
    calls = []
    assert run_round(client, fetch=lambda feed: calls.append(feed) or []) == []
    assert calls == []  # nothing subscribed -> X is never touched


def test_round_fetches_and_pushes_every_feed():
    client = FakeClient([HOME, USER])
    outcomes = run_round(client, fetch=lambda feed: tweets(feed['n']))

    assert [o.channel_id for o in outcomes] == ['foryou', 'novoreorx']
    assert all(o.ok for o in outcomes)
    assert [(cid, len(t)) for cid, t in client.pushed] == [('foryou', 50), ('novoreorx', 10)]


def test_one_failing_feed_does_not_stop_the_others():
    client = FakeClient([HOME, USER])

    def fetch(feed):
        if feed['channel_id'] == 'foryou':
            raise xsource.XSourceError('cookies expired')
        return tweets(4)

    outcomes = run_round(client, fetch=fetch)
    assert not outcomes[0].ok and 'cookies expired' in outcomes[0].error
    assert outcomes[1].ok and client.pushed == [('novoreorx', tweets(4))]


def test_ingest_failure_is_reported_not_raised():
    client = FakeClient([HOME, USER], fail_on=['foryou'])
    outcomes = run_round(client, fetch=lambda feed: tweets(2))
    assert not outcomes[0].ok and outcomes[0].fetched == 2
    assert outcomes[1].ok


def test_empty_fetch_is_not_pushed():
    client = FakeClient([HOME])
    outcomes = run_round(client, fetch=lambda feed: [])
    assert outcomes[0].ok and client.pushed == []


# --- per-kind rounds (the scheduler's view) -------------------------------------


FOLLOWING = {'channel_id': 'following', 'kind': 'following', 'handle': None, 'n': 50}


def test_a_round_can_be_scoped_to_feed_kinds():
    """The scheduler runs For You and the rest on different cadences, so a round
    must be able to fetch only its own slice of probe-config."""
    client = FakeClient([HOME, FOLLOWING, USER])
    outcomes = run_round(client, fetch=lambda feed: tweets(2), kinds={'following', 'user'})
    assert [o.channel_id for o in outcomes] == ['following', 'novoreorx']
    assert [cid for cid, _ in client.pushed] == ['following', 'novoreorx']


def test_no_kind_filter_means_every_feed():
    client = FakeClient([HOME, FOLLOWING, USER])
    outcomes = run_round(client, fetch=lambda feed: tweets(2))
    assert [o.channel_id for o in outcomes] == ['foryou', 'following', 'novoreorx']


def test_a_scoped_round_with_no_matching_feeds_is_idle():
    client = FakeClient([USER])
    calls = []
    assert run_round(client, fetch=lambda feed: calls.append(feed) or [], kinds={'home'}) == []
    assert calls == []


def test_a_scoped_round_still_obeys_a_follow_sync_request():
    """The server decides when the list is stale; whichever round sees the flag
    first should honor it rather than wait for the following round's slot."""
    users = [{'id': '1', 'username': 'alice'}]
    client = FakeClient([HOME, FOLLOWING], sync_following=True)
    run_round(client, fetch=lambda feed: tweets(2), fetch_following=lambda: users, kinds={'home'})
    assert client.followed == users


# --- the follow list ----------------------------------------------------------


def test_round_syncs_the_follow_list_only_when_the_server_asks():
    users = [{'id': '1', 'username': 'alice'}]
    client = FakeClient([USER], sync_following=True)
    run_round(client, fetch=lambda feed: tweets(2), fetch_following=lambda: users)
    assert client.followed == users

    quiet = FakeClient([USER])
    run_round(quiet, fetch=lambda feed: tweets(2), fetch_following=lambda: users)
    assert quiet.followed is None


def test_the_follow_list_is_synced_before_the_feeds_are_pushed():
    """The server drops entries by unknown authors, so a first round that ingested
    before syncing would filter the whole feed away as advertising."""
    order = []
    client = FakeClient([USER], sync_following=True)

    def ingest(channel_id, tweets_):
        order.append('ingest')
        return {}

    def push_following(users):
        order.append('following')
        return {}

    client.ingest = ingest
    client.push_following = push_following
    run_round(client, fetch=lambda feed: tweets(2), fetch_following=lambda: [{'username': 'a'}])
    assert order == ['following', 'ingest']


def test_a_failed_follow_sync_does_not_sink_the_round():
    client = FakeClient([USER], sync_following=True, following_fails=True)
    outcomes = run_round(client, fetch=lambda feed: tweets(2), fetch_following=lambda: [{'username': 'a'}])
    assert [o.ok for o in outcomes] == [True]
    assert client.pushed == [('novoreorx', tweets(2))]


def test_an_x_failure_while_listing_follows_does_not_sink_the_round():
    client = FakeClient([USER], sync_following=True)

    def boom():
        raise xsource.XSourceError('cookies expired')

    outcomes = run_round(client, fetch=lambda feed: tweets(2), fetch_following=boom)
    assert [o.ok for o in outcomes] == [True] and client.followed is None


def test_the_follow_list_is_synced_even_with_nothing_to_fetch():
    """probe-config only asks when there are feeds, but if it asks, obeying it must
    not depend on a feed succeeding."""
    client = FakeClient([], sync_following=True)
    run_round(client, fetch=lambda feed: [], fetch_following=lambda: [{'username': 'a'}])
    assert client.followed == [{'username': 'a'}]


# --- the incremental cache ----------------------------------------------------


def _cache(tmp_path, **kwargs):
    return SeenCache(root=tmp_path / 'seen', **kwargs)


def test_already_seen_tweets_are_not_pushed_again(tmp_path):
    """Following is a stable window (19/20 overlap between consecutive calls), so
    without this every 15-minute round re-pushes almost the same 50 tweets."""
    cache = _cache(tmp_path)
    client = FakeClient([USER])
    run_round(client, fetch=lambda feed: tweets(3), cache=cache)
    assert [len(t) for _, t in client.pushed] == [3]

    run_round(client, fetch=lambda feed: tweets(4), cache=cache)
    assert [cid for cid, _ in client.pushed] == ['novoreorx', 'novoreorx']
    assert [t['id'] for t in client.pushed[1][1]] == ['1003']  # only the new one


def test_a_feed_that_returns_nothing_new_is_not_pushed_at_all(tmp_path):
    cache = _cache(tmp_path)
    client = FakeClient([USER])
    run_round(client, fetch=lambda feed: tweets(3), cache=cache)
    outcomes = run_round(client, fetch=lambda feed: tweets(3), cache=cache)
    assert len(client.pushed) == 1
    assert outcomes[0].ok and outcomes[0].fetched == 3 and outcomes[0].skipped == 3


def test_entries_are_only_remembered_once_the_server_took_them(tmp_path):
    """Recording before the push would lose a tweet permanently on a 500."""
    cache = _cache(tmp_path)
    failing = FakeClient([USER], fail_on=['novoreorx'])
    run_round(failing, fetch=lambda feed: tweets(3), cache=cache)

    client = FakeClient([USER])
    run_round(client, fetch=lambda feed: tweets(3), cache=cache)
    assert [len(t) for _, t in client.pushed] == [3]


def test_the_cache_is_pruned_to_its_window(tmp_path):
    """A few hundred ints, bounded by time rather than by count."""
    cache = _cache(tmp_path, max_age_hours=24)
    old = datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc)
    cache.record('novoreorx', tweets(2), now=old)
    cache.record('novoreorx', [{'id': '2000'}], now=old + timedelta(hours=30))

    assert set(cache.load('novoreorx')) == {'2000'}


def test_a_lost_cache_just_means_a_full_repush(tmp_path):
    """The server dedupes by tweet id, so the recovery path is "do nothing"."""
    cache = _cache(tmp_path)
    client = FakeClient([USER])
    run_round(client, fetch=lambda feed: tweets(3), cache=cache)
    shutil.rmtree(tmp_path / 'seen')
    run_round(client, fetch=lambda feed: tweets(3), cache=cache)
    assert [len(t) for _, t in client.pushed] == [3, 3]


def test_an_unwritable_cache_does_not_break_the_round(tmp_path, monkeypatch):
    cache = _cache(tmp_path)

    def boom(*args, **kwargs):
        raise OSError('read-only file system')

    monkeypatch.setattr(SeenCache, '_write', boom)
    client = FakeClient([USER])
    outcomes = run_round(client, fetch=lambda feed: tweets(3), cache=cache)
    assert outcomes[0].ok and [len(t) for _, t in client.pushed] == [3]


def test_no_cache_means_the_old_stateless_behavior():
    client = FakeClient([USER])
    run_round(client, fetch=lambda feed: tweets(3), cache=None)
    run_round(client, fetch=lambda feed: tweets(3), cache=None)
    assert [len(t) for _, t in client.pushed] == [3, 3]


def test_feeds_have_separate_caches(tmp_path):
    """The same tweet legitimately arrives through For You, Following and its
    author's own feed — each appearance is a separate row on the server."""
    cache = _cache(tmp_path)
    client = FakeClient([HOME, USER])
    run_round(client, fetch=lambda feed: tweets(2), cache=cache)
    assert [(cid, len(t)) for cid, t in client.pushed] == [('foryou', 2), ('novoreorx', 2)]


# --- config -------------------------------------------------------------------


def test_settings_come_from_a_file_and_env_wins(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'server_url': 'https://from-file/', 'token': 'file-token', 'x_timeout_ms': 45000}))
    for key in ('SERVER_URL', 'TOKEN', 'X_TIMEOUT_MS', 'TIMEOUT', 'LOG_LEVEL'):
        monkeypatch.delenv(f'CONDENSER_PROBE_{key}', raising=False)

    settings = load_settings(path)
    assert settings.api_base == 'https://from-file' and settings.token == 'file-token'
    assert settings.x_timeout_ms == 45000

    monkeypatch.setenv('CONDENSER_PROBE_TOKEN', 'env-token')
    assert load_settings(path).token == 'env-token'


def test_missing_credentials_are_fatal(tmp_path, monkeypatch):
    for key in ('SERVER_URL', 'TOKEN'):
        monkeypatch.delenv(f'CONDENSER_PROBE_{key}', raising=False)
    with pytest.raises(ConfigError, match='server_url'):
        load_settings(tmp_path / 'missing.json')
