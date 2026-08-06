"""One probe round: ask the server what to fetch, read X per feed, push it back.

Almost stateless: the server owns the feed list and deduplicates by tweet id, so
a crashed, sleeping or reinstalled probe has nothing to recover. The one piece of
local state is the ``SeenCache`` (opt-out via ``--no-cache``), which only decides
what to *skip* — losing it costs a redundant push, never data. See cache.py.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from .cache import SeenCache
from .client import ProbeClient, ServerError
from .xsource import DEFAULT_TIMEOUT_MS, XSourceError, fetch_feed, fetch_following_users

log = logging.getLogger('condenser_probe.runner')


@dataclass
class FeedOutcome:
    channel_id: str
    fetched: int = 0
    skipped: int = 0  # already pushed by an earlier round (SeenCache)
    error: Optional[str] = None
    result: Optional[dict] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def run_round(
    client: ProbeClient,
    fetch: Callable[[dict], list] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    fetch_following: Callable[[], list] = None,
    cache: Optional[SeenCache] = None,
    kinds: Optional[Iterable[str]] = None,
):
    """Fetch + push every enabled feed. One feed's failure never sinks the others.

    ``kinds`` scopes the round to a slice of probe-config (the scheduler runs
    For You and the rest on different cadences); None means every feed.
    """
    fetch = fetch or (lambda feed: fetch_feed(feed, timeout_ms=timeout_ms))
    fetch_following = fetch_following or (lambda: fetch_following_users(timeout_ms=timeout_ms))
    config = client.probe_config()
    feeds = config.get('feeds') or []
    if kinds is not None:
        kinds = set(kinds)
        feeds = [f for f in feeds if f.get('kind') in kinds]

    # Before the feeds, not after: the server drops Following entries whose author
    # is not in this list, so a first round that ingested first would read its own
    # empty list as "filter nothing" (or, once populated, as "everything is an ad").
    if config.get('sync_following'):
        _sync_following(client, fetch_following)

    if not feeds:
        scope = f' for kinds {sorted(kinds)}' if kinds is not None else ' on the server'
        log.info('nothing subscribed%s — idle round', scope)
        return []

    outcomes = []
    for feed in feeds:
        outcomes.append(_run_feed(client, feed, fetch, cache))
    ok = sum(1 for o in outcomes if o.ok)
    log.info('round done: %d/%d feeds ok', ok, len(outcomes))
    return outcomes


def _sync_following(client: ProbeClient, fetch_following: Callable[[], list]) -> None:
    """Re-crawl the follow list and hand it over. Never fatal: a stale list still
    filters, and the server asks again next round."""
    try:
        users = fetch_following()
    except XSourceError as e:
        log.error('follow list: %s', e)
        return
    try:
        result = client.push_following(users)
    except ServerError as e:
        log.error('follow list: push failed: %s', e)
        return
    log.info('follow list: %d accounts fetched, %s stored', len(users), result.get('stored'))


def _run_feed(
    client: ProbeClient, feed: dict, fetch: Callable[[dict], list], cache: Optional[SeenCache] = None
) -> FeedOutcome:
    channel_id = feed.get('channel_id', '?')
    outcome = FeedOutcome(channel_id=channel_id)
    try:
        tweets = fetch(feed)
    except XSourceError as e:
        log.error('%s: fetch failed: %s', channel_id, e)
        outcome.error = str(e)
        return outcome
    outcome.fetched = len(tweets)
    if not tweets:
        log.warning('%s: no tweets returned', channel_id)
        return outcome

    fresh = cache.filter_new(channel_id, tweets) if cache else tweets
    outcome.skipped = len(tweets) - len(fresh)
    if not fresh:
        log.info('%s: fetched %d, all already pushed', channel_id, outcome.fetched)
        return outcome
    try:
        outcome.result = client.ingest(channel_id, fresh)
    except ServerError as e:
        log.error('%s: ingest failed: %s', channel_id, e)
        outcome.error = str(e)
        return outcome
    if cache:
        # After the push, never before: recording first would drop these tweets
        # for good if the server rejected them.
        cache.record(channel_id, fresh)
    log.info(
        '%s: fetched %d (%d already pushed), new tweets %s, new items %s, parse errors %s',
        channel_id,
        outcome.fetched,
        outcome.skipped,
        outcome.result.get('new_tweets'),
        outcome.result.get('new_items'),
        outcome.result.get('parse_errors'),
    )
    return outcome
