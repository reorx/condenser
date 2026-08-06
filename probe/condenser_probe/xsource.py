"""The X reader: xbird's GraphQL client, driven from probe-config feed entries.

xbird reads the browser's logged-in X cookies, so it only works on the user's own
machine — which is the whole reason the probe exists.

What reaches the server is xbird's **serialized** tweet (``to_json``), byte-identical
to what ``xbird … --json`` prints. That is deliberate and load-bearing: the server
parses these camelCase keys (``condenser.x.parse_tweet``) and archives each entry
verbatim as ``raw``, and the seen cache keys off ``id``. So the wire shape is a
contract shared with the archive, not an implementation detail of whoever fetched
the tweet — handing the server pydantic-native snake_case would silently orphan
every historical row.

Two adaptations to xbird's library semantics:

* it returns remote failures as **values** (``result.success``), never exceptions.
  A failure that read as an empty page would report the round as OK and hide a dead
  X session indefinitely, so every one is raised as :class:`XSourceError` — the same
  signal a non-zero CLI exit used to give, and the same one ``runner`` isolates per
  feed.
* the client owns an httpx connection pool, so it is created and closed per call.
  ``watch`` runs for days; re-resolving credentials each time is what lets a
  re-login in the browser take effect without restarting the probe.
"""

import logging
import time
from typing import Optional

from xbird import TwitterClient, resolve_credentials
from xbird.types import to_json

log = logging.getLogger('condenser_probe.xsource')

#: Tweets per feed when probe-config does not say (it always does; this is a floor).
DEFAULT_COUNT = 20
#: Per X API request, not per round — a Following crawl makes ~15 of them.
DEFAULT_TIMEOUT_MS = 20000

# One page of `following` comes back around 50 accounts however many are asked for,
# so the cap is about bounding a runaway cursor chain, not about the total: 40 pages
# covered 732 accounts with the cursor exhausted, in ~15 requests.
FOLLOWING_MAX_PAGES = 40
FOLLOWING_PAGE_SIZE = 20
# X is more aggressive about automated reading than Telegram, and this is the one
# place the probe makes a burst of requests. The `bird` CLI paced its --all crawl
# the same way; dropping the pacing would be a silent change in exposure.
FOLLOWING_PAGE_DELAY = 1.0


class XSourceError(RuntimeError):
    pass


def _session(timeout_ms: int) -> TwitterClient:
    """A client for one call. Raises if the browser session cannot be read."""
    cookies = resolve_credentials()
    if cookies is None:
        raise XSourceError('no X credentials — log in to x.com in Safari/Chrome/Firefox, or set AUTH_TOKEN and CT0')
    return TwitterClient(cookies, timeout_ms=timeout_ms)


def _tweets(result, what: str) -> list:
    if not result.success:
        raise XSourceError(f'{what}: {result.error}')
    return [to_json(tweet) for tweet in result.tweets]


def fetch_feed(feed: dict, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> list:
    """Fetch one probe-config feed entry's recent tweets, in bird's JSON shape."""
    kind = feed.get('kind')
    n = feed.get('n') or DEFAULT_COUNT
    if kind not in ('home', 'following', 'user'):
        raise XSourceError(f'unknown feed kind: {kind!r}')
    handle = (feed.get('handle') or feed.get('channel_id')) if kind == 'user' else None
    if kind == 'user' and not handle:
        raise XSourceError(f'user feed without a handle: {feed!r}')

    with _session(timeout_ms) as client:
        if kind == 'home':
            # X's algorithmic feed.
            return _tweets(client.get_home_timeline(n), 'For You')
        if kind == 'following':
            # Same account, the chronological "accounts you follow" timeline.
            return _tweets(client.get_home_latest_timeline(n), 'Following')
        # The subscription key is the handle (that is what a reader types), but the
        # timeline endpoint takes the numeric id — which is also what survives a rename.
        lookup = client.get_user_id_by_username(str(handle))
        if not lookup.success:
            raise XSourceError(f'@{handle}: {lookup.error}')
        return _tweets(client.get_user_tweets_paged(lookup.user_id, n), f'@{handle}')


def fetch_following_users(timeout_ms: int = DEFAULT_TIMEOUT_MS, max_pages: int = FOLLOWING_MAX_PAGES) -> list:
    """The accounts the logged-in user follows, as bird's raw user objects.

    All-or-nothing on purpose: the server *replaces* its list wholesale and drops
    Following entries whose author is missing from it, so pushing half a crawl
    would silently discard the missing accounts' tweets as advertising. A failed
    page therefore raises instead of returning what it collected — the stale list
    on the server keeps working until the next round.
    """
    with _session(timeout_ms) as client:
        me = client.get_current_user()
        if not me.success:
            raise XSourceError(f'follow list: {me.error}')

        users: dict[str, dict] = {}
        cursor: Optional[str] = None
        for page in range(max_pages):
            if page:
                time.sleep(FOLLOWING_PAGE_DELAY)
            result = client.get_following(me.user.id, FOLLOWING_PAGE_SIZE, cursor)
            if not result.success:
                raise XSourceError(f'follow list: page {page + 1} failed: {result.error}')
            # The same account repeats across cursor pages; a page that adds nothing
            # new means the chain is looping rather than advancing.
            added = [entry for entry in result.users if entry.id not in users]
            for entry in added:
                users[entry.id] = to_json(entry)
            if not result.next_cursor or not added or result.next_cursor == cursor:
                break
            cursor = result.next_cursor
        else:
            log.warning('follow list: stopped at the %d-page cap, the list may be incomplete', max_pages)
    return list(users.values())


def check_auth(timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str:
    """The logged-in account, or raise — the ``whoami`` half of ``probe check``."""
    with _session(timeout_ms) as client:
        result = client.get_current_user()
    if not result.success:
        raise XSourceError(f'could not read the X session: {result.error}')
    return f'@{result.user.username} ({result.user.name})'
