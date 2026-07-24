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
from condenser.preview import LinkPreview, normalize_url
from telememo import db as tdb

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


class FakePreview:
    """URL -> LinkPreview result (or Exception to raise). Records every call.

    Unknown URLs get a deterministic stub preview, so any test that ingests
    stories works without wiring preview data explicitly.
    """

    def __init__(self):
        self.results = {}
        self.calls = []

    def set(self, url, result):
        self.results[url] = result

    async def __call__(self, url):
        self.calls.append(url)
        r = self.results.get(url)
        if isinstance(r, Exception):
            raise r
        if r is None:
            return LinkPreview(url=url, title=f'Title {url}', description='Desc', site_name='Example')
        return r


_UNSET = object()


def make_manager(fetch, now=NOW, fetch_preview=_UNSET):
    """Build a network-free manager. ``fetch_preview`` defaults to a FakePreview
    (the canned story URLs are real domains — the real ``get_preview`` would hit
    the network); pass ``None`` explicitly to exercise the real cached path."""
    from condenser.config import get_settings
    from condenser.hn import HNManager

    db.init_db(os.environ['CONDENSER_DB_PATH'])
    if fetch_preview is _UNSET:
        fetch_preview = FakePreview()
    mgr = HNManager(get_settings(), fetch_json=fetch, fetch_preview=fetch_preview)
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

    # rollback safety (C1): pre-v3 code INSERTs without the source column;
    # the rebuilt table must default it to 'telegram'
    tdb.db.execute_sql(
        "INSERT INTO subscriptions (channel_id, enabled, backfill_done, added_at) VALUES (8, 1, 0, '2026-06-03 10:00:00')"
    )
    s8 = db.get_subscription(8)
    assert s8 is not None and s8.source == 'telegram'


def test_fresh_subscriptions_table_defaults_source_column(env):
    """A freshly created (never-migrated) table must survive old-code INSERTs too."""
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    tdb.db.execute_sql(
        "INSERT INTO subscriptions (channel_id, enabled, backfill_done, added_at) VALUES (9, 1, 0, '2026-06-03 10:00:00')"
    )
    s9 = db.get_subscription(9)
    assert s9 is not None and s9.source == 'telegram'


def test_add_subscription_coerces_str_channel_id(env):
    """channel_id has no SQLite affinity since v3 — the TG write entry must coerce to int (C2)."""
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    db.add_subscription('5')
    db.add_subscription(5)  # idempotent with the str form: still one row
    rows = db.list_subscriptions()
    assert len(rows) == 1
    assert rows[0].channel_id == 5 and isinstance(rows[0].channel_id, int)


def test_fresh_db_records_schema_version(env):
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    assert db.get_meta('schema_version') == str(db.SCHEMA_VERSION)
    assert db.SCHEMA_VERSION == 7


def test_hn_stories_table_migrates_to_v5(env):
    """A pre-v5 hn_stories table gains the preview columns in place, data intact."""
    path = os.environ['CONDENSER_DB_PATH']
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE hn_stories ('
        'id INTEGER NOT NULL PRIMARY KEY, title TEXT, url TEXT, domain TEXT, author TEXT, text TEXT, '
        'type VARCHAR(255) NOT NULL, submitted_at DATETIME, first_seen_at DATETIME NOT NULL, '
        'day VARCHAR(255) NOT NULL, score INTEGER NOT NULL, comments_count INTEGER NOT NULL, '
        'score_updated_at DATETIME, peak_rank INTEGER, is_dead INTEGER NOT NULL, backfilled INTEGER NOT NULL)'
    )
    conn.execute(
        'INSERT INTO hn_stories (id, title, url, type, first_seen_at, day, score, comments_count, is_dead, backfilled) '
        "VALUES (1, 'old', 'https://example.com/1', 'story', '2026-07-01 10:00:00', '2026-07-01', 5, 0, 0, 0)"
    )
    conn.commit()
    conn.close()

    db.init_db(path)
    s = db.get_hn_story(1)
    assert s.title == 'old'
    assert s.preview is None and s.preview_attempts == 0
    # the legacy row becomes a preview candidate
    assert [c.id for c in db.hn_stories_needing_preview(10, 3)] == [1]

    # idempotent: init again on the migrated file
    db.init_db(path)
    assert db.get_hn_story(1) is not None


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


