"""X (Twitter) source: bird-output parsing + probe ingest (plan Phase 1).

Unlike Telegram and Hacker News, the server never talks to the upstream: X data
only exists inside the bird CLI's logged-in cookie session on the user's own
machine, so a **local probe** pushes it here (see ``probe/``). The server owns
the subscriptions (probe-config tells the probe what to fetch) and the archive.

Two feed kinds share one source: ``foryou`` (the algorithmic For You timeline,
sorted by ``first_seen_at`` like the HN front page — the algorithm resurfaces old
tweets and sorting those by ``created_at`` would insert them into timeline
history) and one feed per followed account (``kind='user'``, sorted by
``created_at``, like a TG channel).

bird's JSON follows X's internal API and its own flattening on top; neither is a
stable contract, so parsing is deliberately tolerant and every entry's raw JSON
is archived for a re-parse after a format drift.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from . import db
from .config import Settings

log = logging.getLogger('condenser.x')

FORYOU_FEED = 'foryou'
FORYOU_NAME = 'X For You'

# X handles: 1-15 chars of [A-Za-z0-9_]. Stored lowercased so a handle is one
# subscription no matter how the user typed it.
HANDLE_RE = re.compile(r'^[A-Za-z0-9_]{1,15}$')
RT_PREFIX_RE = re.compile(r'^RT @([A-Za-z0-9_]{1,15}):')

# bird emits Twitter's legacy timestamp form: 'Thu Jul 23 14:46:20 +0000 2026'.
CREATED_AT_FORMAT = '%a %b %d %H:%M:%S %z %Y'

# app_meta keys for probe activity (mirrors the hn_* status keys)
LAST_PUSH_META_KEY = 'x_last_push_at'
PUSH_STATS_META_KEY = 'x_push_stats'
PARSE_ERRORS_META_KEY = 'x_parse_errors'


class XParseError(ValueError):
    """An entry that cannot be stored at all (no usable tweet id)."""


@dataclass
class ParsedTweet:
    id: int
    author_id: Optional[int] = None
    author_handle: Optional[str] = None
    author_name: Optional[str] = None
    text: Optional[str] = None
    created_at: Optional[datetime] = None
    media: Optional[list] = None
    metrics: Optional[dict] = None
    quote_of: Optional[int] = None
    rt_of_handle: Optional[str] = None
    reply_to_id: Optional[int] = None
    article: Optional[dict] = None
    raw: dict = field(default_factory=dict)
    # non-fatal drift (a field bird emitted in an unexpected shape); the tweet is
    # still stored, the count surfaces in /api/x/status so drift is noticed
    warnings: list[str] = field(default_factory=list)

    def row(self, fetched_at: datetime) -> dict:
        return {
            'id': self.id,
            'author_id': self.author_id,
            'author_handle': self.author_handle,
            'author_name': self.author_name,
            'text': self.text,
            'created_at': self.created_at,
            'media': json.dumps(self.media, ensure_ascii=False) if self.media else None,
            'metrics': json.dumps(self.metrics) if self.metrics else None,
            'quote_of': self.quote_of,
            'rt_of_handle': self.rt_of_handle,
            'reply_to_id': self.reply_to_id,
            'article': json.dumps(self.article, ensure_ascii=False) if self.article else None,
            'raw': json.dumps(self.raw, ensure_ascii=False),
            'fetched_at': fetched_at,
        }


@dataclass
class IngestResult:
    received: int = 0
    stored: int = 0  # entries that produced/refreshed an x_tweets row
    new_tweets: int = 0  # tweet rows created (includes embedded quoted tweets)
    new_items: int = 0  # feed appearances registered for this channel
    parse_errors: int = 0

    def as_dict(self) -> dict:
        return {
            'received': self.received,
            'stored': self.stored,
            'new_tweets': self.new_tweets,
            'new_items': self.new_items,
            'parse_errors': self.parse_errors,
        }


# --- parsing -----------------------------------------------------------------


def _as_int(value: Any) -> Optional[int]:
    """bird sends ids as strings (JS large-integer safety); store them as int64."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_created_at(value: Any) -> Optional[datetime]:
    """Legacy Twitter timestamp -> naive UTC (the project-wide storage convention)."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.strptime(value, CREATED_AT_FORMAT)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_tweet(raw: Any) -> ParsedTweet:
    """One bird entry -> a storable tweet. Raises XParseError only when unkeyable."""
    if not isinstance(raw, dict):
        raise XParseError(f'entry is not an object: {type(raw).__name__}')
    tweet_id = _as_int(raw.get('id'))
    if tweet_id is None:
        raise XParseError(f'entry without a usable id: {json.dumps(raw, ensure_ascii=False)[:200]}')

    warnings: list[str] = []
    created_at = parse_created_at(raw.get('createdAt'))
    if created_at is None and raw.get('createdAt') is not None:
        warnings.append('createdAt')

    author = raw.get('author') if isinstance(raw.get('author'), dict) else {}
    text = raw.get('text') if isinstance(raw.get('text'), str) else None
    rt = RT_PREFIX_RE.match(text) if text else None
    media = raw.get('media') if isinstance(raw.get('media'), list) else None
    quoted = raw.get('quotedTweet') if isinstance(raw.get('quotedTweet'), dict) else None

    return ParsedTweet(
        id=tweet_id,
        author_id=_as_int(raw.get('authorId')),
        author_handle=author.get('username'),
        author_name=author.get('name'),
        text=text,
        created_at=created_at,
        media=media or None,
        metrics={
            'reply_count': _as_int(raw.get('replyCount')) or 0,
            'retweet_count': _as_int(raw.get('retweetCount')) or 0,
            'like_count': _as_int(raw.get('likeCount')) or 0,
        },
        quote_of=_as_int(quoted.get('id')) if quoted else None,
        rt_of_handle=rt.group(1) if rt else None,
        reply_to_id=_as_int(raw.get('inReplyToStatusId')),
        article=raw.get('article') if isinstance(raw.get('article'), dict) else None,
        raw=raw,
        warnings=warnings,
    )


# --- subscriptions ------------------------------------------------------------


def normalize_channel_id(value: str) -> str:
    """'@NovoReorx ' -> 'novoreorx'; 'foryou' stays. Raises ValueError on junk.

    The handle is the subscription key (the probe feeds it straight to
    ``bird user-tweets``); the numeric user id — which survives a rename — is
    learned from the first push and kept in the subscription config.
    """
    handle = (value or '').strip().lstrip('@').lower()
    if handle == FORYOU_FEED:
        return FORYOU_FEED
    if not HANDLE_RE.match(handle):
        raise ValueError(f'invalid x handle: {value!r}')
    return handle


def default_config(channel_id: str) -> dict:
    if channel_id == FORYOU_FEED:
        return {'kind': 'home'}
    return {'kind': 'user', 'handle': channel_id}


def sub_config(sub: db.Subscription) -> dict:
    try:
        return json.loads(sub.config) if sub.config else default_config(sub.channel_id)
    except ValueError:
        return default_config(sub.channel_id)


def feed_count(config: dict, channel_id: str, settings: Settings) -> int:
    """How many tweets the probe fetches for this feed (per-feed override wins)."""
    n = config.get('n')
    if isinstance(n, int) and n > 0:
        return n
    if channel_id == FORYOU_FEED:
        return settings.condenser_x_home_count
    return settings.condenser_x_user_count


def probe_config(settings: Settings) -> dict:
    """What the probe should fetch this round — driven purely by enabled subscriptions."""
    if not settings.condenser_x_enabled:
        return {'feeds': []}
    feeds = []
    for sub in db.enabled_x_subscriptions():
        config = sub_config(sub)
        kind = 'home' if sub.channel_id == FORYOU_FEED else 'user'
        feeds.append(
            {
                'channel_id': sub.channel_id,
                'kind': kind,
                'handle': config.get('handle') if kind == 'user' else None,
                'n': feed_count(config, sub.channel_id, settings),
            }
        )
    return {'feeds': feeds}


def describe_subscription(sub: db.Subscription) -> dict:
    config = sub_config(sub)
    return {
        'source': 'x',
        'channel_id': sub.channel_id,
        'kind': config.get('kind') or ('home' if sub.channel_id == FORYOU_FEED else 'user'),
        'handle': config.get('handle'),
        'user_id': config.get('user_id'),
        'name': sub.name,
        'enabled': bool(sub.enabled),
        'n': config.get('n'),
        'added_at': str(sub.added_at) if sub.added_at else None,
        'tweets': db.x_feed_item_count(sub.channel_id),
    }


# --- ingest -------------------------------------------------------------------


def _now() -> datetime:
    """Naive UTC now (storage convention); test seam."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_batch(entries: list) -> tuple[list[ParsedTweet], int]:
    parsed: list[ParsedTweet] = []
    errors = 0
    for entry in entries:
        try:
            tweet = parse_tweet(entry)
        except XParseError as e:
            log.warning('x ingest: dropping unparseable entry: %s', e)
            errors += 1
            continue
        if tweet.warnings:
            # kept (raw is archived), but counted so a systematic drift is visible
            log.warning('x ingest: tweet %s has unexpected fields: %s', tweet.id, ','.join(tweet.warnings))
            errors += 1
        parsed.append(tweet)
    return parsed, errors


