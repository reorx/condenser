"""Behavior tests for the daily cleanup mechanism.

The X archive is the only source whose growth is a problem — measured on
production, ~700 feed rows/day at ~1.7 KB a body, i.e. ~440 MB/year, half the
database. So a daily round deletes what nobody engaged with once it is old
enough, and everything the reader *did* touch stays forever.

Two things about these tests are worth knowing before reading them:

* The rule reads backwards at first glance. This is **not** cache eviction —
  an *unread* old row is what gets deleted, and a *read* one is kept, the same
  as Telegram history and HN stories never expire. What is being reclaimed is a
  firehose backlog nobody will ever scroll back to.
* The daily cadence is a **database** breakpoint, not a timer. ``git push`` to
  master is a production deploy here, so the process restarts far more often
  than once a day and an in-memory timer would rarely survive to fire.
  ``test_the_breakpoint_survives_a_fresh_manager`` is the one that actually
  pins that property.
"""

import asyncio
import json
import os
import threading
from datetime import datetime, timedelta, timezone

from telememo import db as tdb

from condenser import cleanup, db
from condenser.config import get_settings

NOW = datetime(2026, 8, 7, 12, 0)


# --- seeding helpers ------------------------------------------------------------


def setup_db(monkeypatch, **overrides) -> None:
    for key, value in {'CONDENSER_CLEANUP_X_RETENTION_DAYS': '15', **overrides}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    db.init_db(os.environ['CONDENSER_DB_PATH'])


def make_manager(rules=None, now=NOW, **kwargs) -> cleanup.CleanupManager:
    mgr = cleanup.CleanupManager(get_settings(), rules=rules, **kwargs)
    mgr._now = lambda: now
    return mgr


def tweet(tweet_id: int, *, days_ago: float = 30, quote_of=None, text='hello', now=NOW) -> None:
    db.XTweet.create(
        id=tweet_id,
        author_handle='someone',
        text=text,
        quote_of=quote_of,
        created_at=now - timedelta(days=days_ago),
        fetched_at=now - timedelta(days=days_ago),
    )


def feed_row(tweet_id: int, *, feed='foryou', days_ago: float = 30, now=NOW) -> None:
    db.XFeedItem.create(channel_id=feed, tweet_id=tweet_id, first_seen_at=now - timedelta(days=days_ago))


def archived(tweet_id: int, *, days_ago: float = 30, feed='foryou', now=NOW, **kwargs) -> None:
    """A tweet as it exists after ingest: a body plus one feed appearance."""
    tweet(tweet_id, days_ago=days_ago, now=now, **kwargs)
    feed_row(tweet_id, feed=feed, days_ago=days_ago, now=now)


def mark_read(tweet_id: int) -> None:
    db.ReadItem.create(source='x', ref1=tweet_id, ref2=0, read_at=NOW)


def hide(tweet_id: int) -> None:
    db.HiddenItem.create(source='x', ref1=tweet_id, ref2=0, hidden_at=NOW)


def label(tweet_id: int, verdict: str = 'down') -> None:
    db.set_feedback(db.ItemKey(source='x', ref1=tweet_id), verdict)


def save(tweet_id: int) -> None:
    db.add_saved_item('x', tweet_id, 0, {'source': 'x'})


def embed(tweet_id: int, *, days_ago: float = 0) -> None:
    db.upsert_x_embedding(tweet_id, b'\x00' * 16, 'fake@256', NOW - timedelta(days=days_ago))


def describe(tweet_id: int) -> None:
    db.upsert_x_attributes(tweet_id, ['topic'], [], 'fake@v1', NOW)


def tweet_ids() -> set:
    return {row.id for row in db.XTweet.select(db.XTweet.id)}


def feed_keys() -> set:
    return {(row.channel_id, row.tweet_id) for row in db.XFeedItem.select()}


def attribute_ids() -> set:
    return {row.tweet_id for row in db.XAttribute.select(db.XAttribute.tweet_id)}


class FakeRule:
    """A rule that records its calls — lets the framework tests stay off X's SQL."""

    def __init__(self, name='fake', counts=None, enabled=True, error=None):
        self.name = name
        self.calls = 0
        self._counts = counts or {'rows': 1}
        self._enabled = enabled
        self._error = error

    def enabled(self, settings) -> bool:
        return self._enabled

    def run(self, now, settings) -> cleanup.CleanupReport:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return cleanup.CleanupReport(rule=self.name, counts=dict(self._counts))