def test_transient_null_survives_but_dead_flag_marks_dead(env):
    """A2: Firebase's transient nulls for live items must not permanently kill a story."""
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()

    fetch.set(TOPSTORIES, [1, 2])
    fetch.set(item_url(1), story(1))
    fetch.set(item_url(2), story(2))
    asyncio.run(mgr.poll_once())

    # story 1 hits a transient null -> stays live; story 2 flagged dead -> marked
    mgr._now = lambda: NOW + timedelta(hours=1)
    fetch.set(TOPSTORIES, [])
    fetch.set(item_url(1), None)
    fetch.set(item_url(2), story(2, dead=True))
    asyncio.run(mgr.poll_once())
    assert not bool(db.get_hn_story(1).is_dead)
    assert bool(db.get_hn_story(2).is_dead)

    # story 1 recovers next round and keeps refreshing; dead story 2 stays excluded
    mgr._now = lambda: NOW + timedelta(hours=2)
    n2 = fetch.count(item_url(2))
    fetch.set(item_url(1), story(1, score=77, descendants=9))
    asyncio.run(mgr.poll_once())
    s1 = db.get_hn_story(1)
    assert s1.score == 77 and s1.comments_count == 9
    assert fetch.count(item_url(2)) == n2


def test_loop_survives_poll_once_crash(env, monkeypatch):
    """A1: an exception escaping poll_once (e.g. DB locked before its guard) must not kill the loop."""
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()
    fetch.set(TOPSTORIES, [101])
    fetch.set(item_url(101), story(101))

    real_active = db.hn_sampling_active
    calls = {'n': 0}

    def flaky():
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('database is locked')
        return real_active()

    monkeypatch.setattr(db, 'hn_sampling_active', flaky)

    async def run():
        task = asyncio.create_task(mgr._loop())
        for _ in range(200):
            await asyncio.sleep(0)
            if db.get_hn_story(101) is not None:
                break
            mgr._wake.set()  # skip the inter-round wait
        alive = not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return alive

    assert asyncio.run(run())  # loop still alive after the crash round
    assert calls['n'] >= 2  # a second round actually ran
    assert db.get_hn_story(101) is not None


def test_null_front_item_not_refetched_every_round(env):
    """D2: an id whose item fetch returns null must not be re-pulled every round."""
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()

    fetch.set(TOPSTORIES, [1])
    fetch.set(item_url(1), None)
    asyncio.run(mgr.poll_once())
    assert fetch.count(item_url(1)) == 1

    # still on the front page next round: the placeholder row dedupes the fetch
    mgr._now = lambda: NOW + timedelta(minutes=10)
    asyncio.run(mgr.poll_once())
    assert fetch.count(item_url(1)) == 1


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


def test_backfill_completion_does_not_clobber_concurrent_schedule(env):
    """A3: a schedule_backfill landing mid-round must not be overwritten by the round's stale snapshot."""
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    subscribe_front()
    fetch.set(TOPSTORIES, [])

    day_a, day_b = TODAY - timedelta(days=3), TODAY - timedelta(days=2)
    db.set_meta('hn_backfill_pending', json.dumps([str(day_a), str(day_b)]))

    async def fake_backfill(day):
        if str(day) == str(day_a):
            mgr.schedule_backfill()  # a re-subscribe lands while the round is running

    mgr._backfill_day = fake_backfill
    asyncio.run(mgr.poll_once())

    pending = set(json.loads(db.get_meta('hn_backfill_pending')))
    # the freshly scheduled window survives, minus the two days this round completed
    expected = {str(TODAY - timedelta(days=d)) for d in range(8)} - {str(day_a), str(day_b)}
    assert pending == expected


def test_kick_safe_without_loop_and_wakes_across_threads(env):
    """B3: kick() must be a no-op before startup and thread-safe afterwards."""
    fetch = FakeFetch()
    mgr = make_manager(fetch)
    mgr.kick()  # no loop yet -> must not raise

    async def run():
        await mgr.startup()
        # cancel the sampling task so it can't consume the wake event first
        for t in list(mgr._tasks):
            t.cancel()
        await asyncio.sleep(0)
        await asyncio.to_thread(mgr.kick)  # threadpool caller, like the router endpoints
        await asyncio.wait_for(mgr._wake.wait(), timeout=2)

    asyncio.run(run())
    asyncio.run(mgr.shutdown())


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


