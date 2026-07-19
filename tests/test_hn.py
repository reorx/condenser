"""Behavior tests for the Hacker News source (Phase 1): sampling, backfill, endpoints.

HTTP is mocked by injecting ``fetch_json`` into HNManager — no network, no extra deps.
"""

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from condenser import db
from condenser.app import create_app

TOPSTORIES = 'https://hacker-news.firebaseio.com/v0/topstories.json'

# Fixed "now" (naive UTC, matching storage convention) injected into the manager.
NOW = datetime(2026, 7, 19, 12, 0)
TODAY = NOW.date()


def item_url(sid):
    return f'https://hacker-news.firebaseio.com/v0/item/{sid}.json'


def hckr_url(day):
    return f'https://hckrnews.com/data/{day.strftime("%Y%m%d")}.js'


def unix(dt):
    return int((dt - datetime(1970, 1, 1)).total_seconds())


def story(sid, **over):
    payload = {
        'id': sid,
        'type': 'story',
        'title': f'Story {sid}',
        'url': f'https://example.com/{sid}',
        'by': 'alice',
        'time': unix(NOW - timedelta(hours=1)),
        'score': 10,
        'descendants': 3,
    }
    payload.update(over)
    return payload


class FakeFetch:
    """URL -> canned JSON payload (or Exception to raise). Records every call."""

    def __init__(self):
        self.responses = {}
        self.calls = []

    def set(self, url, payload):
        self.responses[url] = payload

    async def __call__(self, url):
        self.calls.append(url)
        if url not in self.responses:
            raise KeyError(f'unexpected URL fetched: {url}')
        v = self.responses[url]
        if isinstance(v, Exception):
            raise v
        return json.loads(json.dumps(v)) if v is not None else None

    def count(self, url):
        return self.calls.count(url)


def make_manager(fetch, now=NOW):
    from condenser.config import get_settings
    from condenser.hn import HNManager

    db.init_db(os.environ['CONDENSER_DB_PATH'])
    mgr = HNManager(get_settings(), fetch_json=fetch)
    mgr.item_throttle = 0
    mgr.backfill_day_interval = 0
    mgr._now = lambda: now
    return mgr


def subscribe_front():
    return db.add_hn_subscription('front', name='Hacker News Front Page')


# --- subscriptions table migration (SCHEMA_VERSION 3) ------------------------


def test_subscriptions_table_migrates_to_v3(env):
    """An existing v2 DB (single-column PK, no source) is rebuilt in place with data intact."""
    path = os.environ['CONDENSER_DB_PATH']
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE subscriptions ('
        'channel_id INTEGER NOT NULL PRIMARY KEY, enabled INTEGER NOT NULL, '
        'backfill_done INTEGER NOT NULL, added_at DATETIME NOT NULL)'
    )
    conn.execute("INSERT INTO subscriptions VALUES (5, 1, 0, '2026-06-01 10:00:00')")
    conn.execute("INSERT INTO subscriptions VALUES (6, 0, 1, '2026-06-02 10:00:00')")
    conn.commit()
    conn.close()

    db.init_db(path)

    # legacy rows survive as source='telegram' with fields intact
    s5, s6 = db.get_subscription(5), db.get_subscription(6)
    assert s5.source == 'telegram' and bool(s5.enabled) and not bool(s5.backfill_done)
    assert s6.source == 'telegram' and not bool(s6.enabled) and bool(s6.backfill_done)

    # TG CRUD keeps working against the rebuilt table
    db.add_subscription(7)
    assert db.get_subscription(7) is not None
    assert sorted(db.enabled_channel_ids()) == [5, 7]
    db.set_subscription_enabled(5, False)
    assert db.enabled_channel_ids() == [7]

    # HN + TG rows coexist under the composite key
    subscribe_front()
    assert db.get_hn_subscription('front') is not None
    assert {s.channel_id for s in db.list_subscriptions()} == {5, 6, 7}  # TG list only

    # migration is idempotent: init again on the migrated file
    db.init_db(path)
    assert db.get_subscription(5) is not None


def test_fresh_db_records_schema_version_3(env):
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    assert db.get_meta('schema_version') == str(db.SCHEMA_VERSION)
    assert db.SCHEMA_VERSION == 3


# --- sampling: subscription-driven --------------------------------------------


