"""Behavior tests for the RSS source, Phase 2: timeline, keys, search, cleanup.

Phase 1 proved the archive fills; this covers what the reader can do with it —
the federated timeline provider, the item key surfaces it inherits for free
(read / save / hide / records / forward), full-text search, and the retention
sweep.

Entries are seeded straight into ``rss_entries`` unless the test is *about*
ingest, and ``RssManager.startup`` is neutered by the fixture: the polling loop
starts with the app, and a subscription that already exists when the client is
created would otherwise send a real HTTP request during the lifespan.

Plan: kb/plans/2026-08-20-rss-source-opml-llm-summary.md §10 Phase 2.
"""

import asyncio
import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from condenser import db, search
from condenser.app import create_app
from tests.conftest import BASE, md, seed_channel, seed_messages

FEED_A = 'https://a.example.com/feed.xml'
FEED_B = 'https://b.example.com/atom?tag=x'

# The archive's clock. Naive UTC, the storage convention.
T0 = BASE.replace(tzinfo=None)


@pytest.fixture
def rss_env(env, monkeypatch):
    """The base env with the RSS source switched on and its loop switched off.

    The source ships disabled (plan §7), and every test here needs it on. The
    manager itself is left constructible — ``kick()`` is a no-op without a loop —
    so the ingest tests can drive a round explicitly with an injected fetcher.
    """
    monkeypatch.setenv('CONDENSER_RSS_ENABLED', 'true')
    # The daily sweep fires on the first round of an app with no `cleanup_last_run_at`
    # — i.e. every test — and this module's clock is fixed in the past, so the
    # retention rule would delete the fixture out from under the assertions. Exactly
    # the trap test_x_verdict hit on 2026-08-09; the rule gets its own test below,
    # which turns it back on and drives it directly.
    monkeypatch.setenv('CONDENSER_CLEANUP_RSS_ENABLED', 'false')
    from condenser.config import get_settings

    get_settings.cache_clear()

    async def _no_loop(self):
        return None

    monkeypatch.setattr('condenser.rss.RssManager.startup', _no_loop)
    yield


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def init():
    db.init_db(os.environ['CONDENSER_DB_PATH'])


def subscribe(url, name=None, enabled=True):
    db.add_rss_subscription(url, name=name)
    if not enabled:
        db.update_rss_subscription(url, enabled=False)


def seed_entry(feed_url, guid, minutes, published=None, **over):
    """One archived entry. ``minutes`` offsets first_seen_at from T0; ``published``
    (minutes, or the string 'none') offsets the feed's own declared time."""
    first_seen = T0 + timedelta(minutes=minutes)
    if published == 'none':
        published_at = None
    else:
        published_at = first_seen if published is None else T0 + timedelta(minutes=published)
    row = {
        'feed_url': feed_url,
        'guid': guid,
        'title': f'Entry {guid}',
        'link': f'{feed_url}#{guid}',
        'author': 'alice',
        'content': f'<p>body of {guid}</p>',
        'published_at': published_at,
        'first_seen_at': first_seen,
    }
    row.update(over)
    db.insert_rss_entries([row], read_before=None, now=first_seen)
    return db.RssEntry.get(db.RssEntry.feed_url == feed_url, db.RssEntry.guid == guid)


def keys_of(items):
    return [it['key'] for it in items]


def timeline(client, **params):
    r = client.get('/api/timeline', params=params)
    assert r.status_code == 200, r.text
    return r.json()


# --- the sort timestamp (plan §2) ---------------------------------------------
#
# The archive stores what the feed declared, verbatim. Which timestamp an entry
# *sorts* by is a read-side decision, so it lives in the provider — and these
# three cases are why it is not simply `published_at`.


def test_an_entry_sorts_by_the_feeds_own_published_at(rss_env):
    init()
    subscribe(FEED_A)
    entry = seed_entry(FEED_A, 'g1', minutes=100, published=10)
    with _client() as client:
        _login(client)
        item = timeline(client, source='rss')['items'][0]
    assert item['key'] == f'rss:{entry.id}'
    # 10 minutes past T0, not 100: we met the entry late, it was published early.
    assert item['datetime'] == '2026-06-01T12:10:00Z'
    assert item['rss']['published_at'] == '2026-06-01T12:10:00Z'


