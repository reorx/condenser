"""Behavior tests for the RSS list/detail split (plan 2026-08-23).

A feed entry's ``content`` is somebody else's whole article — 13.9KB on average
in production and 7.1MB at the tail — and until now every timeline page shipped
one per item. The split: the **list** carries a plain-text ``content_excerpt``,
the **article** lives behind ``GET /api/rss/entries/{id}``.

What these tests pin is the part that is easy to get wrong later: the list must
not carry the body *at all* (an accidental ``SELECT e.*`` would put it back
silently, and nothing else would fail), the archive-side readers — search, the
summariser, the saved snapshot — must still see the whole thing, and a saved
record must keep replaying without its source row.

Plan: kb/plans/2026-08-23-rss-list-excerpt-detail-endpoint.md
"""

import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from condenser import db, search
from condenser.app import create_app
from condenser.text import ELLIPSIS, EXCERPT_CHARS
from tests.conftest import BASE

FEED_A = 'https://a.example.com/feed.xml'

T0 = BASE.replace(tzinfo=None)

# Long enough to be cut, and with a marker *past* the cut so a test can tell
# "the excerpt stops here" from "the archive stops here".
LONG_HTML = '<p>' + ('段落一句话。' * 120) + '</p><script>var tracker = 1;</script><p>tailmarker 最后一段</p>'


@pytest.fixture
def rss_env(env, monkeypatch):
    """The base env with the RSS source on and its polling loop off.

    Same shape as ``test_rss_timeline.rss_env``, including the fixed-clock/cleanup
    trap: this module seeds entries in the past, and the startup retention round
    would delete them out from under the assertions.
    """
    monkeypatch.setenv('CONDENSER_RSS_ENABLED', 'true')
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


def subscribe(url=FEED_A):
    db.add_rss_subscription(url)


def seed_entry(guid='g1', minutes=10, feed_url=FEED_A, **over):
    first_seen = T0 + timedelta(minutes=minutes)
    row = {
        'feed_url': feed_url,
        'guid': guid,
        'title': f'Entry {guid}',
        'link': f'{feed_url}#{guid}',
        'author': 'alice',
        'content': LONG_HTML,
        'published_at': first_seen,
        'first_seen_at': first_seen,
    }
    row.update(over)
    db.insert_rss_entries([row], read_before=None, now=first_seen)
    return db.RssEntry.get(db.RssEntry.feed_url == feed_url, db.RssEntry.guid == guid)


def timeline_payload(client, **params):
    r = client.get('/api/timeline', params={'source': 'rss', **params})
    assert r.status_code == 200, r.text
    return r.json()['items'][0]['rss']


# --- the list payload ---------------------------------------------------------


def test_the_list_payload_carries_an_excerpt_and_not_the_article(rss_env):
    """The whole point: a timeline page never ships an article body."""
    init()
    subscribe()
    seed_entry()
    with _client() as client:
        _login(client)
        payload = timeline_payload(client)
    assert 'content' not in payload
    excerpt = payload['content_excerpt']
    assert excerpt.startswith('段落一句话。')
    assert len(excerpt) == EXCERPT_CHARS + len(ELLIPSIS)
    assert payload['content_truncated'] is True
    # markup gone, script contents gone, and nothing from past the cut
    assert '<' not in excerpt and 'tracker' not in excerpt and 'tailmarker' not in excerpt


def test_a_short_body_arrives_whole_and_is_not_marked_truncated(rss_env):
    """``content_truncated`` is what the web card's "more" hangs off, so a body
    that already fits must not claim there is more of it."""
    init()
    subscribe()
    seed_entry(content='<p>hello <b>world</b></p><script>alert(1)</script>')
    with _client() as client:
        _login(client)
        payload = timeline_payload(client)
    assert payload['content_excerpt'] == 'hello world'
    assert payload['content_truncated'] is False


def test_an_entry_with_no_body_has_no_excerpt(rss_env):
    """A link-only feed item. Null, not '' — the client's "is there a body" test."""
    init()
    subscribe()
    seed_entry(content=None)
    with _client() as client:
        _login(client)
        payload = timeline_payload(client)
    assert payload['content_excerpt'] is None
    assert payload['content_truncated'] is False


