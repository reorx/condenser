"""Behavior tests for the probe: command building, round isolation, config loading.

bird and the server are both stubbed — the probe's job is orchestration, and that
is what these pin down.
"""

import json

import pytest

from condenser_probe import bird
from condenser_probe.client import ServerError
from condenser_probe.config import ConfigError, load_settings
from condenser_probe.runner import run_round

HOME = {'channel_id': 'foryou', 'kind': 'home', 'handle': None, 'n': 50}
USER = {'channel_id': 'novoreorx', 'kind': 'user', 'handle': 'novoreorx', 'n': 10}


class FakeClient:
    """Stands in for ProbeClient: canned probe-config, recorded ingests."""

    def __init__(self, feeds, fail_on=()):
        self.feeds = feeds
        self.fail_on = set(fail_on)
        self.pushed = []

    def probe_config(self):
        return self.feeds

    def ingest(self, channel_id, tweets):
        if channel_id in self.fail_on:
            raise ServerError('boom')
        self.pushed.append((channel_id, tweets))
        return {'new_tweets': len(tweets), 'new_items': len(tweets), 'parse_errors': 0}


def tweets(n):
    return [{'id': str(1000 + i), 'text': f't{i}'} for i in range(n)]


# --- bird command building ----------------------------------------------------


def test_build_command_per_feed_kind():
    assert bird.build_command(HOME) == ['bird', 'home', '-n', '50', '--json']
    assert bird.build_command(USER, bird_bin='/opt/bin/bird') == [
        '/opt/bin/bird',
        'user-tweets',
        'novoreorx',
        '-n',
        '10',
        '--json',
    ]


def test_build_command_rejects_unusable_feeds():
    with pytest.raises(bird.BirdError):
        bird.build_command({'channel_id': 'x', 'kind': 'lists'})
    with pytest.raises(bird.BirdError):
        bird.build_command({'kind': 'user', 'n': 10})


def test_fetch_feed_rejects_non_json_output(monkeypatch):
    monkeypatch.setattr(bird, '_run', lambda cmd, timeout: 'Error: not logged in\n')
    with pytest.raises(bird.BirdError, match='did not return JSON'):
        bird.fetch_feed(HOME)


def test_fetch_feed_returns_birds_entries_untouched(monkeypatch):
    payload = tweets(3)
    monkeypatch.setattr(bird, '_run', lambda cmd, timeout: json.dumps(payload))
    assert bird.fetch_feed(HOME) == payload


# --- one round ----------------------------------------------------------------


def test_round_is_a_no_op_without_server_side_feeds():
    client = FakeClient([])
    calls = []
    assert run_round(client, fetch=lambda feed: calls.append(feed) or []) == []
    assert calls == []  # nothing subscribed -> bird is never invoked


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
            raise bird.BirdError('cookies expired')
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


# --- config -------------------------------------------------------------------


def test_settings_come_from_a_file_and_env_wins(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'server_url': 'https://from-file/', 'token': 'file-token', 'bird_bin': '/bin/bird'}))
    for key in ('SERVER_URL', 'TOKEN', 'BIRD_BIN', 'TIMEOUT', 'LOG_LEVEL'):
        monkeypatch.delenv(f'CONDENSER_PROBE_{key}', raising=False)

    settings = load_settings(path)
    assert settings.api_base == 'https://from-file' and settings.token == 'file-token'
    assert settings.bird_bin == '/bin/bird'

    monkeypatch.setenv('CONDENSER_PROBE_TOKEN', 'env-token')
    assert load_settings(path).token == 'env-token'


def test_missing_credentials_are_fatal(tmp_path, monkeypatch):
    for key in ('SERVER_URL', 'TOKEN'):
        monkeypatch.delenv(f'CONDENSER_PROBE_{key}', raising=False)
    with pytest.raises(ConfigError, match='server_url'):
        load_settings(tmp_path / 'missing.json')
