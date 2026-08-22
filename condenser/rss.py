"""RSS source: polling, parsing, ingest (plan 2026-08-20-rss-source-opml-llm-summary.md).

The simplest source in the project, and deliberately so: RSS is a published
standard, so there is no probe, no reverse-engineered API, no anti-scraping, and
nothing to judge. What is left is the two things every feed reader gets wrong —
**not re-downloading** what has not changed (conditional requests), and **not
dumping a feed's whole retained window on the reader as unread** the moment they
subscribe (the unread window, plan §0.3).

One ``RssManager`` lives on ``app.state.rss`` (peer of ``HNManager``), sharing the
asyncio loop. HTTP goes through an injectable ``fetch_feed`` so tests run without
network; parsing does **not** get the same treatment, because parsing real-world
XML is the entire risk surface here and a stubbed parser would test nothing.

Design targets 100 subscribed feeds. That is cheap for the reason above: after the
first round almost every feed answers 304, so a round is 100 conditional GETs and
no bodies at all.
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlsplit
from xml.etree import ElementTree

import feedparser
import httpx

from . import db, search, summary
from .config import Settings

log = logging.getLogger('condenser.rss')

LAST_POLL_META_KEY = 'rss_last_poll_at'
LAST_ERROR_META_KEY = 'rss_last_error'
LAST_ROUND_META_KEY = 'rss_last_round'


class NotAFeedError(ValueError):
    """The URL answered, but with something that is not a feed.

    Its own error because the failure is silent otherwise: an HTML error page
    parses **clean** (feedparser sets no ``bozo``) with zero entries, so without
    this the subscription would look like a feed that simply never publishes.
    """


@dataclass
class FetchResult:
    """One HTTP round trip's outcome — the injectable boundary's contract."""

    status: int  # 200 | 304
    body: Optional[bytes]  # None on 304
    etag: Optional[str] = None
    last_modified: Optional[str] = None


@dataclass
class ParsedEntry:
    guid: str
    title: Optional[str] = None
    link: Optional[str] = None
    author: Optional[str] = None
    content: Optional[str] = None
    published_at: Optional[datetime] = None


@dataclass
class ParsedFeed:
    title: Optional[str] = None
    site_url: Optional[str] = None
    entries: list[ParsedEntry] = field(default_factory=list)
    # A recovered-from complaint (malformed XML we still read entries out of).
    # Recorded as a warning, not a failure — see poll_once.
    warning: Optional[str] = None
    dropped: int = 0  # entries with nothing to key on


# --- urls ---------------------------------------------------------------------


def normalize_feed_url(url: str) -> str:
    """Validate a feed URL and strip surrounding whitespace — nothing more.

    Deliberately no canonicalization: lowercasing a host or dropping a trailing
    slash changes the URL some servers key their cache on, and the URL is this
    source's primary key. What the reader typed is what we store (the X handle
    precedent).
    """
    url = (url or '').strip()
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        raise ValueError(f'feed url must be an http(s) URL: {url!r}')
    return url


# --- parsing ------------------------------------------------------------------


def _from_struct(value) -> Optional[datetime]:
    """feedparser's ``*_parsed`` struct_time is already UTC; storage is naive UTC."""
    if not value:
        return None
    return datetime(*value[:6])


def _entry_guid(entry: dict) -> Optional[str]:
    """The dedup key, in three fallbacks (plan §1.2).

    ``<guid>`` / Atom ``<id>`` first, because that is what the format is for; then
    the link, which most guid-less feeds (Hacker News's own, for one) make unique
    anyway; then a hash of title + declared date, which is stable across rounds as
    long as the feed does not rewrite either. An entry with none of the three
    cannot be recognized on its next sighting, so it is dropped rather than
    archived under a hash of nothing — that would make every such entry in the
    feed the same item (``x.py``: unkeyable entries are counted and dropped).
    """
    for candidate in (entry.get('id'), entry.get('link')):
        if candidate and candidate.strip():
            return candidate.strip()
    title = (entry.get('title') or '').strip()
    published = (entry.get('published') or entry.get('updated') or '').strip()
    if not title and not published:
        return None
    return hashlib.sha256(f'{title}\x1f{published}'.encode()).hexdigest()