def test_the_summary_still_rides_in_the_list_payload(rss_env):
    """The excerpt is *beside* the summary, not instead of it: the card shows the
    article's own opening and marks the machine's paraphrase separately."""
    init()
    subscribe()
    seed_entry(summary='两三句中文摘要。')
    with _client() as client:
        _login(client)
        payload = timeline_payload(client)
    assert payload['summary'] == '两三句中文摘要。'
    assert payload['content_excerpt'].startswith('段落一句话。')


# --- the detail endpoint ------------------------------------------------------


def test_the_detail_endpoint_returns_the_whole_article_in_an_envelope(rss_env):
    """Same envelope the list speaks, plus the body — so a client renders it with
    the code it already has."""
    init()
    subscribe()
    entry = seed_entry()
    with _client() as client:
        _login(client)
        r = client.get(f'/api/rss/entries/{entry.id}')
    assert r.status_code == 200, r.text
    item = r.json()
    assert item['source'] == 'rss' and item['key'] == f'rss:{entry.id}'
    assert item['datetime'] == '2026-06-01T12:10:00Z'
    assert item['is_read'] is False and item['is_saved'] is False
    assert item['rss']['content'] == LONG_HTML
    assert item['rss']['content_excerpt'].startswith('段落一句话。')


def test_the_detail_endpoint_reports_the_current_read_and_saved_state(rss_env):
    """The flags are live state, not a property of the entry — the same rule the
    timeline row follows."""
    init()
    subscribe()
    entry = seed_entry()
    key = f'rss:{entry.id}'
    with _client() as client:
        _login(client)
        client.post('/api/read', json={'keys': [key]})
        client.post('/api/records', json={'key': key})
        item = client.get(f'/api/rss/entries/{entry.id}').json()
    assert item['is_read'] is True and item['is_saved'] is True


def test_the_detail_endpoint_404s_on_an_unknown_entry(rss_env):
    init()
    subscribe()
    with _client() as client:
        _login(client)
        assert client.get('/api/rss/entries/99999').status_code == 404


def test_the_detail_endpoint_needs_auth(rss_env):
    """It serves article text; it sits behind the same gate as everything else."""
    init()
    subscribe()
    entry = seed_entry()
    with _client() as client:
        assert client.get(f'/api/rss/entries/{entry.id}').status_code == 401


def test_the_detail_endpoint_reaches_a_paused_feeds_entry(rss_env):
    """Pausing is a reading-list decision; an entry already saved or found in
    search is still openable (``rows_by_id``'s rule)."""
    init()
    subscribe()
    entry = seed_entry()
    db.update_rss_subscription(FEED_A, enabled=False)
    with _client() as client:
        _login(client)
        r = client.get(f'/api/rss/entries/{entry.id}')
    assert r.status_code == 200 and r.json()['rss']['content'] == LONG_HTML


# --- saved records (plan §5, option (a): the snapshot keeps the article) -------


def test_a_saved_record_keeps_the_article_after_its_row_is_gone(rss_env):
    """Why the snapshot stores the full text rather than the excerpt: a record
    replays without the source tables, and that has to include "open the article"."""
    init()
    subscribe()
    entry = seed_entry()
    with _client() as client:
        _login(client)
        assert client.post('/api/records', json={'key': f'rss:{entry.id}'}).status_code == 200
        db.RssEntry.delete().execute()

        records = client.get('/api/records').json()
        detail = client.get(f'/api/rss/entries/{entry.id}')
    # the list of records is a list: excerpt only, like every other list
    assert len(records) == 1
    assert 'content' not in records[0]['rss']
    assert records[0]['rss']['content_excerpt'].startswith('段落一句话。')
    # ...and the article is still reachable, out of the snapshot
    assert detail.status_code == 200
    assert detail.json()['rss']['content'] == LONG_HTML
    assert detail.json()['is_saved'] is True


def test_a_snapshot_written_before_the_excerpt_existed_still_renders_one(rss_env):
    """Records saved by the old code carry ``content`` and no excerpt. Deriving it
    on replay costs nothing (the snapshot is already in hand) and is the difference
    between a card with a body and a card with a blank."""
    init()
    subscribe()
    entry = seed_entry()
    db.add_saved_item(
        'rss',
        entry.id,
        0,
        {
            'id': entry.id,
            'feed_url': FEED_A,
            'title': 'legacy record',
            'content': LONG_HTML,
            'first_seen_at': '2026-06-01T12:10:00Z',
            'sort_at': '2026-06-01T12:10:00Z',
        },
    )
    with _client() as client:
        _login(client)
        rec = client.get('/api/records').json()[0]
    assert rec['rss']['content_excerpt'].startswith('段落一句话。')
    assert rec['rss']['content_truncated'] is True
    assert 'content' not in rec['rss']