def test_poll_skips_without_enabled_subscription(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)

    # no subscription -> the whole round is a no-op, zero requests
    asyncio.run(mgr.poll_once())
    assert fetch.calls == []

    # subscribing turns sampling on
    subscribe_front()
    fetch.set(TOPSTORIES, [101])
    fetch.set(item_url(101), story(101))
    asyncio.run(mgr.poll_once())
    assert db.get_hn_story(101) is not None

    # a disabled subscription also skips
    db.update_hn_subscription('front', enabled=False)
    n = len(fetch.calls)
    asyncio.run(mgr.poll_once())
    assert len(fetch.calls) == n

    # unsubscribing stops sampling but keeps accumulated data
    db.delete_hn_subscription('front')
    asyncio.run(mgr.poll_once())
    assert len(fetch.calls) == n
    assert db.get_hn_story(101) is not None


def test_new_story_inserted_with_first_seen_and_dedupe(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()

    fetch.set(TOPSTORIES, [101, 102])
    fetch.set(item_url(101), story(101, score=10))
    fetch.set(item_url(102), story(102, url=None, text='<p>Ask HN body</p>'))
    asyncio.run(mgr.poll_once())

    s = db.get_hn_story(101)
    assert s.first_seen_at == NOW
    assert s.day == '2026-07-19'
    assert s.title == 'Story 101'
    assert s.domain == 'example.com'
    assert s.author == 'alice'
    assert s.score == 10 and s.comments_count == 3
    assert s.peak_rank == 1
    assert not bool(s.backfilled)
    # self-post: url NULL, text kept
    ask = db.get_hn_story(102)
    assert ask.url is None and ask.text == '<p>Ask HN body</p>' and ask.domain is None

    # a later round must not reset first_seen_at (dedupe), and peak_rank keeps its best
    later = NOW + timedelta(hours=1)
    mgr._now = lambda: later
    fetch.set(TOPSTORIES, [102, 101])  # 101 dropped to rank 2
    fetch.set(item_url(101), story(101, score=50))
    fetch.set(item_url(102), story(102, url=None))
    asyncio.run(mgr.poll_once())
    s = db.get_hn_story(101)
    assert s.first_seen_at == NOW  # unchanged
    assert s.peak_rank == 1  # best rank retained
    assert s.score == 50  # snapshot refreshed


def test_refresh_window_updates_scores_and_expires(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()

    # story 1 first seen 50h ago -> outside the 48h refresh window
    mgr._now = lambda: NOW - timedelta(hours=50)
    fetch.set(TOPSTORIES, [1])
    fetch.set(item_url(1), story(1, score=100))
    asyncio.run(mgr.poll_once())

    # story 2 arrives now; story 1 must NOT be refetched
    mgr._now = lambda: NOW
    fetch.set(TOPSTORIES, [2])
    fetch.set(item_url(2), story(2, score=5))
    asyncio.run(mgr.poll_once())
    assert fetch.count(item_url(1)) == 1
    assert fetch.count(item_url(2)) == 1

    # next round: story 2 is in-window and not on the front anymore -> snapshot refreshed
    mgr._now = lambda: NOW + timedelta(hours=1)
    fetch.set(TOPSTORIES, [])
    fetch.set(item_url(2), story(2, score=42, descendants=17))
    asyncio.run(mgr.poll_once())
    s2 = db.get_hn_story(2)
    assert s2.score == 42 and s2.comments_count == 17
    assert fetch.count(item_url(1)) == 1  # still expired


def test_day_key_is_utc(env):
    fetch = FakeFetch()
    late = datetime(2026, 7, 18, 23, 30)  # 23:30 UTC
    mgr = make_manager(fetch, now=late)
    subscribe_front()
    fetch.set(TOPSTORIES, [7])
    fetch.set(item_url(7), story(7))
    asyncio.run(mgr.poll_once())
    assert db.get_hn_story(7).day == '2026-07-18'


def test_dead_item_marked_and_not_refreshed(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()

    fetch.set(TOPSTORIES, [1, 2])
    fetch.set(item_url(1), story(1))
    fetch.set(item_url(2), story(2))
    asyncio.run(mgr.poll_once())

    # story 1 gets deleted upstream (null item), story 2 flagged dead
    mgr._now = lambda: NOW + timedelta(hours=1)
    fetch.set(TOPSTORIES, [])
    fetch.set(item_url(1), None)
    fetch.set(item_url(2), story(2, dead=True))
    asyncio.run(mgr.poll_once())
    assert bool(db.get_hn_story(1).is_dead)
    assert bool(db.get_hn_story(2).is_dead)

    # dead stories drop out of the refresh set
    mgr._now = lambda: NOW + timedelta(hours=2)
    n1, n2 = fetch.count(item_url(1)), fetch.count(item_url(2))
    asyncio.run(mgr.poll_once())
    assert fetch.count(item_url(1)) == n1
    assert fetch.count(item_url(2)) == n2


def test_single_item_failure_does_not_kill_round(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()

    fetch.set(TOPSTORIES, [1, 2])
    fetch.set(item_url(1), RuntimeError('boom'))
    fetch.set(item_url(2), story(2))
    asyncio.run(mgr.poll_once())

    assert db.get_hn_story(1) is None
    assert db.get_hn_story(2) is not None
    # the round still completed and stamped its poll time
    assert db.get_meta('hn_last_poll_at') is not None


def test_whole_round_error_recorded_not_raised(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()
    fetch.set(TOPSTORIES, RuntimeError('firebase down'))
    asyncio.run(mgr.poll_once())  # must not raise
    assert 'firebase down' in (db.get_meta('hn_last_error') or '')


# --- hckrnews historical backfill ---------------------------------------------


def _set_backfill_data(fetch, days, first_id=1000):
    """Provide hckrnews day lists + firebase items for the given date list."""
    sid = first_id
    by_day = {}
    for day in days:
        ids = [sid, sid + 1]
        fetch.set(hckr_url(day), [{'id': i} for i in ids])
        for i in ids:
            fetch.set(
                item_url(i), story(i, time=unix(datetime.combine(day, datetime.min.time()) + timedelta(hours=10)))
            )
        by_day[day] = ids
        sid += 10
    return by_day


def test_backfill_on_subscribe_fills_eligible_days(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()
    fetch.set(TOPSTORIES, [])

    eligible = [TODAY - timedelta(days=d) for d in range(2, 8)]  # -7 .. -2
    by_day = _set_backfill_data(fetch, eligible)

    mgr.schedule_backfill()
    asyncio.run(mgr.poll_once())

    # 6 hckrnews requests, one per eligible day; yesterday/today stay pending
    assert sum(1 for u in fetch.calls if 'hckrnews.com' in u) == 6
    pending = json.loads(db.get_meta('hn_backfill_pending'))
    assert sorted(pending) == sorted([str(TODAY), str(TODAY - timedelta(days=1))])

    day = eligible[0]
    s = db.get_hn_story(by_day[day][0])
    assert bool(s.backfilled)
    assert s.day == str(day)
    # first_seen_at approximated from submit time, clamped inside the archive day
    assert s.first_seen_at.date() == day


def test_backfill_clamps_first_seen_into_archive_day(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()
    fetch.set(TOPSTORIES, [])

    day = TODAY - timedelta(days=3)
    # submitted long before the archive day -> clamped to the day's start
    fetch.set(hckr_url(day), [{'id': 500}])
    fetch.set(item_url(500), story(500, time=unix(NOW - timedelta(days=30))))
    db.set_meta('hn_backfill_pending', json.dumps([str(day)]))
    asyncio.run(mgr.poll_once())

    s = db.get_hn_story(500)
    assert s.first_seen_at == datetime.combine(day, datetime.min.time())
    assert s.day == str(day)


def test_backfill_failed_day_stays_pending_and_retries(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()
    fetch.set(TOPSTORIES, [])

    good = TODAY - timedelta(days=2)
    bad = TODAY - timedelta(days=3)
    _set_backfill_data(fetch, [good])
    fetch.set(hckr_url(bad), RuntimeError('hckrnews 503'))
    db.set_meta('hn_backfill_pending', json.dumps([str(good), str(bad)]))

    asyncio.run(mgr.poll_once())
    assert json.loads(db.get_meta('hn_backfill_pending')) == [str(bad)]

    # the failed day is retried on a later round once the source recovers
    fetch.set(hckr_url(bad), [{'id': 600}])
    fetch.set(item_url(600), story(600))
    asyncio.run(mgr.poll_once())
    assert json.loads(db.get_meta('hn_backfill_pending')) == []
    assert db.get_hn_story(600) is not None


def test_backfill_pending_day_completes_once_two_days_old(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()
    fetch.set(TOPSTORIES, [])

    yesterday = TODAY - timedelta(days=1)
    db.set_meta('hn_backfill_pending', json.dumps([str(yesterday)]))

    # too fresh today -> untouched
    asyncio.run(mgr.poll_once())
    assert json.loads(db.get_meta('hn_backfill_pending')) == [str(yesterday)]
    assert not any('hckrnews.com' in u for u in fetch.calls)

    # two days later it becomes eligible and gets fetched
    mgr._now = lambda: NOW + timedelta(days=2)
    _set_backfill_data(fetch, [yesterday])
    asyncio.run(mgr.poll_once())
    assert json.loads(db.get_meta('hn_backfill_pending')) == []


def test_backfill_requests_are_throttled(env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()
    fetch.set(TOPSTORIES, [])
    mgr.backfill_day_interval = 3
    sleeps = []

    async def record_sleep(seconds):
        sleeps.append(seconds)

    mgr._sleep = record_sleep

    eligible = [TODAY - timedelta(days=d) for d in range(2, 8)]
    _set_backfill_data(fetch, eligible)
    db.set_meta('hn_backfill_pending', json.dumps([str(d) for d in eligible]))
    asyncio.run(mgr.poll_once())

    # serial day fetches spaced by the interval
    assert sleeps.count(3) >= len(eligible) - 1


def test_backfill_disabled_by_config(env, monkeypatch):
    monkeypatch.setenv('CONDENSER_HN_BACKFILL_DAYS', '0')
    from condenser.config import get_settings

    get_settings.cache_clear()
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()
    fetch.set(TOPSTORIES, [])

    mgr.schedule_backfill()
    assert db.get_meta('hn_backfill_pending') in (None, '[]')
    asyncio.run(mgr.poll_once())
    assert not any('hckrnews.com' in u for u in fetch.calls)


# --- endpoints ----------------------------------------------------------------


def _client():
    return TestClient(create_app())


def _login(client):
    r = client.post('/api/auth/login', json={'password': 'pw'})
    assert r.status_code == 200


def _quiet_hn(client):
    """Neutralize the app's real HN manager: no network, no background poll race."""
    hn = client.app.state.hn
    hn._fetch_json = FakeFetch()
    hn.kick = lambda: None
    return hn


def test_hn_subscription_lifecycle_endpoints(env):
    with _client() as client:
        _login(client)
        _quiet_hn(client)

        # add -> row + default config + backfill scheduled
        r = client.post('/api/sources/hn/subscriptions', json={'channel_id': 'front'})
        assert r.status_code == 200
        sub = db.get_hn_subscription('front')
        assert sub is not None and sub.name == 'Hacker News Front Page'
        assert json.loads(sub.config)['display_mode'] == 'top20'
        st = client.get('/api/hn/status').json()
        assert st['subscribed'] is True and st['enabled'] is True
        assert len(st['backfill_pending_days']) == 8  # -7..0 with the default 7-day window

        # idempotent re-add
        assert client.post('/api/sources/hn/subscriptions', json={'channel_id': 'front'}).status_code == 200

        # only the front feed exists in v1
        assert client.post('/api/sources/hn/subscriptions', json={'channel_id': 'ask'}).status_code == 422

        # the TG subscription list must not leak the HN row
        assert client.get('/api/subscriptions').json() == []

        # patch: enabled toggle + display-mode config
        assert client.patch('/api/sources/hn/subscriptions/front', json={'enabled': False}).status_code == 200
        assert not bool(db.get_hn_subscription('front').enabled)
        assert client.get('/api/hn/status').json()['enabled'] is False
        r = client.patch('/api/sources/hn/subscriptions/front', json={'config': {'display_mode': 'top10'}})
        assert r.status_code == 200
        assert json.loads(db.get_hn_subscription('front').config)['display_mode'] == 'top10'

        # delete: unsubscribes but keeps archived stories
        db.insert_hn_story(id=900, title='kept', first_seen_at=NOW, day=str(TODAY), score=1, comments_count=0)
        assert client.delete('/api/sources/hn/subscriptions/front').status_code == 200
        assert db.get_hn_subscription('front') is None
        assert db.get_hn_story(900) is not None
        assert client.get('/api/hn/status').json()['subscribed'] is False

        # patch/delete on a missing subscription -> 404
        assert client.patch('/api/sources/hn/subscriptions/front', json={'enabled': True}).status_code == 404
        assert client.delete('/api/sources/hn/subscriptions/front').status_code == 404


def test_hn_status_reports_story_counts(env):
    # the app's manager runs on the real clock, so "today" must too
    real_today = datetime.now(timezone.utc).date()
    with _client() as client:
        _login(client)
        _quiet_hn(client)
        db.insert_hn_story(id=1, title='today', first_seen_at=NOW, day=str(real_today), score=1, comments_count=0)
        db.insert_hn_story(
            id=2,
            title='older',
            first_seen_at=NOW - timedelta(days=3),
            day=str(real_today - timedelta(days=3)),
            score=2,
            comments_count=0,
        )
        db.set_meta('hn_last_poll_at', '2026-07-19 11:50:00')
        db.set_meta('hn_last_error', '')

        st = client.get('/api/hn/status').json()
        assert st['stories_total'] == 2
        assert st['stories_today'] == 1
        assert st['last_poll_at'] == '2026-07-19 11:50:00'
        assert st['last_error'] is None