def _embedded_quotes(parsed: list[ParsedTweet]) -> list[ParsedTweet]:
    """Quoted tweets carried inside feed entries, as their own archive rows."""
    out = []
    for tweet in parsed:
        quoted = tweet.raw.get('quotedTweet')
        if not isinstance(quoted, dict):
            continue
        try:
            out.append(parse_tweet(quoted))
        except XParseError as e:
            log.warning('x ingest: unparseable quoted tweet inside %s: %s', tweet.id, e)
    return out


def ingest_tweets(channel_id: str, entries: list) -> IngestResult:
    """Store one probe push into the archive. Idempotent by tweet id.

    The probe is stateless — every round pushes the feed's most recent N tweets —
    so re-pushes are the norm: tweet rows refresh (metrics move), feed rows are
    insert-only so ``first_seen_at`` stays the moment we first saw the tweet.
    """
    now = _now()
    parsed, errors = _parse_batch(entries)
    embedded = _embedded_quotes(parsed)

    feed_ids = [t.id for t in parsed]
    known_tweets = db.existing_x_tweet_ids(feed_ids + [t.id for t in embedded])
    known_items = db.existing_x_feed_item_ids(channel_id, feed_ids)

    for tweet in parsed:
        db.upsert_x_tweet(tweet.row(now))
    for tweet in embedded:
        db.insert_x_tweet_if_absent(tweet.row(now))
    db.insert_x_feed_items(
        [
            {'channel_id': channel_id, 'tweet_id': tid, 'first_seen_at': now}
            for tid in feed_ids
            if tid not in known_items
        ]
    )

    result = IngestResult(
        received=len(entries),
        stored=len(parsed),
        new_tweets=len({t.id for t in parsed + embedded} - known_tweets),
        new_items=len(set(feed_ids) - known_items),
        parse_errors=errors,
    )
    _learn_user_identity(channel_id, parsed)
    _record_push(channel_id, result, now)
    return result