# --- the daily breakpoint -------------------------------------------------------


def test_the_very_first_round_is_due(env, monkeypatch):
    """A fresh install has no breakpoint, and must not wait a day to get one."""
    setup_db(monkeypatch)
    assert make_manager().due() is True


def test_a_round_is_not_due_before_the_interval_elapses(env, monkeypatch):
    setup_db(monkeypatch)
    make_manager().run_once()

    assert make_manager(now=NOW + timedelta(hours=23)).due() is False


def test_a_round_is_due_again_after_the_interval(env, monkeypatch):
    setup_db(monkeypatch)
    make_manager().run_once()

    assert make_manager(now=NOW + timedelta(hours=24)).due() is True


def test_the_breakpoint_survives_a_fresh_manager(env, monkeypatch):
    """The point of storing it in app_meta rather than in the loop: a deploy
    restarts the process, and the schedule has to outlive the object."""
    setup_db(monkeypatch)
    make_manager().run_once()
    stored = db.get_meta(cleanup.LAST_RUN_META_KEY)

    # a brand-new manager, as after a restart — it reads the breakpoint, not a timer
    assert stored
    assert make_manager(now=NOW + timedelta(hours=1)).due() is False
    assert make_manager(now=NOW + timedelta(days=2)).due() is True


def test_an_unparseable_breakpoint_is_treated_as_never_run(env, monkeypatch):
    """A corrupted value must not wedge the loop shut forever."""
    setup_db(monkeypatch)
    db.set_meta(cleanup.LAST_RUN_META_KEY, 'not-a-timestamp')

    assert make_manager().due() is True


def test_run_once_ignores_the_daily_gate(env, monkeypatch):
    """The gate belongs to the scheduler, not to the work — so a test (or a
    future manual trigger) can force a round without rewriting the schedule."""
    setup_db(monkeypatch)
    rule = FakeRule()
    mgr = make_manager(rules=[rule])
    mgr.run_once()
    mgr.run_once()

    assert rule.calls == 2


# --- the rule framework ---------------------------------------------------------


def test_a_failing_rule_is_reported_and_the_other_rules_still_run(env, monkeypatch):
    """Isolation is per rule: a broken future HN rule must not cost X its sweep."""
    setup_db(monkeypatch)
    broken = FakeRule(name='broken', error=RuntimeError('boom'))
    healthy = FakeRule(name='healthy', counts={'rows': 7})

    run = make_manager(rules=[broken, healthy]).run_once()

    assert run.report('broken').error == 'boom'
    assert run.report('healthy').counts == {'rows': 7}
    assert healthy.calls == 1


def test_a_failing_rule_beside_a_working_one_still_advances_the_breakpoint(env, monkeypatch):
    """The round got something done. Re-running the healthy rule every hour buys
    nothing — the failure is visible in status instead."""
    setup_db(monkeypatch)
    rules = [FakeRule(name='broken', error=RuntimeError('boom')), FakeRule(name='healthy')]
    make_manager(rules=rules).run_once()

    assert make_manager(now=NOW + timedelta(hours=1)).due() is False


def test_a_round_where_every_rule_failed_retries_on_the_next_check(env, monkeypatch):
    """Nothing got done, and the likeliest reason is a transient write lock held
    by realtime ingest — that deserves an hour's wait, not a lost day."""
    setup_db(monkeypatch)
    make_manager(rules=[FakeRule(error=RuntimeError('database is locked'))]).run_once()

    assert db.get_meta(cleanup.LAST_RUN_META_KEY) in (None, '')
    assert make_manager(now=NOW + timedelta(hours=1)).due() is True
    assert make_manager().status()['last_error'] == 'database is locked'


def test_a_disabled_rule_is_skipped_and_says_so(env, monkeypatch):
    setup_db(monkeypatch)
    rule = FakeRule(enabled=False)

    run = make_manager(rules=[rule]).run_once()

    assert rule.calls == 0
    assert run.report('fake').skipped_reason == 'disabled'
    assert run.deleted == 0


def test_the_x_rule_can_be_switched_off_on_its_own(env, monkeypatch):
    """Every rule owns an enable flag, independent of the loop's master switch."""
    setup_db(monkeypatch, CONDENSER_CLEANUP_X_ENABLED='false')
    archived(101, days_ago=30)

    run = make_manager().run_once()

    assert run.report('x_retention').skipped_reason == 'disabled'
    assert tweet_ids() == {101}


