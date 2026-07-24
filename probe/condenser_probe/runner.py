"""One probe round: ask the server what to fetch, run bird per feed, push it back.

Stateless by design — every round pushes each feed's most recent N tweets and the
server deduplicates by tweet id. A crashed, sleeping or reinstalled probe has
nothing to recover: the next round simply pushes the current window again.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from .bird import BirdError, fetch_feed
from .client import ProbeClient, ServerError

log = logging.getLogger('condenser_probe.runner')


@dataclass
class FeedOutcome:
    channel_id: str
    fetched: int = 0
    error: Optional[str] = None
    result: Optional[dict] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def run_round(
    client: ProbeClient, fetch: Callable[[dict], list] = None, bird_bin: str = 'bird', timeout: float = 120.0
):
    """Fetch + push every enabled feed. One feed's failure never sinks the others."""
    fetch = fetch or (lambda feed: fetch_feed(feed, bird_bin=bird_bin, timeout=timeout))
    feeds = client.probe_config()
    if not feeds:
        log.info('nothing subscribed on the server — idle round')
        return []

    outcomes = []
    for feed in feeds:
        outcomes.append(_run_feed(client, feed, fetch))
    ok = sum(1 for o in outcomes if o.ok)
    log.info('round done: %d/%d feeds ok', ok, len(outcomes))
    return outcomes


def _run_feed(client: ProbeClient, feed: dict, fetch: Callable[[dict], list]) -> FeedOutcome:
    channel_id = feed.get('channel_id', '?')
    outcome = FeedOutcome(channel_id=channel_id)
    try:
        tweets = fetch(feed)
    except BirdError as e:
        log.error('%s: bird failed: %s', channel_id, e)
        outcome.error = str(e)
        return outcome
    outcome.fetched = len(tweets)
    if not tweets:
        log.warning('%s: bird returned no tweets', channel_id)
        return outcome
    try:
        outcome.result = client.ingest(channel_id, tweets)
    except ServerError as e:
        log.error('%s: ingest failed: %s', channel_id, e)
        outcome.error = str(e)
        return outcome
    log.info(
        '%s: fetched %d, new tweets %s, new items %s, parse errors %s',
        channel_id,
        outcome.fetched,
        outcome.result.get('new_tweets'),
        outcome.result.get('new_items'),
        outcome.result.get('parse_errors'),
    )
    return outcome