def test_an_entry_without_a_published_at_sorts_by_first_sighting(rss_env):
    """A feed that declares no date still has to land somewhere sane."""
    init()
    subscribe(FEED_A)
    seed_entry(FEED_A, 'g1', minutes=100, published='none')
    with _client() as client:
        _login(client)
        item = timeline(client, source='rss')['items'][0]
    assert item['datetime'] == '2026-06-01T13:40:00Z'
    assert item['rss']['published_at'] is None


def test_a_future_published_at_is_clamped_to_first_sighting(rss_env):
    """Feeds do publish timestamps in the future, and an unclamped one would sit at
    the top of the timeline until real time caught up with it.

    Clamping is a *sort* decision: the archived value is left alone, so the pane
    can still show what the feed claimed.
    """
    init()
    subscribe(FEED_A)
    seed_entry(FEED_A, 'future', minutes=10, published=10 + 60 * 24 * 30)
    seed_entry(FEED_A, 'normal', minutes=20)
    with _client() as client:
        _login(client)
        items = timeline(client, source='rss')['items']
    # The honest entry is newest; the liar sits at its own first sighting.
    assert [it['rss']['guid'] for it in items] == ['normal', 'future']
    assert items[1]['datetime'] == '2026-06-01T12:10:00Z'
    assert items[1]['rss']['published_at'] == '2026-07-01T12:10:00Z'  # archived verbatim


def test_a_slightly_future_published_at_is_left_alone(rss_env):
    """The clamp has a tolerance: a feed published seconds before we polled it is
    legitimately a little ahead of our clock, and rewriting that would be noise."""
    init()
    subscribe(FEED_A)
    seed_entry(FEED_A, 'g1', minutes=100, published=110)  # 10 minutes ahead, inside the tolerance
    with _client() as client:
        _login(client)
        item = timeline(client, source='rss')['items'][0]
    assert item['datetime'] == '2026-06-01T13:50:00Z'


# --- the aggregate timeline (plan §0.2, §4) -----------------------------------


def test_rss_joins_the_aggregate_timeline_in_full(rss_env):
    """No admission, no verdict: an RSS entry is a timeline item like a TG message."""
    init()
    seed_channel(-100, 'Chan')
    seed_messages([md(-100, 1, 30)])
    db.add_subscription(-100)
    subscribe(FEED_A)
    e_old = seed_entry(FEED_A, 'old', minutes=10)
    e_new = seed_entry(FEED_A, 'new', minutes=50)
    with _client() as client:
        _login(client)
        items = timeline(client)['items']
    assert keys_of(items) == [f'rss:{e_new.id}', 'tg:-100:1', f'rss:{e_old.id}']


def test_paging_across_sources_neither_duplicates_nor_loses_rss(rss_env):
    init()
    seed_channel(-100, 'Chan')
    seed_messages([md(-100, 1, 15), md(-100, 2, 45)])
    db.add_subscription(-100)
    subscribe(FEED_A)
    for i in range(4):
        seed_entry(FEED_A, f'g{i}', minutes=i * 20)

    with _client() as client:
        _login(client)
        one_page = keys_of(timeline(client, limit=50)['items'])
        seen, cursor = [], None
        for _ in range(10):
            page = timeline(client, limit=2, **({'cursor': cursor} if cursor else {}))
            seen += keys_of(page['items'])
            cursor = page['next_cursor']
            if not cursor:
                break
    assert len(seen) == len(set(seen)) == 6
    # paging changes nothing but where the reader stopped
    assert seen == one_page


def test_timeline_new_reports_rss_arrivals(rss_env):
    """The poll anchor is the sort timestamp, so an entry archived after the page
    was loaded is newer than the anchor and gets reported."""
    init()
    subscribe(FEED_A)
    seed_entry(FEED_A, 'first', minutes=10)
    with _client() as client:
        _login(client)
        head = timeline(client, source='rss')['head_cursor']
        seed_entry(FEED_A, 'second', minutes=20)
        r = client.get('/api/timeline/new', params={'after': head, 'source': 'rss'})
    assert r.status_code == 200
    assert r.json()['count'] == 1
    assert r.json()['items'][0]['rss']['guid'] == 'second'