async def test_the_master_switch_spawns_no_loop_at_all(env, monkeypatch):
    """Off means the task does not exist, not that each round no-ops."""
    setup_db(monkeypatch, CONDENSER_CLEANUP_ENABLED='false')
    mgr = make_manager()
    await mgr.startup()

    assert mgr._tasks == set()
    await mgr.shutdown()


async def test_the_loop_survives_a_crashing_round(env, monkeypatch):
    """Anything a round can throw — a DB error outside run_once's own guards —
    must not take the daily sweep down until the next deploy."""
    setup_db(monkeypatch, CONDENSER_CLEANUP_CHECK_INTERVAL='0')
    mgr = make_manager()
    crashes = []

    def explode():
        crashes.append(1)
        raise RuntimeError('poll exploded')

    mgr._tick = explode
    task = asyncio.create_task(mgr._loop())
    for _ in range(10):
        await asyncio.sleep(0)
    task.cancel()

    assert len(crashes) > 1  # it came back round after the first crash


def test_status_reports_the_same_numbers_it_stored(env, monkeypatch):
    """One shape for the log line, app_meta and the endpoint — not three."""
    setup_db(monkeypatch)
    run = make_manager(rules=[FakeRule(counts={'rows': 3})]).run_once()

    status = make_manager().status()
    assert status['last_run_at']
    assert status['last_error'] is None
    assert status['last_report'] == run.as_dict()
    assert json.loads(db.get_meta(cleanup.LAST_REPORT_META_KEY)) == run.as_dict()


# --- the X rule: feed rows ------------------------------------------------------


def test_an_old_untouched_feed_row_is_deleted(env, monkeypatch):
    setup_db(monkeypatch)
    archived(101, days_ago=16)

    run = make_manager().run_once()

    assert feed_keys() == set()
    assert run.report('x_retention').counts['feed_items'] == 1


def test_a_recent_feed_row_is_kept(env, monkeypatch):
    """The age gate on its own — nothing was engaged with here either."""
    setup_db(monkeypatch)
    archived(101, days_ago=14)

    make_manager().run_once()

    assert feed_keys() == {('foryou', 101)}
    assert tweet_ids() == {101}


def test_a_feed_row_is_kept_while_the_probe_still_pushes_the_tweet(env, monkeypatch):
    """`fetched_at` is refreshed by every re-push, so it says "still live in some
    feed window". Deleting such an appearance would not reclaim anything — the
    next push recreates it with a fresh first_seen_at, and a tweet the reader
    ignored for weeks resurfaces at the top of the unread list."""
    setup_db(monkeypatch)
    tweet(101, days_ago=1)  # re-pushed today, so the body is young
    feed_row(101, days_ago=30)  # but first sighted a month ago

    make_manager().run_once()

    assert feed_keys() == {('foryou', 101)}
    assert tweet_ids() == {101}


def test_the_feed_row_goes_once_the_probe_stops_seeing_it(env, monkeypatch):
    """The other half of the guard: the clock starts when the pushes stop."""
    setup_db(monkeypatch)
    archived(101, days_ago=30)

    make_manager().run_once()

    assert feed_keys() == set()
    assert tweet_ids() == set()


def test_a_read_feed_row_is_kept_forever(env, monkeypatch):
    """The counter-intuitive core of the rule, stated as a test: reading a tweet
    is what makes it permanent, not what makes it disposable."""
    setup_db(monkeypatch)
    archived(101, days_ago=400)
    mark_read(101)

    make_manager().run_once()

    assert feed_keys() == {('foryou', 101)}
    assert tweet_ids() == {101}


def test_a_hidden_feed_row_is_kept(env, monkeypatch):
    """Hiding is an explicit judgement, not indifference — and a hidden tweet
    can never acquire a read marker, so the age rule alone would sweep it."""
    setup_db(monkeypatch)
    archived(101, days_ago=400)
    hide(101)

    make_manager().run_once()

    assert feed_keys() == {('foryou', 101)}
    assert tweet_ids() == {101}


