"""Bootstrap — and afterwards health-check — the App Store review demo server.

Condenser is a self-hosted single-user reader, so an Apple reviewer who installs
the app sees a login screen and nothing else. The demo server at
``condenser-demo.reorx.com`` is what the review notes point them at, and this
script is what puts content in it: subscribe to the Hacker News front page and
verify that a reader actually sees stories.

It is written to be **idempotent**, because initialization and the pre-submission
health check are the same act. Re-running it against a live demo subscribes
nothing new (the endpoint takes the re-enable path), waits for content that is
already there, and re-asserts every invariant. Run it before every submission;
a non-zero exit means the reviewer would have been shown an empty app.

Usage::

    # password from the environment (never argv — it would land in shell history)
    CONDENSER_DEMO_PASSWORD=... uv run python scripts/demo_bootstrap.py \
        --url https://condenser-demo.reorx.com

    # or piped in, the dev-browser-login.sh precedent
    envops read-value .env -K CONDENSER_APP_PASSWORD --unsafe |
        uv run python scripts/demo_bootstrap.py --url http://127.0.0.1:8793 --password-stdin

What it asserts, and why each one is worth a failed exit:

1. **No Telegram session.** The demo must never carry the author's own account —
   that would hand a reviewer a stranger's private channels. This is the one
   check that is about safety rather than about the demo looking populated.
2. **The HN source is enabled server-side** (``CONDENSER_HN_ENABLED``), else the
   subscribe endpoint 503s and the timeline would stay empty forever.
3. **The timeline actually returns items, and every one of them is HN.** The
   admission rules (schema v14) mean "stories are archived" and "stories are on
   the timeline" are different statements, so the archive count is not evidence.
   Polling the timeline is; it is literally the reviewer's first screen.
4. **The days list spans more than the current day**, which is how the 7-day
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
# Total wait for the first admitted stories. The subscribe kick samples immediately,
# but the backfill is rate-limited to ~4s per imported day, so a fresh install needs
# roughly half a minute before the timeline has real history.
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
    """A demo server carrying a real Telegram session would expose private channels."""
    status = get_json(client, '/api/tg/status')
    if status.get('status') == 'authorized':
        raise DemoCheckFailed(
            'this server has a Telegram session connected. A demo server must stay HN-only — '
            'disconnect it in Settings before pointing App Review at it.'
        )


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


def wait_for_timeline(client: httpx.Client, timeout: float) -> list[dict]:
    """Poll the reader's own first screen until it has items (or give up loudly).

    Deliberately the timeline and not ``stories_total``: since schema v14 a story
    is archived long before it is *admitted*, and only admitted ones are on screen.
    """
    deadline = time.monotonic() + timeout
    last = ''
    while True:
        page = get_json(client, '/api/timeline', limit=30)
        items = page.get('items') or []
        if items:
            return items
        hn = get_json(client, '/api/hn/status')
        note = f'archived={hn.get("stories_total", 0)} backfill_pending={len(hn.get("backfill_pending_days") or [])}'
        if note != last:
            print(f'· waiting for the first admitted stories ({note})')
            last = note
        if time.monotonic() >= deadline:
            raise DemoCheckFailed(
                f'no timeline items after {timeout:.0f}s ({note}). '
                'Check the container logs for hn sampling errors, and /api/hn/status for last_error.'
            )
        time.sleep(POLL_INTERVAL)


def assert_hn_only(items: list[dict]) -> None:
    """Any non-HN item means the demo is showing somebody's real reading list."""
    foreign = sorted({str(item.get('source')) for item in items} - {'hn'})
    if foreign:
        raise DemoCheckFailed(f'the timeline carries non-HN items ({", ".join(foreign)}) — this is not a clean demo')


def check_days(client: httpx.Client) -> list[dict]:
    days = get_json(client, '/api/timeline/days')
    if not days:
        raise DemoCheckFailed('/api/timeline/days is empty while the timeline has items — the calendar would be blank')
    return days


def check_sources(client: httpx.Client) -> int:
    """The sidebar's own view of the demo: an enabled HN feed. Returns its unread count."""
    groups = get_json(client, '/api/sources')
    hn = next((g for g in groups if g.get('source') == 'hn'), None)
    if hn is None:
        raise DemoCheckFailed('/api/sources has no hn group — the sidebar would show no feed to open')
    feed = next((s for s in hn['subscriptions'] if s.get('channel_id') == FEED), None)
    if feed is None or not feed.get('enabled'):
        raise DemoCheckFailed(f'the hn {FEED} feed is missing or paused in /api/sources')
    return int(feed.get('unread') or 0)


def run(url: str, password: str, timeout: float) -> None:
    with httpx.Client(base_url=url.rstrip('/'), timeout=30.0, follow_redirects=True) as client:
        login(client, password)
        assert_no_telegram(client)
        ensure_hn_subscription(client)
        items = wait_for_timeline(client, timeout)
        assert_hn_only(items)
        days = check_days(client)
        unread = check_sources(client)
        hn = get_json(client, '/api/hn/status')

    span = f'{days[-1]["date"]} … {days[0]["date"]}' if len(days) > 1 else days[0]['date']
    total = sum(int(d['count']) for d in days)
    print(
        f'OK  {url}: {total} stories on the timeline across {len(days)} day(s) ({span}), '
        f'{unread} unread, {hn.get("stories_total", 0)} archived'
    )
    if len(days) < 2:
        print('note: only one day is on the timeline — the hckrnews backfill may still be running; re-run to confirm.')


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
