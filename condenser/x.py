"""X (Twitter) source: bird-output parsing + probe ingest (plan Phase 1).

Unlike Telegram and Hacker News, the server never talks to the upstream: X data
only exists inside the bird CLI's logged-in cookie session on the user's own
machine, so a **local probe** pushes it here (see ``probe/``). The server owns
the subscriptions (probe-config tells the probe what to fetch) and the archive.

Three feed kinds share one source: ``foryou`` (the algorithmic For You timeline,
sorted by ``first_seen_at`` like the HN front page — the algorithm resurfaces old
tweets and sorting those by ``created_at`` would insert them into timeline
history), ``following`` (the chronological "accounts you follow" timeline, i.e.
one subscription standing in for all of them) and one feed per followed account
(``kind='user'``) — the latter two sorted by ``created_at``, like a TG channel.

Following needs two filters nothing else does, because X pads it: injected ads
(dropped by author, against the follow list the probe syncs — they carry no
structural marker) and a thread's own ancestors (archived, but given no feed row
so months-old tweets cannot land in timeline history). See
``_apply_following_rules``.

bird's JSON follows X's internal API and its own flattening on top; neither is a
stable contract, so parsing is deliberately tolerant and every entry's raw JSON
is archived for a re-parse after a format drift.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from . import db, search
from .config import Settings
from .items import FOLLOWING_FEED, FORYOU_FEED, x_feed_kind

log = logging.getLogger('condenser.x')

FORYOU_NAME = 'X For You'
# The "Following" timeline — one subscription standing in for every account you
# follow. Unlike For You it is *not* a firehose: two consecutive calls overlapped
# 19/20, i.e. a stable time window rather than a fresh sample, which is what makes
# it cheap enough to join the aggregate timeline in full (~100-200 tweets/day).
FOLLOWING_NAME = 'X Following'

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
    # t.co expansion metadata (xbird >= 1.2.0; None from an older probe), normalized
    # to snake_case [{url, expanded_url, display_url, indices}] at this parse
    # boundary — the wire is camelCase but the DB column, envelope and both clients
    # speak snake_case, so the one entry point converts once.
    urls: Optional[list] = None
    # X's own language verdict (xbird >= 1.1.0; None from an older probe). Read
    # only by the For You language filter — no DB column, the raw archive keeps it.
    lang: Optional[str] = None
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
            'urls': json.dumps(self.urls, ensure_ascii=False) if self.urls else None,
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
    # Following-only (see _apply_following_rules): entries dropped whole because
    # their author is not someone you follow, and entries archived without a feed
    # row because they fell outside the age window.
    filtered_ads: int = 0
    filtered_old: int = 0
    # For You-only (see _apply_language_filter): entries dropped whole because
    # their language is outside the global whitelist.
    filtered_lang: int = 0

    def as_dict(self) -> dict:
        return {
            'received': self.received,
            'stored': self.stored,
            'new_tweets': self.new_tweets,
            'new_items': self.new_items,
            'parse_errors': self.parse_errors,
            'filtered_ads': self.filtered_ads,
            'filtered_old': self.filtered_old,
            'filtered_lang': self.filtered_lang,
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


def parse_urls(value: Any) -> Optional[list]:
    """xbird's camelCase url entities -> snake_case dicts; tolerant like media.

    An entry without a t.co ``url`` string is unusable (nothing to match in the
    text) and is skipped; missing expansion fields become None so the renderers'
    fallback path (keep the t.co) stays reachable per entry.
    """
    if not isinstance(value, list):
        return None
    urls = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get('url'), str):
            continue
        expanded = item.get('expandedUrl')
        display = item.get('displayUrl')
        indices = item.get('indices')
        urls.append(
            {
                'url': item['url'],
                'expanded_url': expanded if isinstance(expanded, str) else None,
                'display_url': display if isinstance(display, str) else None,
                'indices': indices if isinstance(indices, list) else None,
            }
        )
    return urls or None


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
        urls=parse_urls(raw.get('urls')),
        lang=raw.get('lang') if isinstance(raw.get('lang'), str) else None,
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
    # Both feed keys would survive HANDLE_RE unchanged, so the early return is not
    # about the value — it is about never letting a feed key take the account path,
    # where it would be handed to `bird user-tweets` as a handle.
    if handle in (FORYOU_FEED, FOLLOWING_FEED):
        return handle
    if not HANDLE_RE.match(handle):
        raise ValueError(f'invalid x handle: {value!r}')
    return handle


def default_name(channel_id: str) -> Optional[str]:
    """The display name to store at subscribe time.

    A followed account's real name is only known once the first push arrives
    (`_learn_user_identity`), so it stays NULL and clients fall back to the handle
    rather than rendering a placeholder next to the same handle.
    """
    return {FORYOU_FEED: FORYOU_NAME, FOLLOWING_FEED: FOLLOWING_NAME}.get(channel_id)


def default_config(channel_id: str) -> dict:
    kind = x_feed_kind(channel_id)
    if kind == 'user':
        return {'kind': kind, 'handle': channel_id}
    return {'kind': kind}


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
    defaults = {
        FORYOU_FEED: settings.condenser_x_home_count,
        FOLLOWING_FEED: settings.condenser_x_following_count,
    }
    return defaults.get(channel_id, settings.condenser_x_user_count)


def probe_config(settings: Settings) -> dict:
    """What the probe should fetch this round — driven purely by enabled subscriptions."""
    if not settings.condenser_x_enabled:
        return {'feeds': [], 'sync_following': False}
    feeds = []
    for sub in db.enabled_x_subscriptions():
        config = sub_config(sub)
        kind = x_feed_kind(sub.channel_id)
        feeds.append(
            {
                'channel_id': sub.channel_id,
                'kind': kind,
                'handle': config.get('handle') if kind == 'user' else None,
                'n': feed_count(config, sub.channel_id, settings),
            }
        )
    return {'feeds': feeds, 'sync_following': bool(feeds) and following_sync_due(settings)}


# --- followed accounts --------------------------------------------------------


def following_sync_due(settings: Settings) -> bool:
    """Should the probe re-crawl the follow list this round?

    The decision lives here rather than in the probe so the probe stays stateless:
    it asks what to do and does it. Gated on there being at least one feed —
    crawling ~15 pages for a source with nothing subscribed is pure cost.
    """
    synced_at = db.x_following_synced_at()
    if synced_at is None:
        return True
    return _now() - synced_at >= timedelta(hours=settings.condenser_x_following_sync_hours)


def parse_following_users(entries: list) -> list[dict]:
    """bird's follow-list objects -> storable rows, dropping what cannot be keyed.

    Tolerant for the same reason ``parse_tweet`` is: bird's output follows X's
    internal API, and one drifted entry must not reject a 732-account list. The
    handle is lowercased because it is matched against a feed entry's author
    handle, and X preserves each account's own capitalization in both places.
    """
    rows: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        handle = (entry.get('username') or '').strip().lstrip('@').lower()
        if not handle:
            continue
        user_id = entry.get('id')
        rows[handle] = {
            'handle': handle,
            'user_id': str(user_id) if user_id is not None else None,
            'name': entry.get('name') or None,
        }
    return list(rows.values())


def sync_following(entries: list) -> dict:
    """Store one follow-list crawl. Raises ValueError on a push we refuse to apply."""
    rows = parse_following_users(entries)
    if not rows and db.x_following_count():
        # An empty list disables the ad filter entirely (see ``ingest_tweets``), so a
        # transient bird failure yielding `[]` would silently let a whole sync
        # interval of ads through. Refusing is the visible failure, and the stored
        # list stays usable in the meantime.
        raise ValueError('refusing to replace a non-empty follow list with an empty one')
    synced_at = _now()
    db.replace_x_following(rows, synced_at)
    log.info('x following: stored %d accounts (from %d entries)', len(rows), len(entries))
    return {
        'received': len(entries),
        'stored': len(rows),
        'synced_at': synced_at.isoformat(sep=' ', timespec='seconds'),
    }


def describe_subscription(sub: db.Subscription) -> dict:
    config = sub_config(sub)
    return {
        'source': 'x',
        'channel_id': sub.channel_id,
        'kind': config.get('kind') or x_feed_kind(sub.channel_id),
        'handle': config.get('handle'),
        'user_id': config.get('user_id'),
        'name': sub.name,
        'enabled': bool(sub.enabled),
        'n': config.get('n'),
        # How much of this feed joins the aggregate timeline (sources/x.py owns the
        # rule). A followed account has no choice to make — subscribing is the setting.
        'aggregate': _aggregate_mode(sub),
        # For You's "filter by the global language preference" switch (inert on
        # other feeds — only algorithm-picked strangers are language-filtered).
        'lang_filter': bool(config.get('lang_filter')),
        'added_at': str(sub.added_at) if sub.added_at else None,
        'tweets': db.x_feed_item_count(sub.channel_id),
    }


def _aggregate_mode(sub: db.Subscription) -> str:
    # deferred: condenser.sources.x imports this module
    from .sources import x as x_source

    return x_source.aggregate_mode(sub.channel_id, sub)


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


@dataclass
class FollowingFilter:
    """What the two Following rules did to one push (plan §6.3)."""

    kept: list[ParsedTweet] = field(default_factory=list)  # body + feed row
    body_only: list[ParsedTweet] = field(default_factory=list)  # body, no feed row
    ads: int = 0  # dropped whole
    old: int = 0  # = len(body_only), named for the counter it feeds


def _apply_following_rules(channel_id: str, parsed: list[ParsedTweet], now: datetime, settings: Settings):
    """Split a Following push into kept / body-only / dropped (plan §6.3).

    Two rules, in this order, and only for the Following feed:

    ① **The author is not someone you follow** -> drop the entry whole. X injects
      ads into this timeline with no structural marker at all (bird dumps the tweet
      result, not the timeline entry, so ``promotedMetadata`` never reaches us), and
      the follow list caught 7 of 7 in a 100-entry sample with no false positive.
      An ad is noise all the way down, so not even its body is archived.

    ② **The tweet is older than the window** -> archive the body, build no feed row.
      X drags a thread's ancestors in for context and bird flattens them into
      ordinary entries; stored as feed items they would land in 2025-09 timeline
      history — invisible, but counted as unread. Keeping the body costs a few
      hundred bytes, keeps the ``reply_to_id`` chain complete for a future thread
      view, and reuses the path a quoted tweet already takes.

    An empty follow list disables ① entirely. That is the deliberate failure mode:
    before the probe has ever synced, the alternative is discarding every tweet as
    advertising, silently.
    """
    if channel_id != FOLLOWING_FEED:
        return FollowingFilter(kept=parsed)

    followed = db.x_following_handles()
    cutoff = now - timedelta(hours=settings.condenser_x_following_max_age_hours)
    out = FollowingFilter()
    for tweet in parsed:
        if followed and (tweet.author_handle or '').lower() not in followed:
            out.ads += 1
            continue
        if tweet.created_at is not None and tweet.created_at < cutoff:
            out.body_only.append(tweet)
            continue
        out.kept.append(tweet)
    out.old = len(out.body_only)
    if out.ads or out.old:
        log.info('x following: dropped %d ad(s), archived %d out-of-window tweet(s)', out.ads, out.old)
    return out


# Codes X uses where it decided the tweet has no (determinable) language — media-only
# tweets, bare links, hashtag piles. Not a language the reader opted out of, so they
# always pass ('zxx' measured at 2 of 40 on a real home timeline).
NON_LANGUAGE_CODES = {'und', 'zxx', 'qme', 'qam', 'qct', 'qht', 'qst', 'art'}


def _apply_language_filter(channel_id: str, parsed: list[ParsedTweet]) -> tuple[list[ParsedTweet], int]:
    """Drop For You tweets outside the global language whitelist (dropped whole,
    the ad filter's semantics: no body, no feed row, no search document).

    Only For You — a followed account posting in another language was still chosen
    by the reader; only the algorithm's picks are filtered. Armed by two settings
    at once: the For You subscription's ``config.lang_filter`` switch AND a
    non-empty global ``languages`` list. Everything unknowable passes (fail-open):
    a missing ``lang`` (pre-1.1.0 probe) must disarm the filter, not empty the
    timeline, and a non-language code marks a tweet with nothing to judge.
    """
    if channel_id != FORYOU_FEED:
        return parsed, 0
    sub = db.get_x_subscription(channel_id)
    if sub is None or not sub_config(sub).get('lang_filter'):
        return parsed, 0
    languages = db.get_languages()
    if not languages:
        return parsed, 0

    kept = []
    dropped = 0
    for tweet in parsed:
        if tweet.lang is None:
            kept.append(tweet)
            continue
        primary = tweet.lang.split('-')[0].lower()
        if primary in languages or primary in NON_LANGUAGE_CODES:
            kept.append(tweet)
        else:
            dropped += 1
    if dropped:
        log.info('x foryou: dropped %d tweet(s) outside languages %s', dropped, languages)
    return kept, dropped


def ingest_tweets(channel_id: str, entries: list, settings: Optional[Settings] = None) -> IngestResult:
    """Store one probe push into the archive. Idempotent by tweet id.

    Re-pushes are the norm (the probe's incremental cache only shrinks them, never
    guarantees they stop): tweet rows refresh so metrics move, feed rows are
    insert-only so ``first_seen_at`` stays the moment we first saw the tweet.
    """
    from .config import get_settings

    settings = settings or get_settings()
    now = _now()
    parsed, errors = _parse_batch(entries)
    filtered = _apply_following_rules(channel_id, parsed, now, settings)
    kept, filtered_lang = _apply_language_filter(channel_id, filtered.kept)
    # After the filters, so a dropped entry's quoted tweet is dropped with it — a
    # body-only entry keeps its quote, since that path is exactly what it lands in
    # itself. A *kept* tweet's foreign-language quote is archived normally: the
    # quote is part of the display unit, never independently recommended.
    embedded = _embedded_quotes(kept + filtered.body_only)

    feed_ids = [t.id for t in kept]
    body_only = filtered.body_only + embedded
    known_tweets = db.existing_x_tweet_ids(feed_ids + [t.id for t in body_only])
    known_items = db.existing_x_feed_item_ids(channel_id, feed_ids)

    for tweet in kept:
        db.upsert_x_tweet(tweet.row(now))
    for tweet in body_only:
        db.insert_x_tweet_if_absent(tweet.row(now))
    db.insert_x_feed_items(
        [
            {'channel_id': channel_id, 'tweet_id': tid, 'first_seen_at': now}
            for tid in feed_ids
            if tid not in known_items
        ]
    )
    # After the feed rows, never before: the indexer takes each tweet's sort
    # position from the feed it wins under the dedup priority, and a tweet with no
    # feed row yet would be read as a body-only archive entry and skipped. Re-pushes
    # re-index on purpose — an edited retweet's text moves, and so does the
    # position when a higher-priority feed starts carrying the tweet.
    search.index_x_tweets(feed_ids)

    result = IngestResult(
        received=len(entries),
        stored=len(kept),
        new_tweets=len({t.id for t in kept + body_only} - known_tweets),
        new_items=len(set(feed_ids) - known_items),
        parse_errors=errors,
        filtered_ads=filtered.ads,
        filtered_old=filtered.old,
        filtered_lang=filtered_lang,
    )
    _learn_user_identity(channel_id, kept)
    _record_push(channel_id, result, now)
    return result


def _learn_user_identity(channel_id: str, parsed: list[ParsedTweet]) -> None:
    """Fill a followed account's numeric id + display name from its own tweets.

    The subscription is keyed by handle (that is what the probe hands to bird), but
    the numeric id is what survives a rename — so we keep it as soon as a push
    reveals it, together with the account's current display name.

    Only a followed-account feed has an identity to learn. The early return is
    explicit rather than incidental: 'foryou'/'following' are not handles, so the
    first entry whose author happened to match would otherwise rename the feed.
    """
    if channel_id in (FORYOU_FEED, FOLLOWING_FEED):
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
    from . import verdict

    tweets_total, feed_items_total = db.x_counts()
    return {
        'source_enabled': settings.condenser_x_enabled,
        'subscribed': bool(db.list_x_subscriptions()),
        'tweets_total': tweets_total,
        'feed_items_total': feed_items_total,
        'last_push_at': db.get_meta(LAST_PUSH_META_KEY),
        'last_push_counts': _push_stats(),
        'parse_errors': _parse_error_total(),
        'verdict': verdict.status(settings),
    }