def test_a_labeled_feed_row_is_kept(env, monkeypatch):
    """Labels are the verdict's training set, and channels D and A re-read
    x_tweets.text / author_handle on every round — deleting a labeled body
    would gut training silently, since nothing here has a foreign key."""
    setup_db(monkeypatch)
    archived(101, days_ago=400)
    archived(102, days_ago=400)
    label(101, 'down')
    label(102, 'up')

    make_manager().run_once()

    assert tweet_ids() == {101, 102}
    assert feed_keys() == {('foryou', 101), ('foryou', 102)}


def test_a_saved_feed_row_is_kept(env, monkeypatch):
    setup_db(monkeypatch)
    archived(101, days_ago=400)
    save(101)

    make_manager().run_once()

    assert tweet_ids() == {101}


# --- the X rule: tweet bodies ---------------------------------------------------


def test_a_body_goes_once_its_only_feed_row_is_gone(env, monkeypatch):
    setup_db(monkeypatch)
    archived(101, days_ago=16)

    run = make_manager().run_once()

    assert tweet_ids() == set()
    assert run.report('x_retention').counts['tweets'] == 1


def test_a_body_survives_while_any_feed_row_survives(env, monkeypatch):
    """One tweet can appear in several feeds. Read state is per tweet id, so the
    read appearance keeps *both* rows — but the shape has to hold even when only
    one appearance is young enough to stay."""
    setup_db(monkeypatch)
    tweet(101, days_ago=16)
    feed_row(101, feed='foryou', days_ago=16)
    feed_row(101, feed='following', days_ago=2)

    make_manager().run_once()

    assert feed_keys() == {('following', 101)}
    assert tweet_ids() == {101}


def test_a_body_goes_when_every_appearance_is_gone(env, monkeypatch):
    setup_db(monkeypatch)
    tweet(101, days_ago=16)
    feed_row(101, feed='foryou', days_ago=16)
    feed_row(101, feed='following', days_ago=20)

    make_manager().run_once()

    assert feed_keys() == set()
    assert tweet_ids() == set()


def test_a_quoted_body_survives_while_the_quoting_tweet_does(env, monkeypatch):
    """An embedded quote has no feed row of its own and would otherwise look
    like garbage — but deleting it blanks the quote block on a card that is
    still being shown, and no foreign key would stop it."""
    setup_db(monkeypatch)
    tweet(900, days_ago=40)  # the quoted tweet: body only, never in a feed
    archived(101, days_ago=2, quote_of=900)  # a live card that quotes it

    make_manager().run_once()

    assert tweet_ids() == {101, 900}


def test_a_quote_chain_drains_in_a_single_round(env, monkeypatch):
    """101 quotes 900 quotes 901. A single DELETE sees the pre-statement state,
    so 900 would shield 901 for a day and 901 would linger another — measured on
    a production snapshot, one pass leaves 17.5% of the deletable bodies behind.
    The sweep therefore repeats until it finds nothing: X quotes always point at
    an older tweet, so the graph is acyclic and this terminates."""
    setup_db(monkeypatch)
    tweet(901, days_ago=42)
    tweet(900, days_ago=41, quote_of=901)
    archived(101, days_ago=16, quote_of=900)

    run = make_manager().run_once()

    assert tweet_ids() == set()
    assert run.report('x_retention').counts['tweets'] == 3


def test_a_labeled_body_survives_with_no_feed_row_at_all(env, monkeypatch):
    """The exemption has to hold on the body sweep too, not just on feed rows —
    a labeled tweet whose feed row was never created is still training data."""
    setup_db(monkeypatch)
    tweet(900, days_ago=40)
    label(900, 'down')

    make_manager().run_once()

    assert tweet_ids() == {900}


def test_a_saved_or_hidden_body_survives_with_no_feed_row(env, monkeypatch):
    setup_db(monkeypatch)
    tweet(900, days_ago=40)
    tweet(901, days_ago=40)
    save(900)
    hide(901)

    make_manager().run_once()

    assert tweet_ids() == {900, 901}


def test_a_recent_orphan_body_is_kept(env, monkeypatch):
    """fetched_at is the body's own clock — a quote embedded in today's push is
    not garbage just because it has no feed row."""
    setup_db(monkeypatch)
    tweet(900, days_ago=1)

    make_manager().run_once()

    assert tweet_ids() == {900}


