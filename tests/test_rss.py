"""Behavior tests for the RSS source, Phase 1: schema, fetching, ingest, OPML, endpoints.

HTTP is mocked by injecting ``fetch_feed`` into RssManager — no network. What is
*not* mocked is the parsing: every feed body here is either a real feed (curated
into ``tests/fixtures/rss/`` by ``tmp/make_rss_fixtures.py``) or a small synthetic
document built for one edge case, and feedparser runs on it for real. The whole
risk in this source is what real-world XML does, so a stubbed parser would test
nothing.

Plan: kb/plans/2026-08-20-rss-source-opml-llm-summary.md §10 Phase 1.
"""

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from condenser import db
from condenser.app import create_app

FIXTURES = Path(__file__).parent / 'fixtures' / 'rss'

# Fixed "now" (naive UTC, the storage convention) injected into the manager. Chosen
# to sit just after the real fixtures' newest entries, so the HN/Atom samples are
# inside the unread window and the (February) content:encoded sample is outside it.
NOW = datetime(2026, 8, 20, 12, 0)

HN_URL = 'https://news.ycombinator.com/rss'
ATOM_URL = 'https://simonwillison.net/atom/everything/'
BLOG_URL = 'https://reorx.com/feed.xml'


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def feed_xml(items_xml: str, title: str = 'Synthetic') -> bytes:
    """A minimal RSS 2.0 document around hand-written <item> blocks."""
    return (
        f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>'
        f'<link>https://example.com/</link>{items_xml}</channel></rss>'
    ).encode()


class FakeFetch:
    """url -> body bytes (or an Exception to raise, or None for a 304). Records calls.

    Mirrors the conditional-request contract: the manager hands us the stored
    validators, and the recorded call is what a test asserts against.
    """

    def __init__(self):
        self.bodies: dict[str, object] = {}
        self.headers: dict[str, tuple] = {}
        self.calls: list[tuple] = []

    def set(self, url, body, etag=None, last_modified=None):
        self.bodies[url] = body
        self.headers[url] = (etag, last_modified)

    async def __call__(self, url, etag=None, last_modified=None):
        from condenser.rss import FetchResult

        self.calls.append((url, etag, last_modified))
        if url not in self.bodies:
            raise KeyError(f'unexpected feed fetched: {url}')
        body = self.bodies[url]
        if isinstance(body, Exception):
            raise body
        new_etag, new_last_modified = self.headers[url]
        if body is None:
            return FetchResult(status=304, body=None, etag=new_etag, last_modified=new_last_modified)
        return FetchResult(status=200, body=body, etag=new_etag, last_modified=new_last_modified)


@pytest.fixture
def rss_env(env, monkeypatch):
    """The base env, plus the RSS source switched on (it ships off — plan §7)."""
    monkeypatch.setenv('CONDENSER_RSS_ENABLED', 'true')
    from condenser.config import get_settings

    get_settings.cache_clear()
    yield


def make_manager(fetch, now=NOW):
    from condenser.config import get_settings
    from condenser.rss import RssManager

    db.init_db(os.environ['CONDENSER_DB_PATH'])
    mgr = RssManager(get_settings(), fetch_feed=fetch)
    mgr._now = lambda: now
    return mgr


def entries(feed_url=None):
    query = db.RssEntry.select().order_by(db.RssEntry.id)
    if feed_url:
        query = query.where(db.RssEntry.feed_url == feed_url)
    return list(query)


# --- schema -------------------------------------------------------------------