def _learn_user_identity(channel_id: str, parsed: list[ParsedTweet]) -> None:
    """Fill a followed account's numeric id + display name from its own tweets.

    The subscription is keyed by handle (that is what the probe hands to bird), but
    the numeric id is what survives a rename — so we keep it as soon as a push
    reveals it, together with the account's current display name.
    """
    if channel_id == FORYOU_FEED:
        return
    sub = db.get_x_subscription(channel_id)
    if sub is None:
        return
    author = next((t for t in parsed if (t.author_handle or '').lower() == channel_id), None)
    if author is None:
        return
    config = sub_config(sub)
    updates: dict = {}
    if author.author_id is not None and config.get('user_id') != str(author.author_id):
        config['user_id'] = str(author.author_id)
        updates['config'] = config
    if author.author_name and sub.name != author.author_name:
        updates['name'] = author.author_name
    if updates:
        db.update_x_subscription(channel_id, **updates)


def _record_push(channel_id: str, result: IngestResult, now: datetime) -> None:
    stamp = now.isoformat(sep=' ', timespec='seconds')
    stats = _push_stats()
    stats[channel_id] = {'at': stamp, **result.as_dict()}
    db.set_meta(PUSH_STATS_META_KEY, json.dumps(stats))
    db.set_meta(LAST_PUSH_META_KEY, stamp)
    if result.parse_errors:
        db.set_meta(PARSE_ERRORS_META_KEY, str(_parse_error_total() + result.parse_errors))


def _push_stats() -> dict:
    raw = db.get_meta(PUSH_STATS_META_KEY)
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def _parse_error_total() -> int:
    try:
        return int(db.get_meta(PARSE_ERRORS_META_KEY) or 0)
    except ValueError:
        return 0


# --- status -------------------------------------------------------------------


def status(settings: Settings) -> dict:
    tweets_total, feed_items_total = db.x_counts()
    return {
        'source_enabled': settings.condenser_x_enabled,
        'subscribed': bool(db.list_x_subscriptions()),
        'tweets_total': tweets_total,
        'feed_items_total': feed_items_total,
        'last_push_at': db.get_meta(LAST_PUSH_META_KEY),
        'last_push_counts': _push_stats(),
        'parse_errors': _parse_error_total(),
    }
