"""Hacker News front-page sampler (multi-source plan Phase 1).

Owns the polling loop that archives every story that reaches the front page.
Sampling is subscription-driven: rounds no-op until an enabled HN feed
subscription exists, so data only accumulates after the user opts in. The
official Firebase API has no history, hence continuous sampling + a one-shot
hckrnews backfill for the recent window.

One instance lives on ``app.state.hn`` (peer of ``TgManager``), sharing the
asyncio loop. HTTP goes through an injectable ``fetch_json`` so tests run
without network or extra dependencies.
"""

import asyncio
import json
import logging
import threading
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import httpx

from . import db, preview, search
from .config import Settings
from .sources import hn as hn_source

log = logging.getLogger('condenser.hn')

TOPSTORIES_URL = 'https://hacker-news.firebaseio.com/v0/topstories.json'
ITEM_URL = 'https://hacker-news.firebaseio.com/v0/item/{id}.json'
HCKRNEWS_URL = 'https://hckrnews.com/data/{yyyymmdd}.js'

# A day's hckrnews archive is only complete/available once it is this many days old.
BACKFILL_ELIGIBLE_AGE_DAYS = 2

# Give up prefetching a story's link preview after this many real fetch attempts
# (fresh negative-cache hits don't count — see _fill_previews).
PREVIEW_MAX_ATTEMPTS = 3

PENDING_META_KEY = 'hn_backfill_pending'

FRONT_FEED_NAME = 'Hacker News Front Page'
# Assembled from the read path's own constants rather than restated here: these
# three values decide what reaches the timeline, and two copies of a number like
# that drift the first time one of them is tuned.
DEFAULT_FEED_CONFIG = {
    'display_mode': hn_source.DEFAULT_DISPLAY_MODE,
    'min_score': hn_source.DEFAULT_MIN_SCORE,
    'max_peak_rank': hn_source.DEFAULT_MAX_PEAK_RANK,
}


def sub_config(sub: db.Subscription) -> dict:
    """A subscription's stored config, defaults filled in (``x.sub_config``'s peer)."""
    cfg = json.loads(sub.config) if sub.config else {}
    return {**DEFAULT_FEED_CONFIG, **cfg}


