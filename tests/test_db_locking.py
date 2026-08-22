"""Reproduces the intermittent ``database is locked`` and pins the fix (TDD).

Mechanism, verified by these tests rather than assumed: a **deferred**
``atomic()`` that reads before it writes takes a read snapshot at its first
SELECT. If any other connection commits a write before the transaction's own
first write, SQLite refuses to upgrade it (``SQLITE_BUSY_SNAPSHOT`` under WAL)
and — unlike ordinary contention — **never invokes the busy handler**, so
peewee's 5s connect timeout does not apply and ``database is locked`` is
immediate. Retrying inside the transaction cannot help either: the snapshot is
already stale and only a rollback clears it.

Production has this interleaving all day (Telethon ingest on the event loop,
FastAPI handlers on the threadpool, RSS ingest via ``asyncio.to_thread``,
cleanup rounds on a worker thread). In the test suite the writer that raced the
RSS endpoint tests is the cleanup **startup round**, whose ``set_meta`` writes
land regardless of whether anything was deleted.

The fix is ``atomic(lock_type='IMMEDIATE')`` on every read-then-write
transaction: BEGIN IMMEDIATE takes the write lock up front, so the transaction
never holds a read snapshot it must upgrade, and a concurrent writer waits in
the busy handler instead of failing. Only two functions have that shape —
``add_rss_subscription`` and ``migrate_rss_feed_url``; every other ``atomic()``
in the codebase issues a write as its first statement (a bare ``get_or_create``
runs its SELECT outside any transaction), which starts the transaction as a
writer and stays on the busy-handler path.

Each test freezes the transaction inside its read-to-write gap (by
monkeypatching the first write), commits a write from another connection, then
resumes — a deterministic replay of the interleaving. Red on deferred, green on
IMMEDIATE.
"""

import os
import threading

from telememo import db as tdb

from condenser import db

URL = 'https://example.com/feed.xml'


def _run_in_thread(fn):
    """Run ``fn`` on its own thread (= its own thread-local peewee connection)."""
    result = {}

    def worker():
        try:
            result['value'] = fn()
        except Exception as e:  # noqa: BLE001 — the exception is the assertion target
            result['error'] = e
        finally:
            if not tdb.db.is_closed():
                tdb.db.close()

    t = threading.Thread(target=worker)
    t.start()
    return t, result


def _commit_during_gap(monkeypatch, model, method, txn):
    """Run ``txn`` on a worker thread, pause it at ``model.method`` (its first
    write), commit an unrelated write from this thread's connection, resume.

    The pause is a bounded wait rather than a strict handshake: under IMMEDIATE
    the worker holds the write lock through the gap, so this thread's probe
    write *blocks* in the busy handler until the worker times out and commits —
    which is exactly the post-fix behavior being pinned.
    """
    in_gap = threading.Event()
    resume = threading.Event()
    real = getattr(model, method)

    def paused(cls, *args, **kwargs):
        in_gap.set()
        resume.wait(timeout=1.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(model, method, classmethod(paused))

    t, result = _run_in_thread(txn)
    assert in_gap.wait(timeout=5), 'transaction never reached its first write'
    db.set_meta('locking_probe', '1')  # any committed write invalidates the snapshot
    resume.set()
    t.join(timeout=15)
    assert not t.is_alive(), 'transaction thread wedged'
    assert 'error' not in result, f'concurrent writer broke the transaction: {result["error"]!r}'
    return result['value']


def test_add_rss_subscription_survives_a_concurrent_writer(env, monkeypatch):
    db.init_db(os.environ['CONDENSER_DB_PATH'])

    # get_or_create's created-path: SELECT (snapshot) -> Subscription.create (first write)
    _commit_during_gap(monkeypatch, db.Subscription, 'create', lambda: db.add_rss_subscription(URL))

    assert db.get_rss_subscription(URL) is not None
    assert db.get_rss_feed(URL) is not None


def test_migrate_rss_feed_url_survives_a_concurrent_writer(env, monkeypatch):
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    old, new = 'https://old.example.com/feed', 'https://new.example.com/feed'
    db.add_rss_subscription(old)

    # the taken-check exists() pair (snapshot) -> RssFeed.update (first write)
    moved = _commit_during_gap(monkeypatch, db.RssFeed, 'update', lambda: db.migrate_rss_feed_url(old, new))

    assert moved is True
    assert db.get_rss_feed(new) is not None and db.get_rss_feed(old) is None
    assert db.get_rss_subscription(new) is not None