def test_timeline_days_counts_rss_by_its_sort_day(rss_env):
    """The calendar has to agree with the page, which means the *clamped* day —
    an entry whose declared date is another day sorts, and counts, by that day."""
    init()
    subscribe(FEED_A)
    seed_entry(FEED_A, 'today', minutes=10)
    seed_entry(FEED_A, 'yesterday', minutes=10, published=-60 * 20)
    with _client() as client:
        _login(client)
        days = client.get('/api/timeline/days', params={'source': 'rss'}).json()
    assert {d['date']: d['count'] for d in days} == {'2026-06-01': 1, '2026-05-31': 1}


def test_a_feed_scope_narrows_to_one_feeds_entries(rss_env):
    """With 100 feeds a per-feed view is the point of the sidebar, and the feed key
    is the URL — including its query string, which is why it is not a path segment."""
    init()
    subscribe(FEED_A)
    subscribe(FEED_B)
    a = seed_entry(FEED_A, 'a1', minutes=10)
    seed_entry(FEED_B, 'b1', minutes=20)
    with _client() as client:
        _login(client)
        items = timeline(client, source='rss', feed=FEED_A)['items']
        days = client.get('/api/timeline/days', params={'source': 'rss', 'feed': FEED_A}).json()
    assert keys_of(items) == [f'rss:{a.id}']
    assert days == [{'date': '2026-06-01', 'count': 1}]


def test_a_paused_feed_leaves_the_timeline(rss_env):
    """Pausing is the reading-list decision, so it hides the feed the way pausing a
    Telegram channel does. The archive is untouched — search still reaches it."""
    init()
    subscribe(FEED_A)
    subscribe(FEED_B)
    seed_entry(FEED_A, 'a1', minutes=10)
    b = seed_entry(FEED_B, 'b1', minutes=20)
    db.update_rss_subscription(FEED_A, enabled=False)
    with _client() as client:
        _login(client)
        items = timeline(client, source='rss')['items']
    assert keys_of(items) == [f'rss:{b.id}']


def test_with_no_rss_subscription_the_aggregate_has_no_rss(rss_env):
    init()
    subscribe(FEED_A)
    seed_entry(FEED_A, 'a1', minutes=10)
    db.delete_rss_subscription(FEED_A)
    with _client() as client:
        _login(client)
        assert timeline(client)['items'] == []


# --- the item key surfaces (plan §1.3) ----------------------------------------


def test_read_save_and_hide_work_through_the_rss_key(rss_env):
    init()
    subscribe(FEED_A)
    entry = seed_entry(FEED_A, 'g1', minutes=10)
    key = f'rss:{entry.id}'
    with _client() as client:
        _login(client)
        assert client.post('/api/read', json={'keys': [key]}).status_code == 200
        assert timeline(client, source='rss')['items'][0]['is_read'] is True
        assert timeline(client, source='rss', unread_only=True)['items'] == []

        assert client.post('/api/records', json={'key': key}).status_code == 200
        assert timeline(client, source='rss')['items'][0]['is_saved'] is True

        assert client.post('/api/hidden', json={'key': key}).status_code == 200
        assert timeline(client, source='rss')['items'] == []
        assert client.get('/api/timeline/days', params={'source': 'rss'}).json() == []
        # ...and the sidebar badge agrees, or it promises a backlog no view can show
        group = next(g for g in client.get('/api/sources').json() if g['source'] == 'rss')
        assert group['subscriptions'][0]['unread'] == 0


def test_bulk_read_scoped_to_rss_burns_only_rss(rss_env):
    init()
    seed_channel(-100, 'Chan')
    seed_messages([md(-100, 1, 10)])
    db.add_subscription(-100)
    subscribe(FEED_A)
    seed_entry(FEED_A, 'g1', minutes=10)
    with _client() as client:
        _login(client)
        assert client.post('/api/read/bulk', json={'source': 'rss'}).status_code == 200
        assert timeline(client, source='rss', unread_only=True)['items'] == []
        assert len(timeline(client, unread_only=True)['items']) == 1  # the TG message survives