# --- link preview prefetch (embedded HnCard previews) --------------------------


def test_new_story_preview_prefetched_and_persisted(env):
    fetch = FakeFetch()
    fp = FakePreview()
    mgr = make_manager(fetch, fetch_preview=fp)
    subscribe_front()

    fetch.set(TOPSTORIES, [101, 102])
    fetch.set(item_url(101), story(101))
    fetch.set(item_url(102), story(102, url=None, text='<p>Ask HN body</p>'))
    asyncio.run(mgr.poll_once())

    p = json.loads(db.get_hn_story(101).preview)
    assert p['title'] == 'Title https://example.com/101'
    assert p['description'] == 'Desc'
    # self-post: never a candidate, no attempt burned
    ask = db.get_hn_story(102)
    assert ask.preview is None and ask.preview_attempts == 0
    assert fp.calls == ['https://example.com/101']

    # a filled story is not refetched on later rounds
    asyncio.run(mgr.poll_once())
    assert fp.calls == ['https://example.com/101']


def test_empty_preview_result_is_terminal(env):
    """A successful fetch with no metadata is still a final state — no refetch loop."""
    fetch = FakeFetch()
    fp = FakePreview()
    fp.set('https://example.com/101', LinkPreview(url='https://example.com/101'))
    mgr = make_manager(fetch, fetch_preview=fp)
    subscribe_front()
    fetch.set(TOPSTORIES, [101])
    fetch.set(item_url(101), story(101))

    asyncio.run(mgr.poll_once())
    p = json.loads(db.get_hn_story(101).preview)
    assert p['title'] is None and p['error'] is None
    asyncio.run(mgr.poll_once())
    assert fp.calls == ['https://example.com/101']


def test_preview_backlog_filled_newest_first_within_batch(env, monkeypatch):
    """Backfilled + pre-feature rows are swept newest-first, capped per round; dead rows excluded."""
    monkeypatch.setenv('CONDENSER_HN_PREVIEW_BATCH', '2')
    from condenser.config import get_settings

    get_settings.cache_clear()
    fetch = FakeFetch()
    fp = FakePreview()
    mgr = make_manager(fetch, fetch_preview=fp)
    subscribe_front()
    fetch.set(TOPSTORIES, [])

    for sid, hours in ((1, 30), (2, 20), (3, 10)):
        seen = NOW - timedelta(hours=hours)
        db.insert_hn_story(
            id=sid, title=f'S{sid}', url=f'https://example.com/{sid}', first_seen_at=seen, day=str(seen.date())
        )
    db.insert_hn_story(id=4, url='https://example.com/4', first_seen_at=NOW, day=str(TODAY), is_dead=True)

    asyncio.run(mgr.poll_once())
    assert fp.calls == ['https://example.com/3', 'https://example.com/2']

    asyncio.run(mgr.poll_once())
    assert fp.calls[2:] == ['https://example.com/1']
    assert db.get_hn_story(4).preview is None  # dead placeholder: never a candidate


def test_failed_preview_retries_up_to_three_real_attempts(env):
    fetch = FakeFetch()
    fp = FakePreview()
    fp.set('https://example.com/101', LinkPreview(url='https://example.com/101', error='HTTP 500'))
    mgr = make_manager(fetch, fetch_preview=fp)
    subscribe_front()
    fetch.set(TOPSTORIES, [101])
    fetch.set(item_url(101), story(101))

    for expected in (1, 2, 3):
        asyncio.run(mgr.poll_once())
        assert db.get_hn_story(101).preview_attempts == expected
    # attempts exhausted: the seam is never called again
    asyncio.run(mgr.poll_once())
    assert len(fp.calls) == 3
    assert db.get_hn_story(101).preview is None


