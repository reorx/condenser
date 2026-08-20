"""Daily data-cleanup loop: retention rules, then a VACUUM decision.

Why this exists: X is the only source whose growth is a problem. Measured on
production, it arrives at ~700 feed rows/day at ~1.7 KB a body — about
440 MB/year, and already half the database — while 92% of what it archives is
never opened. Telegram and Hacker News grow an order of magnitude slower and
are left alone.

Two structural decisions worth knowing:

* **The cadence is a database breakpoint, not a timer.** ``git push`` to master
  is a production deploy here, so the process restarts far more often than once
  a day; an in-memory ``sleep(24h)`` would reset every time and a daily job
  might never fire at all. The loop instead wakes hourly and asks app_meta when
  it last ran, so the round lands on time regardless of how often the process
  bounces.
* **The round runs on a worker thread.** FastAPI, the Telegram listener, HN
  sampling and the verdict all share one event loop, and VACUUM takes an
  exclusive lock for as long as it takes to rewrite the file. peewee's
  connections are thread-local — which is already how every sync route handler
  reaches the database — so the worker gets its own and hands it back.

A rule is anything with ``name``, ``enabled(settings)`` and
``run(now, settings) -> CleanupReport``; duck-typed because this codebase uses
neither ``abc`` nor ``typing.Protocol`` anywhere. Rules own their own internal
sequencing, so the X rule's four causally-chained steps cost a future
single-statement HN rule nothing.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from telememo import db as tdb

from . import db
from .config import Settings

log = logging.getLogger('condenser.cleanup')

LAST_RUN_META_KEY = 'cleanup_last_run_at'
LAST_ERROR_META_KEY = 'cleanup_last_error'
LAST_REPORT_META_KEY = 'cleanup_last_report'


@dataclass
class CleanupReport:
    """One rule's outcome. ``counts`` keys are the rule's own — forcing a shared
    schema would either starve a detailed rule or zero-fill a simple one."""

    rule: str
    counts: dict[str, int] = field(default_factory=dict)
    skipped_reason: Optional[str] = None  # 'disabled' | None
    error: Optional[str] = None  # recorded, never raised past the manager

    @property
    def deleted(self) -> int:
        return sum(self.counts.values())


@dataclass
class CleanupRun:
    """One round, across every rule. The single shape behind the log line, the
    app_meta record and the status endpoint — not three renderings of it."""

    started_at: datetime
    reports: list[CleanupReport] = field(default_factory=list)
    freelist_ratio: Optional[float] = None
    vacuumed: bool = False
    vacuum_error: Optional[str] = None

    @property
    def deleted(self) -> int:
        return sum(r.deleted for r in self.reports)

    def report(self, name: str) -> Optional[CleanupReport]:
        return next((r for r in self.reports if r.rule == name), None)

    def as_dict(self) -> dict:
        return {
            'started_at': self.started_at.isoformat(sep=' ', timespec='seconds'),
            'deleted': self.deleted,
            'vacuumed': self.vacuumed,
            'vacuum_error': self.vacuum_error,
            'freelist_ratio': self.freelist_ratio,
            'rules': [
                {'rule': r.rule, 'counts': r.counts, 'skipped_reason': r.skipped_reason, 'error': r.error}
                for r in self.reports
            ],
        }

    def log_line(self) -> str:
        parts = []
        for report in self.reports:
            if report.skipped_reason:
                parts.append(f'{report.rule}={report.skipped_reason}')
            elif report.error:
                parts.append(f'{report.rule}=failed({report.error})')
            else:
                parts.append(f'{report.rule}[' + ' '.join(f'{k}={v}' for k, v in report.counts.items()) + ']')
        return f'cleanup round: deleted={self.deleted} vacuumed={self.vacuumed} ' + ' '.join(parts)


class XRetentionRule:
    """Deletes X archive rows nobody engaged with, once they are old enough.

    Also owns the unlabeled-embedding expiry that used to run at the tail of
    every verdict round: that call sat *inside* the cold-start gate, so on an
    install with too few labels to judge anything it had never run at all.
    """

    name = 'x_retention'

    def enabled(self, settings: Settings) -> bool:
        return settings.condenser_cleanup_x_enabled

    def run(self, now: datetime, settings: Settings) -> CleanupReport:
        embedding_days = settings.condenser_embedding_retention_days
        counts = db.sweep_x_retention(
            feed_cutoff=now - timedelta(days=settings.condenser_cleanup_x_retention_days),
            embedding_cutoff=now - timedelta(days=embedding_days) if embedding_days > 0 else None,
        )
        return CleanupReport(rule=self.name, counts=counts)


class RssRetentionRule:
    """Deletes archived feed entries nobody engaged with, once they are old enough.

    X's rule with one table instead of three: RSS has no quote graph, so there is
    no convergence loop, and ``rss_feeds`` is never swept (100 rows at the design
    target, and its validators are what make a re-subscribe resume rather than
    re-download).
    """

    name = 'rss_retention'

    def enabled(self, settings: Settings) -> bool:
        return settings.condenser_cleanup_rss_enabled

    def run(self, now: datetime, settings: Settings) -> CleanupReport:
        cutoff = now - timedelta(days=settings.condenser_cleanup_rss_retention_days)
        return CleanupReport(rule=self.name, counts=db.sweep_rss_retention(cutoff))


# One tuple, so adding a rule is one line here and the loop below never changes.
DEFAULT_RULES = (XRetentionRule(), RssRetentionRule())


class CleanupManager:
    """Owns the daily sweep. One instance lives on ``app.state.cleanup``."""

    def __init__(
        self,
        settings: Settings,
        rules: Optional[list] = None,
        freelist_ratio: Optional[Callable[[], float]] = None,
        vacuum: Optional[Callable[[], None]] = None,
    ):
        self.settings = settings
        self.rules = list(DEFAULT_RULES) if rules is None else list(rules)
        self._freelist_ratio = freelist_ratio or db.sqlite_freelist_ratio
        self._vacuum = vacuum or db.vacuum
        self._tasks: set[asyncio.Task] = set()

    # ---- lifecycle ----
    async def startup(self) -> None:
        if not self.settings.condenser_cleanup_enabled:
            log.info('cleanup loop disabled by config')
            return
        task = asyncio.create_task(self._loop())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()

    async def _loop(self) -> None:
        # A plain sleep, not HNManager's wake-Event: that idiom exists so
        # subscribing can sample immediately, and nothing here has an equivalent
        # trigger — no user action makes yesterday's retention sweep due sooner.
        while True:
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 — the sweep must outlive anything a round can throw
                log.exception('cleanup round crashed')
            await asyncio.sleep(self.settings.condenser_cleanup_check_interval)

    @staticmethod
    def _now() -> datetime:
        """Naive UTC now (matches the storage convention); test seam."""
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def due(self) -> bool:
        """Has a full interval passed since the last recorded round?

        An absent or unreadable breakpoint reads as "never ran": a corrupted
        value must not wedge the sweep shut until someone notices.
        """
        raw = db.get_meta(LAST_RUN_META_KEY)
        if not raw:
            return True
        try:
            last = datetime.fromisoformat(raw)
        except ValueError:
            return True
        return self._now() - last >= timedelta(hours=self.settings.condenser_cleanup_interval_hours)

    async def _tick(self) -> Optional[CleanupRun]:
        if not self.due():
            return None
        run = await asyncio.to_thread(self._run_in_thread)
        log.info(run.log_line())
        return run

    def _run_in_thread(self) -> CleanupRun:
        try:
            return self.run_once()
        finally:
            # peewee connections are thread-local and this worker is pooled, so
            # hand the connection back rather than pinning a second SQLite handle
            # open for the life of the process.
            if not tdb.db.is_closed():
                tdb.db.close()

    # ---- one round ----
    def run_once(self) -> CleanupRun:
        """Every rule, then the VACUUM decision. Ungated on purpose — the daily
        gate belongs to the scheduler, so a test or a manual trigger can force a
        round without rewriting the schedule."""
        now = self._now()
        run = CleanupRun(started_at=now)
        run.reports = [self._run_rule(rule, now) for rule in self.rules]
        self._maybe_vacuum(run)
        # The breakpoint moves when *something* got done. If every rule threw,
        # nothing did — and the likeliest reason is a transient write lock held
        # by realtime ingest, which deserves a retry on the next hourly check
        # rather than a lost day. A rule failing beside a rule that worked is a
        # different story: re-running the healthy ones every hour buys nothing,
        # and the failure is visible in status either way.
        if not (run.reports and all(r.error for r in run.reports)):
            db.set_meta(LAST_RUN_META_KEY, now.isoformat(sep=' ', timespec='seconds'))
        db.set_meta(LAST_ERROR_META_KEY, '; '.join(r.error for r in run.reports if r.error))
        db.set_meta(LAST_REPORT_META_KEY, json.dumps(run.as_dict()))
        return run

    def _run_rule(self, rule, now: datetime) -> CleanupReport:
        """Isolation is per rule, not per round: a broken future HN rule must
        not cost X the sweep it would otherwise have done."""
        if not rule.enabled(self.settings):
            return CleanupReport(rule=rule.name, skipped_reason='disabled')
        try:
            return rule.run(now, self.settings)
        except Exception as e:  # noqa: BLE001 — one rule's failure is not the round's
            log.exception('cleanup rule %s failed', rule.name)
            return CleanupReport(rule=rule.name, error=str(e))

    def _maybe_vacuum(self, run: CleanupRun) -> None:
        """Reclaim pages, but only when a round actually freed some and they add
        up to a meaningful slice of the file.

        Skipping a round that deleted nothing is the common case for the first
        weeks of a 15-day window, and rewriting the whole file to reclaim
        nothing would be an exclusive lock for no reason. A failure here does
        *not* fail the round: the deletions are already committed, re-running
        them buys nothing, and a write lock held by realtime ingest is a normal
        transient reason to lose the race.
        """
        if run.deleted <= 0:
            return
        run.freelist_ratio = self._freelist_ratio()
        if run.freelist_ratio <= self.settings.condenser_cleanup_vacuum_threshold:
            return
        try:
            self._vacuum()
        except Exception as e:  # noqa: BLE001 — see the docstring
            log.exception('cleanup vacuum failed')
            run.vacuum_error = str(e)
            return
        run.vacuumed = True

    # ---- status ----
    def status(self) -> dict:
        """Answers the question the logs can't: at a 15-day window the first
        weeks legitimately delete nothing, so "never ran" and "ran and found
        nothing" have to look different from outside."""
        raw = db.get_meta(LAST_REPORT_META_KEY)
        return {
            'enabled': self.settings.condenser_cleanup_enabled,
            'interval_hours': self.settings.condenser_cleanup_interval_hours,
            'rules': [{'rule': r.name, 'enabled': r.enabled(self.settings)} for r in self.rules],
            'last_run_at': db.get_meta(LAST_RUN_META_KEY) or None,
            'last_error': db.get_meta(LAST_ERROR_META_KEY) or None,
            'last_report': json.loads(raw) if raw else None,
        }
