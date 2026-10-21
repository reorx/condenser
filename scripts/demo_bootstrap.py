"""Bootstrap — and afterwards health-check — the App Store review demo server.

Condenser is a self-hosted single-user reader, so an Apple reviewer who installs
the app sees a login screen and nothing else. The demo server at
``condenser-demo.reorx.com`` is what the review notes point them at, and this
script is what puts content in it: subscribe to the Hacker News front page and a
handful of public RSS feeds, then verify that a reader actually sees items from
every source the demo carries.

Telegram is the one source this script cannot fill. The demo has no Telegram
session and must never have one, so its Telegram items are a snapshot of public
channels that ``scripts/demo_tg_snapshot.py`` loads *inside* the container. This
script only checks that the snapshot is there and that it is public-only.

It is written to be **idempotent**, because initialization and the pre-submission
health check are the same act. Re-running it against a live demo subscribes
nothing new (only a missing or paused feed is (re)subscribed), waits for content
that is already there, and re-asserts every invariant. Run it before every
submission; a non-zero exit means the reviewer would have been shown an empty or
incomplete app.

Usage::

    # password from the environment (never argv — it would land in shell history)
    CONDENSER_DEMO_PASSWORD=... uv run python scripts/demo_bootstrap.py \
        --url https://condenser-demo.reorx.com

    # or piped in, the dev-browser-login.sh precedent
    envops read-value .env -K CONDENSER_APP_PASSWORD --unsafe |
        uv run python scripts/demo_bootstrap.py --url http://127.0.0.1:8793 --password-stdin

What it asserts, and why each one is worth a failed exit:

1. **No Telegram session.** The demo must never carry a Telegram account — that
   would hand a reviewer someone's channels and the ability to post as them.
   This is the one check that is about safety rather than about the demo looking
   populated.
2. **Every Telegram subscription is a public channel** (it has a @username). A
   private channel can only have come from a real account, so this is the same
   safety line seen from the data side.
3. **The HN and RSS sources are enabled server-side** (``CONDENSER_HN_ENABLED`` /
   ``CONDENSER_RSS_ENABLED``), else the subscribe endpoints 503 and those
   sources would stay empty forever.
4. **Each demo source has items on the timeline, and nothing else does.** The
   timeline is polled per source because it is the reviewer's first screen; for
   HN, the admission rules (schema v14) mean "archived" and "on the timeline"
   are different statements, so the archive count is not evidence. X must not
   appear at all.
5. **The HN days list spans more than the current day**, which is how the 7-day
   hckrnews backfill reports that it landed.
"""

import argparse
import os
import sys
import time
from typing import Optional

import httpx

# The one feed the HN source has in v1; the subscribe endpoint rejects anything else.
FEED = 'front'
# Public feeds, picked 2026-10-21 for no rights question (public domain, CC, or
# blogs written to be syndicated), full text or images to open, and enough
# cadence between them that the RSS group always has something from this week.
# Stored as typed: the server keys a feed on its exact URL.
RSS_FEEDS = (
    'https://www.nasa.gov/feed/',
    'https://en.wikipedia.org/w/api.php?action=featuredfeed&feed=featured&feedformat=atom',
    'https://simonwillison.net/atom/everything/',
    'https://blog.cloudflare.com/rss/',
    'https://xkcd.com/atom.xml',
)
DEMO_SOURCES = ('hn', 'rss', 'telegram')
# Total wait for the first items of every source. The subscribe kicks fetch
# immediately, but the HN backfill is rate-limited to ~4s per imported day, so a
# fresh install needs roughly half a minute before the timeline has real history.
CONTENT_TIMEOUT = 300.0
POLL_INTERVAL = 5.0


class DemoCheckFailed(Exception):
    """An invariant the demo server has to satisfy before a submission."""


def read_password(from_stdin: bool) -> str:
    """The app password, from stdin or the environment — never from argv."""
    if from_stdin:
        return sys.stdin.read().strip()
    for var in ('CONDENSER_DEMO_PASSWORD', 'CONDENSER_APP_PASSWORD'):
        value = os.environ.get(var)
        if value:
            return value.strip()
    raise DemoCheckFailed(
        'no password: set CONDENSER_DEMO_PASSWORD (or CONDENSER_APP_PASSWORD), or pipe it in with --password-stdin'
    )