def test_fresh_negative_cache_skips_without_burning_attempts(env):
    """A fresh cached failure must not consume a retry (each bump = one real network attempt)."""
    fetch = FakeFetch()
    fp = FakePreview()
    mgr = make_manager(fetch, fetch_preview=fp)
    subscribe_front()
    fetch.set(TOPSTORIES, [101])
    fetch.set(item_url(101), story(101))

    db.upsert_preview(normalize_url('https://example.com/101'), ok=False, error='HTTP 500')
    asyncio.run(mgr.poll_once())
    assert fp.calls == []
    assert db.get_hn_story(101).preview_attempts == 0

    # once the negative entry ages past its TTL, the next round really retries
    stale = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    db.LinkPreviewCache.update(fetched_at=stale).execute()
    asyncio.run(mgr.poll_once())
    assert fp.calls == ['https://example.com/101']
    assert db.get_hn_story(101).preview is not None


def test_fresh_positive_cache_fills_preview_with_zero_network(env):
    """With a fresh ok cache row, even the real get_preview path stays offline."""
    fetch = FakeFetch()
    mgr = make_manager(fetch, fetch_preview=None)  # the real preview.get_preview
    subscribe_front()
    fetch.set(TOPSTORIES, [101])
    fetch.set(item_url(101), story(101))

    db.upsert_preview(normalize_url('https://example.com/101'), ok=True, title='Cached title', site_name='Example')
    asyncio.run(mgr.poll_once())
    p = json.loads(db.get_hn_story(101).preview)
    assert p['title'] == 'Cached title'


def test_preview_prefetch_disabled_by_config(env, monkeypatch):
    monkeypatch.setenv('CONDENSER_HN_PREVIEW_BATCH', '0')
    from condenser.config import get_settings

    get_settings.cache_clear()
    fetch = FakeFetch()
    fp = FakePreview()
    mgr = make_manager(fetch, fetch_preview=fp)
    subscribe_front()
    fetch.set(TOPSTORIES, [101])
    fetch.set(item_url(101), story(101))

    asyncio.run(mgr.poll_once())
    assert fp.calls == []
    assert db.get_hn_story(101).preview is None


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


def test_resubscribe_reenables_paused_subscription(env):
    """B1: POST means subscribe-and-enable — a paused row must come back enabled."""
    with _client() as client:
        _login(client)
        _quiet_hn(client)
        client.post('/api/sources/hn/subscriptions', json={'channel_id': 'front'})
        client.patch('/api/sources/hn/subscriptions/front', json={'enabled': False})
        assert not bool(db.get_hn_subscription('front').enabled)

        r = client.post('/api/sources/hn/subscriptions', json={'channel_id': 'front'})
        assert r.status_code == 200
        assert r.json()['enabled'] is True
        assert bool(db.get_hn_subscription('front').enabled)


def test_resubscribe_does_not_reschedule_backfill(env):
    """D1: an idempotent re-subscribe must not push completed days back into pending."""
    with _client() as client:
        _login(client)
        _quiet_hn(client)
        client.post('/api/sources/hn/subscriptions', json={'channel_id': 'front'})
        db.set_meta('hn_backfill_pending', '[]')  # simulate a finished backfill
        client.post('/api/sources/hn/subscriptions', json={'channel_id': 'front'})
        assert json.loads(db.get_meta('hn_backfill_pending')) == []


def test_source_disabled_rejects_writes_and_reports_status(env, monkeypatch):
    """B2: with CONDENSER_HN_ENABLED=false the sampler never runs — writes must not pretend otherwise."""
    monkeypatch.setenv('CONDENSER_HN_ENABLED', 'false')
    from condenser.config import get_settings

    get_settings.cache_clear()
    with _client() as client:
        _login(client)
        r = client.post('/api/sources/hn/subscriptions', json={'channel_id': 'front'})
        assert r.status_code == 503
        assert db.get_hn_subscription('front') is None
        assert client.get('/api/hn/status').json()['source_enabled'] is False

        # enabling an existing row is rejected too; pausing it is still allowed
        subscribe_front()
        assert client.patch('/api/sources/hn/subscriptions/front', json={'enabled': True}).status_code == 503
        assert client.patch('/api/sources/hn/subscriptions/front', json={'enabled': False}).status_code == 200


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
        assert st['source_enabled'] is True