def test_the_pre_existing_orphan_backlog_is_collected(env, monkeypatch):
    """Embedded quotes and Following's out-of-window thread ancestors are
    archived body-only and never had a feed row, so a feed-scoped rule would
    never reach them — on production they are ~13% of the table and growing."""
    setup_db(monkeypatch)
    for tweet_id in (900, 901, 902):
        tweet(tweet_id, days_ago=40)

    run = make_manager().run_once()

    assert tweet_ids() == set()
    assert run.report('x_retention').counts['tweets'] == 3


# --- the X rule: the rebuildable caches -----------------------------------------


def test_deleting_a_body_takes_its_embedding_and_attributes_with_it(env, monkeypatch):
    """Both are caches keyed by tweet id with no foreign key. Once the text is
    gone neither can ever be rebuilt, so leaving them is pure dangling data."""
    setup_db(monkeypatch)
    archived(101, days_ago=16)
    embed(101)
    describe(101)

    run = make_manager().run_once()

    assert db.x_embedding_ids() == set()
    assert attribute_ids() == set()
    assert run.report('x_retention').counts['embeddings_orphaned'] == 1
    assert run.report('x_retention').counts['attributes_orphaned'] == 1


def test_cache_rows_orphaned_before_this_rule_existed_are_swept_too(env, monkeypatch):
    """An anti-join rather than a list of ids deleted this round, so the sweep
    self-heals a backlog it did not create."""
    setup_db(monkeypatch)
    embed(555)  # no x_tweets row has ever existed for this id
    describe(555)

    make_manager().run_once()

    assert db.x_embedding_ids() == set()
    assert attribute_ids() == set()


def test_a_surviving_body_keeps_its_caches(env, monkeypatch):
    setup_db(monkeypatch)
    archived(101, days_ago=2)
    embed(101)
    describe(101)

    make_manager().run_once()

    assert db.x_embedding_ids() == {101}
    assert attribute_ids() == {101}


def test_an_unlabeled_vector_expires_on_its_own_window(env, monkeypatch):
    """A live tweet's vector is read once, at judge time, and is re-derivable
    from the text — so it expires on its own (longer) clock while the body
    stays. This used to run at the tail of a verdict round, behind the
    cold-start gate; on an install that never opened that gate it never ran."""
    setup_db(monkeypatch, CONDENSER_EMBEDDING_RETENTION_DAYS='90')
    archived(101, days_ago=2)
    embed(101, days_ago=91)

    run = make_manager().run_once()

    assert tweet_ids() == {101}
    assert db.x_embedding_ids() == set()
    assert run.report('x_retention').counts['embeddings_expired'] == 1


def test_a_labeled_vector_never_expires(env, monkeypatch):
    """It is the training set, not a cache."""
    setup_db(monkeypatch, CONDENSER_EMBEDDING_RETENTION_DAYS='90')
    archived(101, days_ago=2)
    embed(101, days_ago=400)
    label(101, 'up')

    make_manager().run_once()

    assert db.x_embedding_ids() == {101}


def test_zero_disables_embedding_expiry(env, monkeypatch):
    setup_db(monkeypatch, CONDENSER_EMBEDDING_RETENTION_DAYS='0')
    archived(101, days_ago=2)
    embed(101, days_ago=4000)

    make_manager().run_once()

    assert db.x_embedding_ids() == {101}


# --- VACUUM ---------------------------------------------------------------------


def test_vacuum_runs_when_the_freed_fraction_clears_the_threshold(env, monkeypatch):
    setup_db(monkeypatch, CONDENSER_CLEANUP_VACUUM_THRESHOLD='0.2')
    archived(101, days_ago=16)
    calls = []
    run = make_manager(freelist_ratio=lambda: 0.5, vacuum=lambda: calls.append(1)).run_once()

    assert calls == [1]
    assert run.vacuumed is True


def test_vacuum_is_skipped_at_or_below_the_threshold(env, monkeypatch):
    setup_db(monkeypatch, CONDENSER_CLEANUP_VACUUM_THRESHOLD='0.2')
    archived(101, days_ago=16)
    calls = []
    run = make_manager(freelist_ratio=lambda: 0.2, vacuum=lambda: calls.append(1)).run_once()

    assert calls == []
    assert run.vacuumed is False