def get_json(client: httpx.Client, path: str, **params) -> object:
    res = client.get(path, params=params or None)
    if res.status_code != 200:
        raise DemoCheckFailed(f'GET {path} -> {res.status_code} {res.text[:200]}')
    return res.json()


def login(client: httpx.Client, password: str) -> None:
    """Exchange the app password for the session cookie the client keeps."""
    res = client.post('/api/auth/login', json={'password': password})
    if res.status_code == 401:
        raise DemoCheckFailed('the app password was rejected — is this the demo server, and is the password current?')
    if res.status_code != 200:
        raise DemoCheckFailed(f'login failed: {res.status_code} {res.text[:200]}')


def assert_no_telegram(client: httpx.Client) -> None:
    """A demo server carrying a real Telegram session would expose an account."""
    status = get_json(client, '/api/tg/status')
    if status.get('status') == 'authorized':
        raise DemoCheckFailed(
            'this server has a Telegram session connected. A demo server must never carry a Telegram '
            'account (its Telegram items are a snapshot, scripts/demo_tg_snapshot.py) — disconnect it in '
            'Settings before pointing App Review at it.'
        )


def check_telegram_snapshot(client: httpx.Client) -> list[dict]:
    """The snapshot's channels are subscribed, and every one of them is public."""
    subs = get_json(client, '/api/subscriptions')
    if not subs:
        raise DemoCheckFailed(
            'no Telegram channels — load the snapshot inside the container with scripts/demo_tg_snapshot.py refresh'
        )
    private = [str(s['channel_id']) for s in subs if not s.get('username')]
    if private:
        raise DemoCheckFailed(f'Telegram channels without a public @username: {", ".join(private)}')
    return subs


def ensure_hn_subscription(client: httpx.Client) -> dict:
    """Subscribe to the HN front page if needed; returns the resulting status."""
    status = get_json(client, '/api/hn/status')
    if not status.get('source_enabled'):
        raise DemoCheckFailed('the HN source is off server-side (CONDENSER_HN_ENABLED=false) — nothing can be sampled')
    if status.get('subscribed') and status.get('enabled'):
        print('· hn front feed already subscribed and enabled')
        return status
    # Also the re-enable path for a paused row; the endpoint kicks a sampling
    # round either way, and only schedules the history backfill on first create.
    res = client.post('/api/sources/hn/subscriptions', json={'channel_id': FEED})
    if res.status_code != 200:
        raise DemoCheckFailed(f'subscribe failed: {res.status_code} {res.text[:200]}')
    print(f'· subscribed to the hn {FEED} feed')
    return get_json(client, '/api/hn/status')


def ensure_rss_subscriptions(client: httpx.Client) -> None:
    """Subscribe every demo feed that is missing or paused; leave the rest alone.

    POSTing an existing feed would also be harmless, but only-what-is-missing keeps
    a re-run from resetting fetch backoff on feeds that are merely slow today.
    """
    status = get_json(client, '/api/rss/status')
    if not status.get('source_enabled'):
        raise DemoCheckFailed('the RSS source is off server-side (CONDENSER_RSS_ENABLED=false)')
    enabled = {s['url'] for s in get_json(client, '/api/sources/rss/subscriptions') if s['enabled']}
    missing = [url for url in RSS_FEEDS if url not in enabled]
    for url in missing:
        res = client.post('/api/sources/rss/subscriptions', json={'url': url})
        if res.status_code != 200:
            raise DemoCheckFailed(f'rss subscribe failed for {url}: {res.status_code} {res.text[:200]}')
        print(f'· subscribed to {url}')
    if not missing:
        print(f'· all {len(RSS_FEEDS)} rss feeds already subscribed and enabled')


def wait_for_sources(client: httpx.Client, timeout: float) -> dict[str, list[dict]]:
    """Poll the reader's own first screen, per source, until every demo source has items.

    Deliberately the timeline and not an archive count: since schema v14 an HN
    story is archived long before it is *admitted*, and only admitted ones are on
    screen.
    """
    deadline = time.monotonic() + timeout
    found: dict[str, list[dict]] = {}
    last = ''
    while True:
        for source in DEMO_SOURCES:
            if source not in found:
                items = get_json(client, '/api/timeline', limit=30, source=source).get('items') or []
                if items:
                    found[source] = items
        missing = [s for s in DEMO_SOURCES if s not in found]
        if not missing:
            return found
        note = ', '.join(missing)
        if note != last:
            print(f'· waiting for the first items of: {note}')
            last = note
        if time.monotonic() >= deadline:
            raise DemoCheckFailed(
                f'no timeline items for {note} after {timeout:.0f}s. Check the container logs, and '
                '/api/hn/status or /api/rss/status for last_error.'
            )
        time.sleep(POLL_INTERVAL)