def test_bulk_read_ignores_a_paused_feed(rss_env):
    """ "Mark all read" burns what the view showed, and a paused feed shows nothing
    (X's bulk_read_scope rule) — otherwise resuming it lands a silent grey backlog."""
    init()
    subscribe(FEED_A)
    subscribe(FEED_B)
    seed_entry(FEED_A, 'a1', minutes=10)
    seed_entry(FEED_B, 'b1', minutes=20)
    db.update_rss_subscription(FEED_A, enabled=False)
    with _client() as client:
        _login(client)
        client.post('/api/read/bulk', json={'source': 'rss'})
        db.update_rss_subscription(FEED_A, enabled=True)
        items = timeline(client, source='rss', unread_only=True)['items']
    assert [it['rss']['guid'] for it in items] == ['a1']


def test_sources_lists_the_rss_group_with_per_feed_unread(rss_env):
    init()
    subscribe(FEED_A, name='Feed A')
    subscribe(FEED_B)
    seed_entry(FEED_A, 'a1', minutes=10)
    seed_entry(FEED_A, 'a2', minutes=20)
    seed_entry(FEED_B, 'b1', minutes=30)
    with _client() as client:
        _login(client)
        groups = client.get('/api/sources').json()
    rss = next(g for g in groups if g['source'] == 'rss')
    rows = {s['channel_id']: s for s in rss['subscriptions']}
    assert rows[FEED_A]['name'] == 'Feed A'
    assert rows[FEED_A]['unread'] == 2 and rows[FEED_A]['aggregate_unread'] == 2
    assert rows[FEED_B]['unread'] == 1


def test_a_saved_rss_record_replays_without_the_entry_row(rss_env):
    """A record is a snapshot, so it survives the retention sweep deleting its source
    row — including the sort timestamp, which is computed rather than stored."""
    init()
    subscribe(FEED_A)
    entry = seed_entry(FEED_A, 'g1', minutes=100, published=10, summary='摘要在此')
    key = f'rss:{entry.id}'
    with _client() as client:
        _login(client)
        assert client.post('/api/records', json={'key': key}).status_code == 200
        db.RssEntry.delete().execute()
        records = client.get('/api/records').json()
    assert len(records) == 1
    rec = records[0]
    assert rec['key'] == key and rec['is_saved'] is True
    assert rec['datetime'] == '2026-06-01T12:10:00Z'
    assert rec['rss']['title'] == 'Entry g1'
    assert rec['rss']['summary'] == '摘要在此'


def test_forward_renders_an_rss_entry_as_one_title_link(rss_env):
    """RSS has no second destination the way HN has its discussion page, so the
    rendered message is one line and Telegram's own card carries the rest."""
    init()
    subscribe(FEED_A)
    entry = seed_entry(FEED_A, 'g1', minutes=10, title='标题 & 副标题')
    from condenser.forward import render
    from condenser.items import parse_key

    body = render(parse_key(f'rss:{entry.id}'))
    assert body == f'<b><a href="{FEED_A}#g1">标题 &amp; 副标题</a></b>'
    assert render(parse_key(f'rss:{entry.id}'), comment='看这个') == '看这个\n\n' + body


# --- search (plan §8) ---------------------------------------------------------


