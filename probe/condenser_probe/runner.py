"""One probe round: ask the server what to fetch, read X per feed, push it back.

Almost stateless: the server owns the feed list and deduplicates by tweet id, so
a crashed, sleeping or reinstalled probe has nothing to recover. The one piece of
local state is the ``SeenCache`` (opt-out via ``--no-cache``), which only decides
what to *skip* — losing it costs a redundant push, never data. See cache.py.

X Articles are read **inline** (plan 2026-09-17): a timeline read carries a
long-form post's title and preview only, so each new one gets a TweetDetail read
before its feed is pushed, and the detail's ``article`` block — body included —
rides up in the same ingest. A read that raises costs the body, never the tweet,
and is retried by the cache's own structure: the tweet is pushed but not recorded,
so the next round sees it as new and reads it again. See ``_read_articles``.
"""

import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from .cache import SeenCache
from .client import ProbeClient, ServerError
from .xsource import (
    ARTICLE_FETCH_DELAY,
    DEFAULT_TIMEOUT_MS,
    XSourceError,
    fetch_feed,
    fetch_following_users,
    fetch_tweet_article,
)

log = logging.getLogger('condenser_probe.runner')


@dataclass
class FeedOutcome:
    channel_id: str
    fetched: int = 0
    skipped: int = 0  # already pushed by an earlier round (SeenCache)
    error: Optional[str] = None
    result: Optional[dict] = None
    articles_fetched: int = 0  # new long-form posts pushed with their body
    articles_failed: int = 0  # ...pushed without it, to be read again next round

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class ArticleReader:
    """One round's article reads: the pacing between them and the circuit breaker.

    Shared by every feed of the round, because what the breaker guards against is
    round-wide — a dead session or a rate limit fails every read the same way, and
    one timeout per article would hold each feed's push back by minutes. It closes
    again with the next round, which is a new reader.
    """

    fetch: Callable[[str], Optional[dict]]
    delay: float
    sleep: Callable[[float], None]
    reads: int = 0
    open: bool = False

    def read(self, channel_id: str, tweet_id: str) -> tuple[bool, Optional[dict]]:
        """One paced detail read -> (whether the read happened, the body block or None).

        Did not happen = it raised, or the breaker was already open. Any exception
        counts — xbird maps the detail response outside its own error values, and a
        body must never cost its tweet the push. The first one opens the breaker.
        """
        if self.open:
            return False, None
        if self.reads:
            self.sleep(self.delay)
        self.reads += 1
        try:
            detail = self.fetch(str(tweet_id))
        except Exception as e:  # noqa: BLE001 - see the docstring
            log.error('%s: article %s: read failed: %s', channel_id, tweet_id, e)
            log.warning('article reads paused for the rest of this round')
            self.open = True
            return False, None
        return True, detail if _has_body(detail) else None


def run_round(
    client: ProbeClient,
    fetch: Callable[[dict], list] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    fetch_following: Callable[[], list] = None,
    cache: Optional[SeenCache] = None,
    kinds: Optional[Iterable[str]] = None,
    fetch_article: Callable[[str], Optional[dict]] = None,
    article_delay: float = ARTICLE_FETCH_DELAY,
    sleep: Callable[[float], None] = time.sleep,
):
    """Fetch + push every enabled feed, new long-form posts with their bodies.
    One feed's failure never sinks the others, and an article read never sinks
    its feed.

    ``kinds`` scopes the round to a slice of probe-config (the scheduler runs
    For You and the rest on different cadences); None means every feed.
    """
    fetch = fetch or (lambda feed: fetch_feed(feed, timeout_ms=timeout_ms))
    fetch_following = fetch_following or (lambda: fetch_following_users(timeout_ms=timeout_ms))
    fetch_article = fetch_article or (lambda tweet_id: fetch_tweet_article(tweet_id, timeout_ms=timeout_ms))
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

    reader = ArticleReader(fetch_article, article_delay, sleep)
    outcomes = []
    for feed in feeds:
        outcomes.append(_run_feed(client, feed, fetch, cache, reader))
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
    client: ProbeClient,
    feed: dict,
    fetch: Callable[[dict], list],
    cache: Optional[SeenCache],
    reader: ArticleReader,
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
    fresh, unread = _read_articles(channel_id, fresh, reader, outcome)
    try:
        outcome.result = client.ingest(channel_id, fresh)
    except ServerError as e:
        log.error('%s: ingest failed: %s', channel_id, e)
        outcome.error = str(e)
        return outcome
    if cache:
        # After the push, never before: recording first would drop these tweets
        # for good if the server rejected them. An article whose read raised stays
        # out, so the next round finds it new and reads it again.
        cache.record(channel_id, [t for t in fresh if t.get('id') not in unread])
    log.info(
        '%s: fetched %d (%d already pushed), new tweets %s, new items %s, parse errors %s, articles %d fetched, %d failed',
        channel_id,
        outcome.fetched,
        outcome.skipped,
        outcome.result.get('new_tweets'),
        outcome.result.get('new_items'),
        outcome.result.get('parse_errors'),
        outcome.articles_fetched,
        outcome.articles_failed,
    )
    return outcome


def _read_articles(
    channel_id: str, tweets: list, reader: ArticleReader, outcome: FeedOutcome
) -> tuple[list, set]:
    """Merge each long-form post's body into its tweet before the push.

    Returns the tweets to push — each article's block grown by the detail's, the
    tweet's own ``text`` untouched (on the detail path it is title + the whole body,
    and the card needs the title) — and the ids whose read did not happen: those
    are pushed as they are and kept out of the cache.

    Two outcomes are told apart. A read that **raises** (session, rate limit,
    timeout, or xbird failing to map the response) is transient: counted as failed,
    retried next round, and it opens the round's breaker so the remaining articles
    wait for that round too. A detail that answers **without a body** is X's final
    word — pushed as is and remembered like any other tweet.
    """
    pushed = []
    unread = set()
    for tweet in tweets:
        article = tweet.get('article')
        if not isinstance(article, dict) or not article.get('title'):
            pushed.append(tweet)
            continue
        tweet_id = tweet.get('id')
        read, detail = reader.read(channel_id, tweet_id)
        if not read:
            unread.add(tweet_id)
            outcome.articles_failed += 1
            pushed.append(tweet)
        elif detail is None:
            log.warning('%s: article %s: the detail carries no body', channel_id, tweet_id)
            pushed.append(tweet)
        else:
            pushed.append({**tweet, 'article': {**article, **detail}})
            outcome.articles_fetched += 1
    return pushed, unread


def _has_body(detail) -> bool:
    return isinstance(detail, dict) and any(
        isinstance(detail.get(k), str) and detail[k].strip() for k in ('content', 'plainText')
    )