# --- the archive-side readers -------------------------------------------------


def test_search_still_indexes_the_whole_body_not_the_excerpt(rss_env):
    """Search reads the archive row, not the envelope. A word past the excerpt's
    cut has to stay findable, or the split silently shrinks what search covers."""
    init()
    subscribe()
    seed_entry()
    assert search.rebuild()['rss'] == 1
    with _client() as client:
        _login(client)
        hits = client.get('/api/search', params={'q': 'tailmarker'}).json()
    assert hits['total'] == 1


def test_the_summariser_still_reads_the_whole_body(rss_env):
    """The summary is of the article, not of its first 500 characters."""
    init()
    subscribe()
    seed_entry()
    rows = db.rss_entries_needing_summary(limit=10, max_attempts=3, min_content_chars=10)
    assert len(rows) == 1
    assert rows[0]['content'] == LONG_HTML


# --- the column (schema v16) --------------------------------------------------


def test_ingest_writes_the_excerpt_beside_the_body(rss_env):
    """Materialized on the write side (``is_filtered``'s rule), so the list query
    never touches the body column at all — which is where the 7.1MB row is paid for."""
    init()
    subscribe()
    entry = seed_entry()
    row = db.RssEntry.get_by_id(entry.id)
    assert row.content_excerpt.startswith('段落一句话。')
    assert row.content_excerpt.endswith(ELLIPSIS)


def test_a_pre_v16_archive_gains_the_column_and_gets_backfilled(rss_env):
    """The upgrade path: shape-based ADD COLUMN plus a marker-keyed backfill, since
    a NULL excerpt is not "the pre-feature behavior" here — it is a blank card."""
    path = os.environ['CONDENSER_DB_PATH']
    init()
    subscribe()
    entry = seed_entry()

    db.set_meta('schema_version', '15')
    db.set_meta(db.RSS_EXCERPT_META_KEY, '')
    db.tdb.db.execute_sql('ALTER TABLE rss_entries DROP COLUMN content_excerpt')  # pre-v16 shape
    db.close_db()

    db.init_db(path)

    assert db.get_meta('schema_version') == str(db.SCHEMA_VERSION)
    row = db.RssEntry.get_by_id(entry.id)
    assert row.content_excerpt.startswith('段落一句话。')
    assert db.get_meta(db.RSS_EXCERPT_META_KEY) == str(db.RSS_EXCERPT_VERSION)


def test_the_backfill_reruns_when_the_excerpt_rule_changes(rss_env, monkeypatch):
    """The marker holds a version, not a flag: the excerpt is derived data, and a
    length or stripping change that left every stored excerpt behind would be
    invisible (``TOKENIZER_VERSION``'s arrangement, one table smaller)."""
    path = os.environ['CONDENSER_DB_PATH']
    init()
    subscribe()
    entry = seed_entry()
    db.RssEntry.update(content_excerpt='stale').where(db.RssEntry.id == entry.id).execute()
    db.close_db()

    monkeypatch.setattr(db, 'RSS_EXCERPT_VERSION', db.RSS_EXCERPT_VERSION + 1)
    db.init_db(path)

    assert db.RssEntry.get_by_id(entry.id).content_excerpt.startswith('段落一句话。')


def test_a_second_startup_does_not_rewrite_the_excerpts(rss_env):
    """Idempotence, stated as the thing that would hurt: the backfill reads every
    body in the archive, and doing that on each boot is a cost nobody asked for."""
    path = os.environ['CONDENSER_DB_PATH']
    init()
    subscribe()
    entry = seed_entry()
    # A hand-edited excerpt survives a restart => the backfill did not run again.
    db.RssEntry.update(content_excerpt='untouched').where(db.RssEntry.id == entry.id).execute()
    db.close_db()

    db.init_db(path)

    assert db.RssEntry.get_by_id(entry.id).content_excerpt == 'untouched'