def _entry_content(entry: dict) -> Optional[str]:
    """The entry's body: ``content:encoded`` / Atom ``<content>`` if present, else
    ``<description>`` / ``<summary>``.

    The fuller one wins because this text is the summariser's raw material (plan
    §0.1 — no full-article fetching), and a teaser summarized is a summary of a
    teaser.
    """
    for content in entry.get('content') or []:
        value = content.get('value')
        if value:
            return value
    return entry.get('summary') or None


def parse_feed(body: bytes) -> ParsedFeed:
    """Parse a feed document. RSS 2.0 / Atom / RDF are all feedparser's problem.

    Runs off the event loop (see ``_poll_feed``): feedparser is pure Python and a
    round of 100 feeds would otherwise stall the loop this process shares with
    FastAPI, the Telegram listener and the HN sampler.
    """
    parsed = feedparser.parse(body)
    if not parsed.entries and not parsed.get('version'):
        raise NotAFeedError('not a feed: no entries and no recognizable feed format')
    entries, dropped = [], 0
    for raw in parsed.entries:
        guid = _entry_guid(raw)
        if guid is None:
            dropped += 1
            continue
        entries.append(
            ParsedEntry(
                guid=guid,
                title=(raw.get('title') or None),
                link=(raw.get('link') or None),
                author=(raw.get('author') or None),
                content=_entry_content(raw),
                published_at=_from_struct(raw.get('published_parsed') or raw.get('updated_parsed')),
            )
        )
    return ParsedFeed(
        title=parsed.feed.get('title') or None,
        site_url=parsed.feed.get('link') or None,
        entries=entries,
        # bozo means "this XML is broken" — but feedparser recovers entries from
        # broken XML routinely, and dropping real content over a stray ampersand
        # would be the worse failure. Archive them and show the complaint.
        warning=str(parsed.bozo_exception) if parsed.bozo else None,
        dropped=dropped,
    )


# --- opml ---------------------------------------------------------------------


def parse_opml(text: str) -> list[dict]:
    """Every ``<outline>`` carrying an ``xmlUrl``, flattened, in document order.

    ``iter`` walks the whole tree, so nested folders need no recursion of our own —
    and the folder structure is discarded, which is the v1 decision (plan §11):
    condenser has no folders to import them into. An outline with no ``xmlUrl`` is
    a folder, not an error.
    """
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as e:
        raise ValueError(f'not valid OPML: {e}')
    out: list[dict] = []
    seen: set[str] = set()
    for outline in root.iter('outline'):
        url = (outline.get('xmlUrl') or '').strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = (outline.get('title') or outline.get('text') or '').strip()
        out.append({'url': url, 'title': title or None})
    return out


# --- manager ------------------------------------------------------------------