def test_rss_tables_are_created(rss_env):
    """v15 is two new tables, so the upgrade is plain create_tables — no migration.
    (The version pin itself lives in test_hn.py, with every other schema version;
    the item key ``rss:{id}`` is covered by test_multi_source's roundtrip.)"""
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    from telememo import db as tdb

    tables = {r[0] for r in tdb.db.execute_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {'rss_feeds', 'rss_entries'} <= tables


# --- ingest -------------------------------------------------------------------


def test_a_round_archives_a_real_rss_feed(rss_env):
    """RSS 2.0 with no <guid> anywhere: the link is the dedup key (fallback 2)."""
    fetch = FakeFetch()
    fetch.set(HN_URL, fixture('rss2_no_guid.xml'))
    mgr = make_manager(fetch)
    db.add_rss_subscription(HN_URL)

    asyncio.run(mgr.poll_once())

    rows = entries(HN_URL)
    assert len(rows) == 3
    first = rows[0]
    assert first.title == 'Windows brings out the Rorschach test in everyone'
    assert first.link == 'https://devblogs.microsoft.com/oldnewthing/20030825-00/?p=42803'
    assert first.guid == first.link
    assert first.published_at == datetime(2026, 8, 20, 6, 16, 40)  # pubDate, converted to UTC
    assert first.first_seen_at == NOW
    assert 'Comments' in first.content


def test_a_round_archives_a_real_atom_feed(rss_env):
    """Atom: <id> is the dedup key (fallback 1) and <summary> is the content."""
    fetch = FakeFetch()
    fetch.set(ATOM_URL, fixture('atom.xml'))
    mgr = make_manager(fetch)
    db.add_rss_subscription(ATOM_URL)

    asyncio.run(mgr.poll_once())

    rows = entries(ATOM_URL)
    assert len(rows) == 3
    assert rows[0].guid == 'https://simonwillison.net/2026/Aug/19/smolmachines-untrusted-sandbox/'
    assert rows[0].published_at == datetime(2026, 8, 19, 23, 16, 0)
    assert '<p>' in rows[0].content


def test_content_encoded_wins_over_the_description(rss_env):
    """A feed carrying both gives the full article in content:encoded and a teaser in
    <description>; the archive is the summariser's raw material, so it takes the fuller one."""
    fetch = FakeFetch()
    fetch.set(BLOG_URL, fixture('content_encoded.xml'))
    mgr = make_manager(fetch)
    db.add_rss_subscription(BLOG_URL)

    asyncio.run(mgr.poll_once())

    row = entries(BLOG_URL)[0]
    assert row.content.startswith('<p>')  # content:encoded is HTML; the description is a text teaser
    assert len(row.content) > 2000


def test_ingest_is_idempotent(rss_env):
    """A feed re-serves its whole window every round; a second pass must add nothing."""
    fetch = FakeFetch()
    fetch.set(HN_URL, fixture('rss2_no_guid.xml'))
    mgr = make_manager(fetch)
    db.add_rss_subscription(HN_URL)

    asyncio.run(mgr.poll_once())
    asyncio.run(mgr.poll_once())

    assert len(entries(HN_URL)) == 3


def test_guid_falls_back_to_a_hash_of_title_and_date(rss_env):
    """No <guid>, no <link> — the entry still has to dedup against its next sighting."""
    body = feed_xml(
        '<item><title>Only a title</title><pubDate>Wed, 19 Aug 2026 10:00:00 +0000</pubDate>'
        '<description>body</description></item>'
    )
    fetch = FakeFetch()
    fetch.set('https://example.com/f.xml', body)
    mgr = make_manager(fetch)
    db.add_rss_subscription('https://example.com/f.xml')

    asyncio.run(mgr.poll_once())
    asyncio.run(mgr.poll_once())

    rows = entries()
    assert len(rows) == 1
    assert len(rows[0].guid) == 64  # sha256 hex — not a URL, so it cannot be confused for one


def test_an_unkeyable_entry_is_dropped_and_counted(rss_env):
    """Nothing to key on and nothing to show: no id, no link, no title, no date.
    Dropped rather than collapsed onto one hash, which would make every such entry
    in the feed the same item (x.py's "unkeyable entries are counted and dropped")."""
    fetch = FakeFetch()
    fetch.set('https://example.com/f.xml', feed_xml('<item><description>orphan</description></item>'))
    mgr = make_manager(fetch)
    db.add_rss_subscription('https://example.com/f.xml')

    asyncio.run(mgr.poll_once())

    assert entries() == []
    assert db.get_rss_feed('https://example.com/f.xml').last_error is None  # not an error, just skipped


# --- the unread window (plan §0.3) --------------------------------------------


def test_entries_older_than_the_window_arrive_already_read(rss_env):
    """Importing a feed's whole backlog must not dump months of unread onto the reader.
    Everything is archived; only the recent slice stays unread."""
    fetch = FakeFetch()
    fetch.set(HN_URL, fixture('rss2_no_guid.xml'))  # published yesterday/today
    fetch.set(BLOG_URL, fixture('content_encoded.xml'))  # published in February
    mgr = make_manager(fetch)
    db.add_rss_subscription(HN_URL)
    db.add_rss_subscription(BLOG_URL)

    asyncio.run(mgr.poll_once())

    assert all(not db.is_item_read('rss', row.id) for row in entries(HN_URL))
    assert all(db.is_item_read('rss', row.id) for row in entries(BLOG_URL))
    assert len(entries(BLOG_URL)) == 3  # archived, not skipped


def test_an_entry_without_a_date_stays_unread(rss_env):
    """A missing pubDate falls back to first_seen_at, i.e. now — so a feed that
    publishes no dates is treated as new content, never as backlog."""
    fetch = FakeFetch()
    fetch.set('https://example.com/f.xml', feed_xml('<item><title>Undated</title><link>https://e.com/1</link></item>'))
    mgr = make_manager(fetch)
    db.add_rss_subscription('https://example.com/f.xml')

    asyncio.run(mgr.poll_once())

    row = entries()[0]
    assert row.published_at is None
    assert not db.is_item_read('rss', row.id)


def test_a_future_published_at_is_archived_verbatim(rss_env):
    """Garbage future timestamps are stored as the feed declared them. Clamping is a
    read-side concern (the provider's sort key, Phase 2) — rewriting the archive
    would destroy the only evidence the feed lied."""
    fetch = FakeFetch()
    fetch.set(
        'https://example.com/f.xml',
        feed_xml(
            '<item><title>From the future</title><link>https://e.com/1</link>'
            '<pubDate>Fri, 20 Aug 2027 10:00:00 +0000</pubDate></item>'
        ),
    )
    mgr = make_manager(fetch)
    db.add_rss_subscription('https://example.com/f.xml')

    asyncio.run(mgr.poll_once())

    row = entries()[0]
    assert row.published_at == datetime(2027, 8, 20, 10, 0)
    assert not db.is_item_read('rss', row.id)


# --- conditional requests -----------------------------------------------------


def test_validators_are_stored_and_sent_back(rss_env):
    fetch = FakeFetch()
    fetch.set(HN_URL, fixture('rss2_no_guid.xml'), etag='"abc"', last_modified='Thu, 20 Aug 2026 06:20:00 GMT')
    mgr = make_manager(fetch)
    db.add_rss_subscription(HN_URL)

    asyncio.run(mgr.poll_once())
    feed = db.get_rss_feed(HN_URL)
    assert feed.etag == '"abc"' and feed.last_modified == 'Thu, 20 Aug 2026 06:20:00 GMT'
    assert fetch.calls == [(HN_URL, None, None)]

    asyncio.run(mgr.poll_once())
    assert fetch.calls[-1] == (HN_URL, '"abc"', 'Thu, 20 Aug 2026 06:20:00 GMT')


def test_a_304_round_touches_no_entries(rss_env):
    fetch = FakeFetch()
    fetch.set(HN_URL, fixture('rss2_no_guid.xml'), etag='"abc"')
    mgr = make_manager(fetch)
    db.add_rss_subscription(HN_URL)
    asyncio.run(mgr.poll_once())

    fetch.set(HN_URL, None, etag='"abc"')  # 304
    asyncio.run(
        mgr.poll_once(),
    )

    assert len(entries(HN_URL)) == 3
    feed = db.get_rss_feed(HN_URL)
    assert feed.etag == '"abc"'  # kept, not cleared
    assert feed.fetched_at == NOW  # a 304 is still a successful check


# --- the real HTTP path -------------------------------------------------------
# Everything above injects ``fetch_feed``, which is right — the risk in this source
# is XML, not sockets. But the fetcher itself then has no coverage at all, and the
# first live run found a real bug in it, so it gets a transport-level test.


def test_the_real_fetcher_treats_304_as_a_hit_not_an_error(rss_env):
    """httpx classifies 304 as a *redirect*, so ``raise_for_status()`` raises on it.
    Unhandled, that turns the single most common outcome of a polling round —
    "nothing changed" — into a recorded feed failure, and after a few rounds every
    healthy feed wears an error badge."""
    import httpx

    seen: list = []

    def handler(request):
        seen.append(request)
        return httpx.Response(304, headers={'ETag': '"abc"'})

    mgr = make_manager(None)
    mgr._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = asyncio.run(mgr._http_fetch_feed(HN_URL, etag='"abc"', last_modified='Thu, 20 Aug 2026 06:00:00 GMT'))

    assert result.status == 304 and result.body is None
    assert seen[0].headers['if-none-match'] == '"abc"'
    assert seen[0].headers['if-modified-since'] == 'Thu, 20 Aug 2026 06:00:00 GMT'


def test_the_real_fetcher_raises_on_a_server_error(rss_env):
    import httpx

    mgr = make_manager(None)
    mgr._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(mgr._http_fetch_feed(HN_URL))


# --- failure isolation --------------------------------------------------------


def test_one_failing_feed_does_not_sink_the_round(rss_env):
    fetch = FakeFetch()
    fetch.set('https://broken.example/f.xml', RuntimeError('connection reset'))
    fetch.set(HN_URL, fixture('rss2_no_guid.xml'))
    mgr = make_manager(fetch)
    db.add_rss_subscription('https://broken.example/f.xml')
    db.add_rss_subscription(HN_URL)

    asyncio.run(mgr.poll_once())

    assert len(entries(HN_URL)) == 3
    broken = db.get_rss_feed('https://broken.example/f.xml')
    assert 'connection reset' in broken.last_error and broken.error_count == 1
    assert db.get_meta('rss_last_poll_at')  # the round still completed


def test_error_count_accumulates_and_clears_on_success(rss_env):
    """The count is the signal a feed is dead rather than flaky; a success resets it.
    Nothing unsubscribes automatically — that decision stays the reader's (plan §1.1)."""
    url = 'https://flaky.example/f.xml'
    fetch = FakeFetch()
    fetch.set(url, RuntimeError('boom'))
    mgr = make_manager(fetch)
    db.add_rss_subscription(url)

    asyncio.run(mgr.poll_once())
    asyncio.run(mgr.poll_once())
    assert db.get_rss_feed(url).error_count == 2
    assert db.get_rss_subscription(url) is not None  # still subscribed

    fetch.set(url, fixture('rss2_no_guid.xml'))
    asyncio.run(mgr.poll_once())
    feed = db.get_rss_feed(url)
    assert feed.error_count == 0 and feed.last_error is None


def test_a_malformed_but_readable_feed_is_ingested_and_flagged(rss_env):
    """feedparser recovers entries from broken XML. Dropping them would lose real
    content over a stray ampersand, so they are archived *and* the error is recorded."""
    fetch = FakeFetch()
    fetch.set(
        'https://example.com/f.xml',
        b'<rss version="2.0"><channel><title>Broken</title>'
        b'<item><title>A & B</title><link>https://e.com/1</link></item>',
    )
    mgr = make_manager(fetch)
    db.add_rss_subscription('https://example.com/f.xml')

    asyncio.run(mgr.poll_once())

    assert len(entries()) == 1
    feed = db.get_rss_feed('https://example.com/f.xml')
    assert feed.last_error is not None
    assert feed.error_count == 0  # readable is not failed: the next round is not a retry


def test_a_response_that_is_not_a_feed_is_an_error(rss_env):
    """An HTML error page parses clean with zero entries — silence would look like
    'this feed publishes nothing' forever."""
    fetch = FakeFetch()
    fetch.set('https://example.com/f.xml', b'<html><body>404 not found</body></html>')
    mgr = make_manager(fetch)
    db.add_rss_subscription('https://example.com/f.xml')

    asyncio.run(mgr.poll_once())

    feed = db.get_rss_feed('https://example.com/f.xml')
    assert feed.error_count == 1 and 'not a feed' in feed.last_error


def test_an_empty_but_valid_feed_is_not_an_error(rss_env):
    fetch = FakeFetch()
    fetch.set('https://example.com/f.xml', feed_xml(''))
    mgr = make_manager(fetch)
    db.add_rss_subscription('https://example.com/f.xml')

    asyncio.run(mgr.poll_once())

    assert db.get_rss_feed('https://example.com/f.xml').last_error is None


# --- feed identity ------------------------------------------------------------


def test_the_first_fetch_backfills_the_feed_title(rss_env):
    """The reader subscribes with a URL; the feed tells us its name (X's
    _learn_user_identity precedent). Until then the row renders as the URL."""
    fetch = FakeFetch()
    fetch.set(HN_URL, fixture('rss2_no_guid.xml'))
    mgr = make_manager(fetch)
    db.add_rss_subscription(HN_URL)
    assert db.get_rss_subscription(HN_URL).name is None

    asyncio.run(mgr.poll_once())

    assert db.get_rss_feed(HN_URL).title == 'Hacker News'
    assert db.get_rss_feed(HN_URL).site_url == 'https://news.ycombinator.com/'
    assert db.get_rss_subscription(HN_URL).name == 'Hacker News'


def test_a_reader_chosen_name_survives_the_fetch(rss_env):
    fetch = FakeFetch()
    fetch.set(HN_URL, fixture('rss2_no_guid.xml'))
    mgr = make_manager(fetch)
    db.add_rss_subscription(HN_URL, name='HN front page')

    asyncio.run(mgr.poll_once())

    assert db.get_rss_subscription(HN_URL).name == 'HN front page'


def test_a_paused_feed_is_not_fetched(rss_env):
    fetch = FakeFetch()
    fetch.set(HN_URL, fixture('rss2_no_guid.xml'))
    mgr = make_manager(fetch)
    db.add_rss_subscription(HN_URL)
    db.update_rss_subscription(HN_URL, enabled=False)

    asyncio.run(mgr.poll_once())

    assert fetch.calls == []


def test_a_round_without_subscriptions_costs_nothing(rss_env):
    fetch = FakeFetch()
    mgr = make_manager(fetch)

    asyncio.run(mgr.poll_once())

    assert fetch.calls == []
    assert db.get_meta('rss_last_poll_at') is None


# --- OPML ---------------------------------------------------------------------

OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <head><title>subscriptions</title></head>
  <body>
    <outline text="Tech">
      <outline type="rss" text="Hacker News" xmlUrl="https://news.ycombinator.com/rss" htmlUrl="https://news.ycombinator.com/"/>
      <outline type="rss" text="Simon Willison" xmlUrl="https://simonwillison.net/atom/everything/"/>
    </outline>
    <outline type="rss" text="Reorx" xmlUrl="https://reorx.com/feed.xml"/>
  </body>
</opml>
"""


def test_opml_parsing_flattens_nested_groups(rss_env):
    from condenser.rss import parse_opml

    found = parse_opml(OPML)
    assert [f['url'] for f in found] == [HN_URL, ATOM_URL, BLOG_URL]
    assert found[0]['title'] == 'Hacker News'


def test_opml_parsing_rejects_broken_xml(rss_env):
    from condenser.rss import parse_opml

    with pytest.raises(ValueError):
        parse_opml('<opml><body><outline xmlUrl="https://e.com/f"></body>')


# --- endpoints ----------------------------------------------------------------


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _quiet_rss(client):
    """Neutralize the app's real manager: no network, no background round."""
    rss = client.app.state.rss
    rss._fetch_feed = FakeFetch()
    rss.kick = lambda: None
    return rss


def test_subscription_lifecycle_endpoints(rss_env):
    with _client() as client:
        _login(client)
        _quiet_rss(client)

        r = client.post('/api/sources/rss/subscriptions', json={'url': HN_URL})
        assert r.status_code == 200
        assert r.json()['url'] == HN_URL and r.json()['enabled'] is True
        assert db.get_rss_subscription(HN_URL) is not None
        assert db.get_rss_feed(HN_URL) is not None  # the fetch-state row is created with it

        # idempotent re-add, and the TG subscription list must not leak the row
        assert client.post('/api/sources/rss/subscriptions', json={'url': HN_URL}).status_code == 200
        assert len(client.get('/api/sources/rss/subscriptions').json()) == 1
        assert client.get('/api/subscriptions').json() == []

        # pause / resume — the feed URL is a query param, not a path segment
        pause = client.patch('/api/sources/rss/subscriptions', params={'url': HN_URL}, json={'enabled': False})
        assert pause.status_code == 200
        assert not bool(db.get_rss_subscription(HN_URL).enabled)
        resume = client.patch('/api/sources/rss/subscriptions', params={'url': HN_URL}, json={'enabled': True})
        assert resume.status_code == 200
        assert bool(db.get_rss_subscription(HN_URL).enabled)

        # unsubscribe keeps the archive
        db.insert_rss_entries(
            [{'feed_url': HN_URL, 'guid': 'g1', 'title': 'kept', 'first_seen_at': NOW}], read_before=None, now=NOW
        )
        assert client.delete('/api/sources/rss/subscriptions', params={'url': HN_URL}).status_code == 200
        assert db.get_rss_subscription(HN_URL) is None
        assert len(entries(HN_URL)) == 1

        # patch/delete on a missing subscription -> 404
        assert (
            client.patch('/api/sources/rss/subscriptions', params={'url': HN_URL}, json={'enabled': True}).status_code
            == 404
        )
        assert client.delete('/api/sources/rss/subscriptions', params={'url': HN_URL}).status_code == 404


def test_resubscribe_reenables_a_paused_feed(rss_env):
    with _client() as client:
        _login(client)
        _quiet_rss(client)
        client.post('/api/sources/rss/subscriptions', json={'url': HN_URL})
        client.patch('/api/sources/rss/subscriptions', params={'url': HN_URL}, json={'enabled': False})

        r = client.post('/api/sources/rss/subscriptions', json={'url': HN_URL})
        assert r.json()['enabled'] is True
        assert bool(db.get_rss_subscription(HN_URL).enabled)


def test_a_url_that_is_not_a_feed_url_is_rejected(rss_env):
    with _client() as client:
        _login(client)
        _quiet_rss(client)
        assert client.post('/api/sources/rss/subscriptions', json={'url': 'not a url'}).status_code == 422
        assert client.post('/api/sources/rss/subscriptions', json={'url': 'ftp://e.com/f.xml'}).status_code == 422


def test_opml_import_endpoint(rss_env):
    with _client() as client:
        _login(client)
        _quiet_rss(client)
        client.post('/api/sources/rss/subscriptions', json={'url': HN_URL})

        r = client.post('/api/sources/rss/opml', json={'opml': OPML})
        assert r.status_code == 200
        assert r.json() == {'added': 2, 'skipped_existing': 1, 'invalid': 0}
        assert {s.channel_id for s in db.list_rss_subscriptions()} == {HN_URL, ATOM_URL, BLOG_URL}
        # every imported feed gets its fetch-state row, same path as a manual add
        assert db.get_rss_feed(BLOG_URL) is not None


def test_opml_import_leaves_an_existing_subscription_alone(rss_env):
    """An import must not reverse the reader's decisions (2026-08-22): a paused
    feed stays paused — re-importing an OPML export to pick up additions would
    otherwise silently re-enable every noisy feed the reader turned off — and a
    name the row already carries is not overwritten by the outline's title."""
    with _client() as client:
        _login(client)
        _quiet_rss(client)
        client.post('/api/sources/rss/subscriptions', json={'url': HN_URL, 'name': 'my label'})
        client.patch('/api/sources/rss/subscriptions', params={'url': HN_URL}, json={'enabled': False})

        r = client.post('/api/sources/rss/opml', json={'opml': OPML})
        assert r.json() == {'added': 2, 'skipped_existing': 1, 'invalid': 0}
        sub = db.get_rss_subscription(HN_URL)
        assert not bool(sub.enabled)
        assert sub.name == 'my label'


def test_resubscribe_with_a_name_is_the_rename_path(rss_env):
    """PATCH carries no ``name``, so re-adding the URL with one is how a feed gets
    renamed; re-adding without one keeps the label already there."""
    with _client() as client:
        _login(client)
        _quiet_rss(client)
        client.post('/api/sources/rss/subscriptions', json={'url': HN_URL, 'name': 'old'})

        r = client.post('/api/sources/rss/subscriptions', json={'url': HN_URL, 'name': 'new'})
        assert r.json()['name'] == 'new'
        assert db.get_rss_subscription(HN_URL).name == 'new'

        r = client.post('/api/sources/rss/subscriptions', json={'url': HN_URL})
        assert r.json()['name'] == 'new'


def test_opml_import_counts_unusable_outlines(rss_env):
    with _client() as client:
        _login(client)
        _quiet_rss(client)
        opml = (
            '<opml version="1.0"><body>'
            '<outline type="rss" text="ok" xmlUrl="https://e.com/f.xml"/>'
            '<outline type="rss" text="bad" xmlUrl="javascript:alert(1)"/>'
            '<outline text="just a folder"/>'
            '</body></opml>'
        )
        r = client.post('/api/sources/rss/opml', json={'opml': opml})
        assert r.json() == {'added': 1, 'skipped_existing': 0, 'invalid': 1}


def test_opml_import_rejects_broken_xml(rss_env):
    with _client() as client:
        _login(client)
        _quiet_rss(client)
        assert client.post('/api/sources/rss/opml', json={'opml': '<opml><body>'}).status_code == 400


def test_source_disabled_rejects_writes_and_reports_status(env, monkeypatch):
    """CONDENSER_RSS_ENABLED=false means the loop never runs — a subscribe that
    reported success would archive nothing (HN's B2). It ships false, so this is
    also the default deployed state until iOS can render the cards (plan §7)."""
    monkeypatch.setenv('CONDENSER_RSS_ENABLED', 'false')
    from condenser.config import get_settings

    get_settings.cache_clear()
    with _client() as client:
        _login(client)
        assert client.post('/api/sources/rss/subscriptions', json={'url': HN_URL}).status_code == 503
        assert db.get_rss_subscription(HN_URL) is None
        assert client.post('/api/sources/rss/opml', json={'opml': OPML}).status_code == 503
        assert client.get('/api/rss/status').json()['source_enabled'] is False

        # enabling an existing row is rejected too; pausing it is still allowed
        db.add_rss_subscription(HN_URL)
        assert (
            client.patch('/api/sources/rss/subscriptions', params={'url': HN_URL}, json={'enabled': True}).status_code
            == 503
        )
        assert (
            client.patch('/api/sources/rss/subscriptions', params={'url': HN_URL}, json={'enabled': False}).status_code
            == 200
        )


def test_status_reports_the_source_state(rss_env):
    with _client() as client:
        _login(client)
        _quiet_rss(client)
        client.post('/api/sources/rss/subscriptions', json={'url': HN_URL})
        client.post('/api/sources/rss/subscriptions', json={'url': ATOM_URL})
        client.patch('/api/sources/rss/subscriptions', params={'url': ATOM_URL}, json={'enabled': False})
        db.record_rss_feed_error(HN_URL, 'timeout', NOW)
        db.insert_rss_entries(
            [{'feed_url': HN_URL, 'guid': 'g1', 'title': 'a', 'first_seen_at': NOW}], read_before=None, now=NOW
        )
        db.set_meta('rss_last_poll_at', '2026-08-20 11:50:00')

        st = client.get('/api/rss/status').json()
        assert st['source_enabled'] is True
        assert st['feeds_total'] == 2 and st['feeds_enabled'] == 1 and st['feeds_error'] == 1
        assert st['entries_total'] == 1
        assert st['last_poll_at'] == '2026-08-20 11:50:00'