def test_vacuum_is_skipped_when_the_round_deleted_nothing(env, monkeypatch):
    """The common case for the first weeks: at a 15-day window there is simply
    nothing old enough yet. Rewriting the whole file to reclaim nothing would be
    an exclusive lock for no reason."""
    setup_db(monkeypatch, CONDENSER_CLEANUP_VACUUM_THRESHOLD='0.0')
    measured = []

    def ratio():
        measured.append(1)
        return 0.9

    run = make_manager(freelist_ratio=ratio, vacuum=lambda: None).run_once()

    assert measured == []  # not even measured
    assert run.vacuumed is False
    assert run.freelist_ratio is None


def test_a_failed_vacuum_does_not_lose_the_round(env, monkeypatch):
    """The deletions are already committed; re-running them buys nothing. A
    write lock held by realtime ingest is a normal, transient reason to fail."""
    setup_db(monkeypatch, CONDENSER_CLEANUP_VACUUM_THRESHOLD='0.0')
    archived(101, days_ago=16)

    def boom():
        raise RuntimeError('database is locked')

    run = make_manager(freelist_ratio=lambda: 0.9, vacuum=boom).run_once()

    assert run.vacuumed is False
    assert run.vacuum_error == 'database is locked'
    assert tweet_ids() == set()  # the sweep itself still happened
    assert make_manager(now=NOW + timedelta(hours=1)).due() is False


def test_vacuum_really_runs_outside_the_transaction(env, monkeypatch):
    """The one unmocked VACUUM. SQLite refuses to vacuum inside a transaction
    ('cannot VACUUM from within a transaction'), so this is the engine itself
    checking that the sweep's atomic() block has closed before we get here."""
    setup_db(monkeypatch, CONDENSER_CLEANUP_VACUUM_THRESHOLD='0.0')
    for tweet_id in range(1000, 1080):
        archived(tweet_id, days_ago=16, text='x' * 4000)

    run = make_manager().run_once()

    assert tweet_ids() == set()
    assert db.sqlite_freelist_ratio() == 0.0  # everything reclaimed
    assert run.vacuumed is True
    assert run.vacuum_error is None


# --- wiring ---------------------------------------------------------------------


async def test_a_round_runs_on_a_worker_thread(env, monkeypatch):
    """VACUUM takes an exclusive lock and this process runs FastAPI, the
    Telegram listener, HN sampling and the verdict on one event loop — a
    multi-second rewrite on that loop would stall realtime ingest. peewee's
    connections are thread-local, so the worker gets its own and hands it back."""
    setup_db(monkeypatch)
    archived(101, days_ago=16)
    observed = {}
    mgr = make_manager()
    original = mgr._run_in_thread

    def wrapped():
        try:
            return original()
        finally:
            # inside the worker, after run_once and its connection handback
            observed['thread'] = threading.current_thread()
            observed['closed'] = tdb.db.is_closed()

    mgr._run_in_thread = wrapped
    run = await mgr._tick()

    assert observed['thread'] is not threading.main_thread()
    assert observed['closed'] is True  # the pooled worker did not keep a handle open
    assert run.deleted == 2  # the feed row and the body
    assert tweet_ids() == set()


def test_status_before_any_round_says_so(env, monkeypatch):
    setup_db(monkeypatch)
    status = make_manager().status()

    assert status['last_run_at'] is None
    assert status['last_report'] is None
    assert status['rules'] == [
        {'rule': 'x_retention', 'enabled': True},
        {'rule': 'rss_retention', 'enabled': True},
    ]


def test_the_endpoint_distinguishes_ran_from_deleted_nothing(env, monkeypatch):
    """At a 15-day window the first weeks legitimately delete nothing (measured:
    the oldest production row is 13 days old), so 'never ran' and 'ran and found
    nothing' must not look the same from outside. Booting the app is enough to
    produce the second — the loop's first iteration runs a round immediately."""
    from fastapi.testclient import TestClient

    from condenser.app import create_app

    setup_db(monkeypatch)
    # Seeded against the real clock, not the module's fixed NOW: this test boots the
    # real app, whose startup round runs at wall time — anchored to NOW the fixture
    # crosses the 15-day retention window as the calendar advances (rotted 2026-08-21).
    archived(101, days_ago=2, now=datetime.now(timezone.utc).replace(tzinfo=None))
    with TestClient(create_app()) as client:
        client.post('/api/auth/login', json={'password': 'pw'})
        status = client.get('/api/cleanup/status').json()

    assert status['last_run_at'] is not None
    assert status['last_error'] is None
    assert status['last_report']['deleted'] == 0
    assert tweet_ids() == {101}