def test_an_ingested_entry_is_searchable_by_title_and_body(rss_env):
    """Indexing hangs off ingest, so a round leaves the archive searchable."""
    from condenser.rss import FetchResult, RssManager
    from condenser.config import get_settings

    init()
    subscribe(FEED_A)

    async def fetch(url, etag=None, last_modified=None):
        body = (
            '<?xml version="1.0"?><rss version="2.0"><channel><title>A</title>'
            '<link>https://a.example.com/</link><item>'
            '<title>Rust 的所有权模型</title><link>https://a.example.com/p1</link>'
            '<guid>p1</guid><description><![CDATA[<p>borrow checker 讲解</p>]]></description>'
            '</item></channel></rss>'
        ).encode()
        return FetchResult(status=200, body=body, etag=None, last_modified=None)

    mgr = RssManager(get_settings(), fetch_feed=fetch)
    mgr._now = lambda: T0
    asyncio.run(mgr.poll_once())

    with _client() as client:
        _login(client)
        hits = client.get('/api/search', params={'q': '所有权'}).json()
        assert hits['total'] == 1
        assert hits['items'][0]['rss']['title'] == 'Rust 的所有权模型'
        # the body is indexed too, HTML stripped
        assert client.get('/api/search', params={'q': 'borrow checker'}).json()['total'] == 1


def test_search_indexes_the_summary_and_scopes_to_a_feed(rss_env):
    """The summary is what the card shows, so it is part of what the card can be
    found by. Rebuild is the path an existing archive takes into the index."""
    init()
    subscribe(FEED_A)
    subscribe(FEED_B)
    seed_entry(FEED_A, 'a1', minutes=10, title='Untranslatable', content=None, summary='中文摘要说的是量子计算')
    seed_entry(FEED_B, 'b1', minutes=20, title='量子计算 elsewhere')
    assert search.rebuild()['rss'] == 2

    with _client() as client:
        _login(client)
        assert client.get('/api/search', params={'q': '量子计算'}).json()['total'] == 2
        scoped = client.get('/api/search', params={'q': '量子计算', 'source': 'rss', 'feed': FEED_A}).json()
        assert scoped['total'] == 1 and scoped['items'][0]['rss']['guid'] == 'a1'


def test_search_reaches_a_paused_feeds_archive(rss_env):
    """Search reads the archive, not the reading list (the paused-channel rule)."""
    init()
    subscribe(FEED_A)
    seed_entry(FEED_A, 'a1', minutes=10, title='findable')
    search.rebuild()
    db.update_rss_subscription(FEED_A, enabled=False)
    with _client() as client:
        _login(client)
        assert client.get('/api/search', params={'q': 'findable'}).json()['total'] == 1


# --- retention (plan §8) ------------------------------------------------------


def test_retention_deletes_old_untouched_entries_and_keeps_engaged_ones(rss_env, monkeypatch):
    """The rule reads backwards until said out loud: an **unread** old entry is
    deleted, a **read** one is kept forever — X's semantics, and for the same
    reason (the backlog nobody will scroll back to is what costs disk)."""
    from condenser.cleanup import RssRetentionRule
    from condenser.config import get_settings

    monkeypatch.setenv('CONDENSER_CLEANUP_RSS_ENABLED', 'true')
    get_settings.cache_clear()
    assert RssRetentionRule().enabled(get_settings()) is True

    init()
    subscribe(FEED_A)
    stale = seed_entry(FEED_A, 'stale', minutes=10)
    read = seed_entry(FEED_A, 'read', minutes=10)
    saved = seed_entry(FEED_A, 'saved', minutes=10)
    hidden = seed_entry(FEED_A, 'hidden', minutes=10)
    fresh = seed_entry(FEED_A, 'fresh', minutes=10)
    search.rebuild()

    from condenser.items import parse_key

    db.mark_read([parse_key(f'rss:{read.id}')])
    db.add_saved_item('rss', saved.id, 0, {'id': saved.id})
    db.hide_item(parse_key(f'rss:{hidden.id}'))
    # `fresh` is inside the window; everything else is 60 days behind the cutoff.
    db.RssEntry.update(first_seen_at=T0 + timedelta(days=60)).where(db.RssEntry.id == fresh.id).execute()

    counts = RssRetentionRule().run(T0 + timedelta(days=61), get_settings()).counts
    assert counts['entries'] == 1
    surviving = {e.guid for e in db.RssEntry.select()}
    assert surviving == {'read', 'saved', 'hidden', 'fresh'}
    # and the deleted entry takes its search document with it
    assert search.count() == 4
    assert db.RssEntry.get_or_none(db.RssEntry.id == stale.id) is None