def _domain(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith('www.') else host or None


def _from_unix(ts: Optional[int]) -> Optional[datetime]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


class HNManager:
    # Throttle knobs as instance attributes so tests can zero them.
    item_throttle = 0.05  # between firebase item fetches
    backfill_day_interval = 4.0  # between hckrnews day requests (rate-limit courtesy)
    refresh_concurrency = 10

    def __init__(
        self, settings: Settings, fetch_json: Optional[Callable] = None, fetch_preview: Optional[Callable] = None
    ):
        self.settings = settings
        self._fetch_json = fetch_json or self._http_fetch_json
        self._fetch_preview = fetch_preview or preview.get_preview
        self._client: Optional[httpx.AsyncClient] = None
        self._tasks: set[asyncio.Task] = set()
        self._wake = asyncio.Event()
        self._sleep = asyncio.sleep
        self._loop_ref: Optional[asyncio.AbstractEventLoop] = None
        # Guards the pending-backfill set: schedule_backfill runs on FastAPI's
        # threadpool while the sampling loop rewrites the set from the event loop.
        self._pending_lock = threading.Lock()

    # ---- lifecycle ----
    async def startup(self) -> None:
        if not self.settings.condenser_hn_enabled:
            log.info('hn source disabled by config')
            return
        self._loop_ref = asyncio.get_running_loop()
        task = asyncio.create_task(self._loop())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._client is not None:
            await self._client.aclose()

    def kick(self) -> None:
        """Wake the loop for an immediate round (called right after subscribing).

        Callers run on FastAPI's threadpool; asyncio primitives are not
        thread-safe, so the set() is marshalled onto the loop's thread. No-op
        when the loop never started (source disabled / before startup).
        """
        if self._loop_ref is None or self._loop_ref.is_closed():
            return
        self._loop_ref.call_soon_threadsafe(self._wake.set)

    async def _loop(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:  # noqa: BLE001 — the sampler must outlive anything a round can throw
                log.exception('hn poll round crashed')
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.settings.condenser_hn_poll_interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _http_fetch_json(self, url: str) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20, follow_redirects=True)
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _now() -> datetime:
        """Naive UTC now (matches the storage convention); test seam."""
        return datetime.now(timezone.utc).replace(tzinfo=None)

    # ---- one sampling round ----
    async def poll_once(self) -> None:
        """One round: sample the front page, refresh snapshots, advance backfill.

        Subscription-driven: with no enabled HN subscription the round is a no-op
        (zero requests). Any round-level failure is logged + recorded in app_meta,
        never raised — the loop must survive.
        """
        if not db.hn_sampling_active():
            return
        try:
            sampled = await self._sample_front()
            await self._refresh_snapshots(exclude=sampled)
            await self._backfill_eligible_days()
            await self._fill_previews()
        except Exception as e:  # noqa: BLE001 — top-level loop guard (spec: log + skip round)
            log.exception('hn poll round failed')
            db.set_meta('hn_last_error', str(e))
            return
        db.set_meta('hn_last_poll_at', self._now().isoformat(sep=' ', timespec='seconds'))
        db.set_meta('hn_last_error', '')

    async def _sample_front(self) -> set[int]:
        """Ingest unseen front-page stories; returns every id fetched this round."""
        ids = await self._fetch_json(TOPSTORIES_URL)
        front = list(ids or [])[: self.settings.condenser_hn_front_size]
        known = db.existing_hn_story_ids(front)
        fetched: set[int] = set()
        for rank, sid in enumerate(front, start=1):
            if sid in known:
                db.update_hn_peak_rank(sid, rank)
                continue
            try:
                item = await self._fetch_json(ITEM_URL.format(id=sid))
            except Exception:  # noqa: BLE001 — one bad item must not sink the round (spec)
                log.exception('hn item fetch failed for %s', sid)
                continue
            fetched.add(sid)
            if item is None:
                # Never-seen id with a null item: store a dead placeholder so the id
                # isn't refetched every round while it stays on the front page.
                now = self._now()
                db.insert_hn_story(id=sid, first_seen_at=now, day=str(now.date()), peak_rank=rank, is_dead=True)
                continue
            self._insert_item(item, first_seen_at=self._now(), rank=rank)
            await self._sleep(self.item_throttle)
        return fetched

    def _insert_item(
        self,
        item: dict,
        first_seen_at: datetime,
        rank: Optional[int] = None,
        day: Optional[str] = None,
        backfilled: bool = False,
    ) -> None:
        db.insert_hn_story(
            id=item['id'],
            title=item.get('title'),
            url=item.get('url'),
            domain=_domain(item.get('url')),
            author=item.get('by'),
            text=item.get('text'),
            type=item.get('type') or 'story',
            submitted_at=_from_unix(item.get('time')),
            first_seen_at=first_seen_at,
            day=day or str(first_seen_at.date()),
            score=item.get('score') or 0,
            comments_count=item.get('descendants') or 0,
            score_updated_at=self._now(),
            peak_rank=rank,
            is_dead=bool(item.get('dead') or item.get('deleted')),
            backfilled=backfilled,
        )
        # The one place a story's *text* enters the archive — sampling and the
        # hckrnews backfill both land here, and the snapshot refresh only moves
        # score/comment counts, so there is nothing else to hook. `is_dead` rides
        # along because Firebase serves already-flagged submissions that are still
        # in `topstories`, and those were never showable.
        search.index_hn_story(
            {
                'id': item['id'],
                'title': item.get('title'),
                'text': item.get('text'),
                'first_seen_at': first_seen_at,
                'is_dead': bool(item.get('dead') or item.get('deleted')),
            }
        )

    async def _refresh_snapshots(self, exclude: set[int]) -> None:
        """Re-pull score/comment counts for live stories inside the refresh window."""
        cutoff = self._now() - timedelta(hours=self.settings.condenser_hn_refresh_hours)
        stories = [s for s in db.hn_stories_to_refresh(cutoff) if s.id not in exclude]
        if not stories:
            return
        sem = asyncio.Semaphore(self.refresh_concurrency)

        async def refresh_one(story) -> None:
            async with sem:
                try:
                    item = await self._fetch_json(ITEM_URL.format(id=story.id))
                except Exception:  # noqa: BLE001 — per-item tolerance (spec)
                    log.exception('hn snapshot refresh failed for %s', story.id)
                    return
                if item is None:
                    # Firebase transiently returns null for live items; a dead mark here
                    # would silently freeze the story forever. Retry next round instead.
                    return
                if item.get('dead') or item.get('deleted'):
                    db.mark_hn_story_dead(story.id)
                    return
                db.update_hn_snapshot(story.id, item.get('score') or 0, item.get('descendants') or 0, self._now())

        await asyncio.gather(*(refresh_one(s) for s in stories))

    # ---- link preview prefetch ----
    async def _fill_previews(self) -> None:
        """Prefetch link previews into ``hn_stories.preview`` (batch per round, newest first).

        One mechanism covers freshly sampled stories, backfilled history, and rows
        from before the feature existed. Fetching goes through ``preview.get_preview``
        so the shared ``link_previews`` cache is warmed for the pane too. An attempt
        is only counted when a real fetch happened: a still-fresh negative cache entry
        (its TTL < the poll interval would otherwise eat every retry) skips the story
        without bumping, so the retries spread out to one per cache expiry.
        """
        batch = self.settings.condenser_hn_preview_batch
        if batch <= 0:
            return
        stories = db.hn_stories_needing_preview(batch, PREVIEW_MAX_ATTEMPTS)
        if not stories:
            return
        sem = asyncio.Semaphore(self.settings.condenser_preview_max_concurrency)

        async def fill_one(story) -> None:
            cached = db.get_cached_preview(preview.normalize_url(story.url))
            if cached is not None and not cached.ok and preview._cache_fresh(cached, self.settings):
                return
            async with sem:
                result = await self._fetch_preview(story.url)
            if result.error:
                db.bump_hn_preview_attempts(story.id)
                return
            # Success is terminal even with empty fields — the URL just has no metadata.
            db.set_hn_preview(story.id, result.model_dump_json())

        await asyncio.gather(*(fill_one(s) for s in stories))

    # ---- hckrnews historical backfill ----
    def schedule_backfill(self) -> None:
        """Register the recent window as pending backfill days (called on subscribe).

        Days at least ``BACKFILL_ELIGIBLE_AGE_DAYS`` old are picked up by the next
        round immediately; yesterday/today stay pending until their hckrnews
        archive exists, so the pre-subscription hours of those days get filled too.
        """
        days = self.settings.condenser_hn_backfill_days
        if days <= 0:
            return
        today = self._now().date()
        with self._pending_lock:
            pending = self._pending_days()
            pending.update(str(today - timedelta(days=d)) for d in range(days + 1))
            self._save_pending(pending)

    def _pending_days(self) -> set[str]:
        raw = db.get_meta(PENDING_META_KEY)
        return set(json.loads(raw)) if raw else set()

    def _save_pending(self, days: set[str]) -> None:
        db.set_meta(PENDING_META_KEY, json.dumps(sorted(days)))

    def _discard_pending_day(self, day_str: str) -> None:
        """Drop one completed day via a fresh read-modify-write.

        The backfill round spans long awaits; writing back its stale snapshot
        would clobber days a concurrent schedule_backfill just added.
        """
        with self._pending_lock:
            pending = self._pending_days()
            pending.discard(day_str)
            self._save_pending(pending)

    async def _backfill_eligible_days(self) -> None:
        """Serially fetch eligible pending days from hckrnews; failures stay pending."""
        if self.settings.condenser_hn_backfill_days <= 0:
            return
        pending = self._pending_days()
        if not pending:
            return
        newest_eligible = self._now().date() - timedelta(days=BACKFILL_ELIGIBLE_AGE_DAYS)
        eligible = sorted(d for d in pending if date.fromisoformat(d) <= newest_eligible)
        for i, day_str in enumerate(eligible):
            if i > 0:
                await self._sleep(self.backfill_day_interval)
            try:
                await self._backfill_day(date.fromisoformat(day_str))
            except Exception:  # noqa: BLE001 — a failed day stays pending for the next round (spec)
                log.exception('hn backfill failed for %s', day_str)
                continue
            self._discard_pending_day(day_str)

    async def _backfill_day(self, day: date) -> None:
        """Import one hckrnews archive day; item details still come from the official API."""
        entries = await self._fetch_json(HCKRNEWS_URL.format(yyyymmdd=day.strftime('%Y%m%d')))
        ids = [int(e['id']) for e in entries or [] if e.get('id') is not None]
        known = db.existing_hn_story_ids(ids)
        day_start = datetime.combine(day, dtime.min)
        day_end = datetime.combine(day, dtime.max)
        for sid in ids:
            if sid in known:
                continue
            try:
                item = await self._fetch_json(ITEM_URL.format(id=sid))
            except Exception:  # noqa: BLE001 — per-item tolerance (spec)
                log.exception('hn backfill item fetch failed for %s', sid)
                continue
            if item is None:
                continue
            # first_seen_at approximated by the submit time clamped into the archive day
            submitted = _from_unix(item.get('time')) or day_start
            first_seen = min(max(submitted, day_start), day_end)
            self._insert_item(item, first_seen_at=first_seen, day=str(day), backfilled=True)
            await self._sleep(self.item_throttle)

    # ---- status ----
    def status(self) -> dict:
        sub = db.get_hn_subscription('front')
        total, today_count = db.hn_story_counts(str(self._now().date()))
        return {
            'subscribed': sub is not None,
            'enabled': bool(sub.enabled) if sub is not None else False,
            'source_enabled': self.settings.condenser_hn_enabled,
            'config': json.loads(sub.config) if sub is not None and sub.config else None,
            'last_poll_at': db.get_meta('hn_last_poll_at'),
            'last_error': db.get_meta('hn_last_error') or None,
            'stories_total': total,
            'stories_today': today_count,
            'backfill_pending_days': sorted(self._pending_days()),
        }