def assert_demo_sources_only(client: httpx.Client) -> None:
    """Any other source on the timeline means the demo is showing a real reading list."""
    items = get_json(client, '/api/timeline', limit=100).get('items') or []
    foreign = sorted({str(item.get('source')) for item in items} - set(DEMO_SOURCES))
    if foreign:
        raise DemoCheckFailed(f'the timeline carries non-demo items ({", ".join(foreign)}) — this is not a clean demo')


def check_hn_days(client: httpx.Client) -> list[dict]:
    days = get_json(client, '/api/timeline/days', source='hn')
    if not days:
        raise DemoCheckFailed(
            '/api/timeline/days has no hn days while the timeline has items — the calendar would be blank'
        )
    return days


def check_sidebar(client: httpx.Client) -> dict[str, int]:
    """The sidebar's own view of the demo: every subscription enabled. Returns unread per source."""
    groups = {g['source']: g['subscriptions'] for g in get_json(client, '/api/sources')}
    missing = [s for s in DEMO_SOURCES if s not in groups]
    if missing:
        raise DemoCheckFailed(f'/api/sources has no group for {", ".join(missing)} — the sidebar would not show it')
    hn = next((s for s in groups['hn'] if s.get('channel_id') == FEED), None)
    if hn is None or not hn.get('enabled'):
        raise DemoCheckFailed(f'the hn {FEED} feed is missing or paused in /api/sources')
    rss = {s['channel_id']: s for s in groups['rss']}
    paused = [url for url in RSS_FEEDS if not rss.get(url, {}).get('enabled')]
    if paused:
        raise DemoCheckFailed(f'rss feeds missing or paused in /api/sources: {", ".join(paused)}')
    return {source: sum(int(s.get('unread') or 0) for s in groups[source]) for source in DEMO_SOURCES}


def run(url: str, password: str, timeout: float) -> None:
    with httpx.Client(base_url=url.rstrip('/'), timeout=30.0, follow_redirects=True) as client:
        login(client, password)
        assert_no_telegram(client)
        channels = check_telegram_snapshot(client)
        ensure_hn_subscription(client)
        ensure_rss_subscriptions(client)
        wait_for_sources(client, timeout)
        assert_demo_sources_only(client)
        days = check_hn_days(client)
        unread = check_sidebar(client)
        hn = get_json(client, '/api/hn/status')
        rss = get_json(client, '/api/rss/status')

    span = f'{days[-1]["date"]} … {days[0]["date"]}' if len(days) > 1 else days[0]['date']
    stories = sum(int(d['count']) for d in days)
    names = ', '.join(f'@{c["username"]}' for c in channels)
    print(
        f'OK  {url}\n'
        f'    hn:       {stories} stories across {len(days)} day(s) ({span}), {hn.get("stories_total", 0)} archived\n'
        f'    rss:      {rss.get("feeds_enabled", 0)} feeds, {rss.get("entries_total", 0)} entries\n'
        f'    telegram: {len(channels)} channels ({names})\n'
        f'    unread:   ' + ', '.join(f'{s} {unread[s]}' for s in DEMO_SOURCES)
    )
    if len(days) < 2:
        print(
            'note: only one HN day is on the timeline — the hckrnews backfill may still be running; re-run to confirm.'
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', required=True, help='demo server base URL, e.g. https://condenser-demo.reorx.com')
    parser.add_argument('--password-stdin', action='store_true', help='read the app password from stdin')
    parser.add_argument('--timeout', type=float, default=CONTENT_TIMEOUT, help='seconds to wait for timeline content')
    args = parser.parse_args(argv)

    try:
        run(args.url, read_password(args.password_stdin), args.timeout)
    except DemoCheckFailed as exc:
        print(f'FAIL  {exc}', file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f'FAIL  cannot reach {args.url}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