class RssManager:
    def __init__(
        self,
        settings: Settings,
        fetch_feed: Optional[Callable] = None,
        summarize: Optional[Callable] = None,
    ):
        self.settings = settings
        self._fetch_feed = fetch_feed or self._http_fetch_feed
        # None = summary.run_round builds the real (billed) one. Injected in tests
        # for the same reason fetch_feed is: no test may reach the network.
        self._summarize = summarize
        self._client: Optional[httpx.AsyncClient] = None
        self._tasks: set[asyncio.Task] = set()
        self._wake = asyncio.Event()
        self._loop_ref: Optional[asyncio.AbstractEventLoop] = None

    # ---- lifecycle ----
    async def startup(self) -> None:
        if not self.settings.condenser_rss_enabled:
            log.info('rss source disabled by config')
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
        """Wake the loop for an immediate round (subscribe / OPML import).

        Callers run on FastAPI's threadpool and asyncio primitives are not
        thread-safe, so the set() is marshalled onto the loop's thread. No-op
        before startup / when the source is disabled (HNManager.kick).
        """
        if self._loop_ref is None or self._loop_ref.is_closed():
            return
        self._loop_ref.call_soon_threadsafe(self._wake.set)

    async def _loop(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:  # noqa: BLE001 — the poller must outlive anything a round can throw
                log.exception('rss poll round crashed')
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.settings.condenser_rss_poll_minutes * 60)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _http_fetch_feed(
        self, url: str, etag: Optional[str] = None, last_modified: Optional[str] = None
    ) -> FetchResult:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.settings.condenser_rss_timeout,
                follow_redirects=True,
                headers={'User-Agent': self.settings.condenser_preview_user_agent},
            )
        headers = {}
        if etag:
            headers['If-None-Match'] = etag
        if last_modified:
            headers['If-Modified-Since'] = last_modified
        resp = await self._client.get(url, headers=headers)
        if resp.status_code == 304:
            # Checked *before* raise_for_status, which classifies 304 as a redirect
            # and raises on it. That would turn the most common outcome of a healthy
            # round — "nothing changed" — into a recorded feed failure (found on the
            # first live run; the injected fetcher in tests cannot see this).
            return FetchResult(
                status=304,
                body=None,
                etag=resp.headers.get('etag'),
                last_modified=resp.headers.get('last-modified'),
            )
        resp.raise_for_status()
        return FetchResult(
            status=resp.status_code,
            body=resp.content,
            etag=resp.headers.get('etag'),
            last_modified=resp.headers.get('last-modified'),
        )

    @staticmethod
    def _now() -> datetime:
        """Naive UTC now (the storage convention); test seam."""
        return datetime.now(timezone.utc).replace(tzinfo=None)

    # ---- one polling round ----
    async def poll_once(self) -> None:
        """Fetch every enabled feed once, concurrently but bounded.

        Subscription-driven: with nothing subscribed the round is a no-op and
        costs zero requests. A single feed's failure is recorded on its own row
        and never sinks the round — with 100 feeds, one dead host must not cost
        the other 99 their update.
        """
        if not db.rss_polling_active():
            return
        try:
            subs = db.enabled_rss_subscriptions()
            sem = asyncio.Semaphore(max(1, self.settings.condenser_rss_fetch_concurrency))
            # return_exceptions so one feed's *unhandled* failure (a DB error in the
            # handler that records the failure, say) cannot abort the gather and take
            # the other 99 feeds' results with it. _poll_feed already catches the
            # expected ones; this covers the rest.
            outcomes = await asyncio.gather(*(self._poll_feed(sub, sem) for sub in subs), return_exceptions=True)
        except Exception as e:  # noqa: BLE001 — round-level guard (the HN precedent: log + skip)
            log.exception('rss poll round failed')
            db.set_meta(LAST_ERROR_META_KEY, str(e))
            return
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                log.exception('rss feed round crashed', exc_info=outcome)
        results = [o for o in outcomes if isinstance(o, dict)]
        round_stats = {
            'feeds': len(outcomes),
            'errors': sum(1 for o in results if not o['ok']) + (len(outcomes) - len(results)),
            'new_entries': sum(o['new'] for o in results),
            **await self._summarize_round(),
        }
        db.set_meta(LAST_POLL_META_KEY, self._now().isoformat(sep=' ', timespec='seconds'))
        db.set_meta(LAST_ERROR_META_KEY, '')
        db.set_meta(LAST_ROUND_META_KEY, json.dumps(round_stats))
        log.info('rss round done: %s', round_stats)

    async def _poll_feed(self, sub: db.Subscription, sem: asyncio.Semaphore) -> dict:
        url = sub.channel_id
        feed = db.get_rss_feed(url) or db.ensure_rss_feed(url)
        try:
            async with sem:
                result = await self._fetch_feed(url, feed.etag, feed.last_modified)
            now = self._now()
            if result.status == 304:
                # Nothing changed. Still a successful check, so the timestamp moves
                # and the failure streak clears; the stored validators stay put.
                db.record_rss_feed_success(url, at=now, etag=result.etag, last_modified=result.last_modified)
                return {'ok': True, 'new': 0}
            parsed = await asyncio.to_thread(parse_feed, result.body or b'')
            new = self._ingest(url, parsed, now)
            db.record_rss_feed_success(
                url,
                at=now,
                title=parsed.title,
                site_url=parsed.site_url,
                etag=result.etag,
                last_modified=result.last_modified,
                note=parsed.warning,
            )
            self._learn_feed_name(sub, parsed.title)
            return {'ok': True, 'new': new}
        except Exception as e:  # noqa: BLE001 — per-feed isolation is the whole point
            log.warning('rss feed failed: %s (%s)', url, e)
            db.record_rss_feed_error(url, str(e) or e.__class__.__name__, self._now())
            return {'ok': False, 'new': 0}

    def _ingest(self, feed_url: str, parsed: ParsedFeed, now: datetime) -> int:
        """Archive the entries this feed has that we do not, applying the unread window.

        Insert-if-absent on ``(feed_url, guid)``: a feed re-serves its whole
        retained window every round, so all but the first pass is expected to add
        nothing. Entries are also deduplicated *within* one document, because a
        broken feed repeating a guid would otherwise miscount the round.
        """
        if not parsed.entries:
            return 0
        known = db.existing_rss_guids(feed_url, [e.guid for e in parsed.entries])

        rows, seen = [], set()
        for entry in parsed.entries:
            if entry.guid in known or entry.guid in seen:
                continue
            seen.add(entry.guid)
            rows.append(
                {
                    'feed_url': feed_url,
                    'guid': entry.guid,
                    'title': entry.title,
                    'link': entry.link,
                    'author': entry.author,
                    'content': entry.content,
                    'published_at': entry.published_at,
                    'first_seen_at': now,
                }
            )
        added = db.insert_rss_entries(rows, read_before=self._unread_cutoff(now), now=now)
        # Search documents are written here rather than inside the insert, because
        # what they contain (the clamped sort position, the feed's own title) is the
        # provider's view of the row, not the row.
        search.index_rss_entries(db.rss_entry_ids(feed_url, [row['guid'] for row in rows]))
        return added

    def _unread_cutoff(self, now: datetime) -> Optional[datetime]:
        """Entries published before this arrive already read (plan §0.3).

        Applied to every round, not just the first: on a steady-state round nothing
        real is that old, so the rule only bites on an import or a new subscription
        — which is exactly where it is needed, and needs no "is this the first
        round" branch to know it.
        """
        days = self.settings.condenser_rss_unread_window_days
        return now - timedelta(days=days) if days > 0 else None

    async def _summarize_round(self) -> dict:
        """Run the summary pipeline at the tail of the round (plan §3).

        Guarded on its own: fetching is this source's job and summarizing is an
        extra, so a pipeline that throws must not cost the round its ingest — by
        this point the entries are already archived, and the meta the status
        endpoint reads is still unwritten.
        """
        try:
            stats = await summary.run_round(self.settings, summarize=self._summarize)
        except Exception as e:  # noqa: BLE001 — an extra must not sink the round
            log.exception('rss summary round failed')
            return {'summarized': 0, 'summary_error': str(e)}
        out = {'summarized': stats['summarized']}
        if stats['provider_error']:
            out['summary_error'] = stats['provider_error']
        return out

    def _learn_feed_name(self, sub: db.Subscription, title: Optional[str]) -> None:
        """Backfill the subscription's display name from the feed's own title.

        Only while it is NULL: a name the reader typed is their label, and a feed
        that renames itself must not overwrite it (``x._learn_user_identity``).
        """
        if title and not sub.name:
            db.update_rss_subscription(sub.channel_id, name=title)

    # ---- status ----
    def status(self) -> dict:
        subs = db.list_rss_subscriptions()
        raw_round = db.get_meta(LAST_ROUND_META_KEY)
        return {
            'source_enabled': self.settings.condenser_rss_enabled,
            'subscribed': bool(subs),
            'feeds_total': len(subs),
            'feeds_enabled': sum(1 for s in subs if s.enabled),
            'feeds_error': db.rss_feed_error_count(),
            'entries_total': db.rss_entry_count(),
            # The billed half of this source reports itself here (plan §3 fence 4):
            # an inert pipeline and an empty backlog look the same from the timeline.
            'summary': summary.counts(self.settings),
            'last_poll_at': db.get_meta(LAST_POLL_META_KEY),
            'last_error': db.get_meta(LAST_ERROR_META_KEY) or None,
            'last_round': json.loads(raw_round) if raw_round else None,
        }


def describe_subscription(sub: db.Subscription, feed: Optional[db.RssFeed] = None) -> dict[str, Any]:
    """One subscription row as the API returns it: the reader's decision plus the
    feed's fetch state, which is where a silent feed explains itself."""
    feed = feed if feed is not None else db.get_rss_feed(sub.channel_id)
    return {
        'url': sub.channel_id,
        # NULL until the first successful fetch teaches us the feed's title; the
        # client falls back to the URL rather than rendering a placeholder.
        'name': sub.name or (feed.title if feed else None),
        'enabled': bool(sub.enabled),
        'site_url': feed.site_url if feed else None,
        'fetched_at': str(feed.fetched_at) if feed and feed.fetched_at else None,
        'last_error': feed.last_error if feed else None,
        'error_count': feed.error_count if feed else 0,
    }
