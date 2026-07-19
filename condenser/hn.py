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
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import httpx

from . import db
from .config import Settings

log = logging.getLogger('condenser.hn')

TOPSTORIES_URL = 'https://hacker-news.firebaseio.com/v0/topstories.json'
ITEM_URL = 'https://hacker-news.firebaseio.com/v0/item/{id}.json'
HCKRNEWS_URL = 'https://hckrnews.com/data/{yyyymmdd}.js'

# A day's hckrnews archive is only complete/available once it is this many days old.
BACKFILL_ELIGIBLE_AGE_DAYS = 2

PENDING_META_KEY = 'hn_backfill_pending'

FRONT_FEED_NAME = 'Hacker News Front Page'
DEFAULT_FEED_CONFIG = {'display_mode': 'top20'}


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

    def __init__(self, settings: Settings, fetch_json: Optional[Callable] = None):
        self.settings = settings
        self._fetch_json = fetch_json or self._http_fetch_json
        self._client: Optional[httpx.AsyncClient] = None
        self._tasks: set[asyncio.Task] = set()
        self._wake = asyncio.Event()
        self._sleep = asyncio.sleep

    # ---- lifecycle ----
    async def startup(self) -> None:
        if not self.settings.condenser_hn_enabled:
            log.info('hn source disabled by config')
            return
        task = asyncio.create_task(self._loop())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._client is not None:
            await self._client.aclose()

    def kick(self) -> None:
        """Wake the loop for an immediate round (called right after subscribing)."""
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            await self.poll_once()
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
                if item is None or item.get('dead') or item.get('deleted'):
                    db.mark_hn_story_dead(story.id)
                    return
                db.update_hn_snapshot(story.id, item.get('score') or 0, item.get('descendants') or 0, self._now())

        await asyncio.gather(*(refresh_one(s) for s in stories))

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
        pending = self._pending_days()
        pending.update(str(today - timedelta(days=d)) for d in range(days + 1))
        self._save_pending(pending)

    def _pending_days(self) -> set[str]:
        raw = db.get_meta(PENDING_META_KEY)
        return set(json.loads(raw)) if raw else set()

    def _save_pending(self, days: set[str]) -> None:
        db.set_meta(PENDING_META_KEY, json.dumps(sorted(days)))

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
            pending.discard(day_str)
            self._save_pending(pending)

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
            'config': json.loads(sub.config) if sub is not None and sub.config else None,
            'last_poll_at': db.get_meta('hn_last_poll_at'),
            'last_error': db.get_meta('hn_last_error') or None,
            'stories_total': total,
            'stories_today': today_count,
            'backfill_pending_days': sorted(self._pending_days()),
        }
