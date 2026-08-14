"""Phase 2 multi-source behavior tests (plan 2026-07-19-multi-source-hn.md).

Covers: item keys, the unified read_items/saved_items storage (+ v4 migration),
the federated timeline merge with composite cursors, and the /api/sources listing.
Telegram is mocked (DB-seeded); HN stories are seeded directly into hn_stories.
"""

import base64
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from condenser import db
from condenser.app import create_app
from condenser.items import hn_key, parse_key, tg_key
from tests.conftest import BASE, md, seed_channel, seed_messages


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def seed_hn(sid, minutes, score=120, day=None, is_dead=False, **over):
    """Seed one hn_stories row; first_seen_at = BASE + minutes (naive UTC).

    The default score clears the admission floor (``sources/hn.DEFAULT_MIN_SCORE``,
    plan 2026-08-14 phase A) — these cases are about merging, paging and keys, so
    their stories should be ordinary front-page material rather than the kind the
    floor exists to reject. ``peak_rank`` defaults to NULL, which always passes.
    """
    first_seen = (BASE + timedelta(minutes=minutes)).replace(tzinfo=None)
    fields = dict(
        id=sid,
        title=f'S{sid}',
        url=f'https://ex.com/{sid}',
        domain='ex.com',
        author='alice',
        text=None,
        type='story',
        submitted_at=first_seen,
        first_seen_at=first_seen,
        day=day or str(first_seen.date()),
        score=score,
        comments_count=1,
        score_updated_at=first_seen,
        is_dead=is_dead,
    )
    fields.update(over)
    db.insert_hn_story(**fields)


def subscribe_hn(config=None):
    return db.add_hn_subscription('front', name='Hacker News Front Page', config=config)


def keys_of(items):
    return [it['key'] for it in items]


# --- item keys (2.1) ---------------------------------------------------------


def test_item_key_roundtrip():
    k = parse_key('tg:1234567:89')
    assert (k.source, k.ref1, k.ref2) == ('telegram', 1234567, 89)
    assert k.key == 'tg:1234567:89'
    assert tg_key(1234567, 89) == 'tg:1234567:89'

    k = parse_key('hn:44001234')
    assert (k.source, k.ref1, k.ref2) == ('hn', 44001234, 0)
    assert k.key == 'hn:44001234'
    assert hn_key(44001234) == 'hn:44001234'

    for bad in ('rss:1', 'tg:1', 'hn:1:2', 'tg:x:1', 'hn:', 'tg:1:2:3', ''):
        with pytest.raises(ValueError):
            parse_key(bad)


# --- v4 migration: read_messages/telegram_records -> unified tables (2.2) ----


def test_migration_v4_moves_read_and_saved_rows(env):
    """A v3 DB (read_messages/telegram_records) is migrated: rows copied into the
    unified triple-keyed tables, old tables renamed *_legacy (kept one version)."""
    path = os.environ['CONDENSER_DB_PATH']
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE read_messages (channel_id INTEGER NOT NULL, message_id INTEGER NOT NULL, '
        'read_at DATETIME NOT NULL, PRIMARY KEY (channel_id, message_id))'
    )
    conn.execute("INSERT INTO read_messages VALUES (5, 60, '2026-06-01 10:00:00')")
    conn.execute("INSERT INTO read_messages VALUES (5, 61, '2026-06-01 10:01:00')")
    conn.execute(
        'CREATE TABLE telegram_records (channel_id INTEGER NOT NULL, message_id INTEGER NOT NULL, '
        'raw_data TEXT NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (channel_id, message_id))'
    )
    conn.execute("INSERT INTO telegram_records VALUES (5, 60, '{\"messages\": []}', '2026-06-01 11:00:00')")
    conn.commit()
    conn.close()

    db.init_db(path)

    reads = {(r.source, r.ref1, r.ref2) for r in db.ReadItem.select()}
    assert reads == {('telegram', 5, 60), ('telegram', 5, 61)}
    saved = list(db.SavedItem.select())
    assert [(s.source, s.ref1, s.ref2) for s in saved] == [('telegram', 5, 60)]
    assert saved[0].raw_data == '{"messages": []}'

    tables = {r[0] for r in db.tdb.db.execute_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert 'read_messages' not in tables and 'telegram_records' not in tables
    assert 'read_messages_legacy' in tables and 'telegram_records_legacy' in tables

    # idempotent: a second init must not duplicate or crash
    db.init_db(path)
    assert db.ReadItem.select().count() == 2


# --- envelope shape (2.1) ----------------------------------------------------


def test_timeline_items_are_envelopes(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1, text='hello')])
        db.add_subscription(1)

        items = client.get('/api/timeline').json()['items']
        assert len(items) == 1
        it = items[0]
        assert it['source'] == 'telegram'
        assert it['key'] == 'tg:1:10'
        assert it['datetime'].startswith('2026-06-01T12:01')
        assert it['is_read'] is False and it['is_saved'] is False
        tg = it['telegram']
        assert tg['id'] == 10 and tg['channel_id'] == 1 and tg['text'] == 'hello'
        # flags are hoisted to the envelope, not duplicated in the payload
        assert 'is_read' not in tg and 'is_saved' not in tg
        assert 'hn' not in it


def test_timeline_hn_envelope_payload(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(101, 5, score=142, text=None)

        items = client.get('/api/timeline').json()['items']
        assert len(items) == 1
        it = items[0]
        assert it['source'] == 'hn'
        assert it['key'] == 'hn:101'
        assert it['is_read'] is False and it['is_saved'] is False
        hn = it['hn']
        assert hn['id'] == 101 and hn['title'] == 'S101'
        assert hn['url'] == 'https://ex.com/101' and hn['domain'] == 'ex.com'
        assert hn['score'] == 142 and hn['comments_count'] == 1
        assert hn['day_rank'] == 1
        assert hn['first_seen_at'].startswith('2026-06-01T12:05')
        assert it['datetime'] == hn['first_seen_at']
        assert 'telegram' not in it


def _preview_json(**over):
    fields = {
        'url': 'https://ex.com/101',
        'title': 'Og title',
        'description': 'Og desc',
        'image': 'https://ex.com/img.png',
        'site_name': 'Ex',
        'source': 'fetched',
        'tg_image_message_id': None,
        'error': None,
    }
    fields.update(over)
    return json.dumps(fields)


def test_timeline_hn_envelope_includes_preview(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(101, 5, preview=_preview_json())
        seed_hn(102, 6)

        by_key = {it['key']: it for it in client.get('/api/timeline').json()['items']}
        p = by_key['hn:101']['hn']['preview']
        assert p['title'] == 'Og title' and p['image'] == 'https://ex.com/img.png'
        assert by_key['hn:102']['hn']['preview'] is None


def test_hn_record_snapshot_carries_preview_and_tolerates_legacy(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(101, 5, preview=_preview_json())
        assert client.post('/api/records', json={'key': 'hn:101'}).status_code == 200

        # wipe the source table: the snapshot alone must still render the preview
        db.HNStory.delete().execute()
        recs = client.get('/api/records').json()
        assert recs[0]['hn']['preview']['title'] == 'Og title'

        # a pre-feature snapshot (raw_data without the preview key) renders with preview=None
        db.add_saved_item(
            'hn',
            999,
            0,
            {
                'id': 999,
                'title': 'old snapshot',
                'url': 'https://ex.com/999',
                'domain': 'ex.com',
                'author': 'alice',
                'type': 'story',
                'text': None,
                'submitted_at': None,
                'first_seen_at': '2026-06-01T10:00:00Z',
                'score': 1,
                'comments_count': 0,
                'day_rank': None,
                'peak_rank': None,
                'backfilled': False,
                'day': '2026-06-01',
            },
        )
        legacy = next(r for r in client.get('/api/records').json() if r['key'] == 'hn:999')
        assert legacy['hn']['preview'] is None


# --- read by key (2.2/2.4) ---------------------------------------------------


def test_read_by_keys_marks_both_sources(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1), md(1, 11, 2)])
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 3)

        r = client.post('/api/read', json={'keys': ['tg:1:11', 'hn:101']})
        assert r.status_code == 200

        flags = {it['key']: it['is_read'] for it in client.get('/api/timeline').json()['items']}
        assert flags == {'hn:101': True, 'tg:1:11': True, 'tg:1:10': False}

        unread = keys_of(client.get('/api/timeline?unread_only=true').json()['items'])
        assert unread == ['tg:1:10']


def test_read_rejects_malformed_key(env):
    with _client() as client:
        _login(client)
        assert client.post('/api/read', json={'keys': ['bogus:1']}).status_code == 422


def test_read_album_expansion_still_works_by_key(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages(
            [
                md(1, 12, 3, text=None, grouped_id=99, has_media=True, media_type='photo'),
                md(1, 13, 3, text='album', grouped_id=99, has_media=True, media_type='photo'),
            ]
        )
        db.add_subscription(1)
        assert client.get('/api/subscriptions').json()[0]['unread'] == 1
        client.post('/api/read', json={'keys': ['tg:1:12']})
        assert client.get('/api/subscriptions').json()[0]['unread'] == 0


# --- federated merge + composite cursor (2.3) --------------------------------


def test_timeline_merges_sources_by_datetime(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1), md(1, 11, 3), md(1, 12, 5)])
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 2)
        seed_hn(102, 4)

        items = client.get('/api/timeline').json()['items']
        assert keys_of(items) == ['tg:1:12', 'hn:102', 'tg:1:11', 'hn:101', 'tg:1:10']


def test_timeline_pagination_across_sources_no_dup_no_loss(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10 + i, i * 2) for i in range(5)])  # minutes 0,2,4,6,8
        db.add_subscription(1)
        subscribe_hn()
        for j in range(4):
            seed_hn(100 + j, j * 2 + 1)  # minutes 1,3,5,7

        seen = []
        cursor = None
        pages = 0
        while True:
            q = f'/api/timeline?limit=2{f"&cursor={cursor}" if cursor else ""}'
            page = client.get(q).json()
            seen += keys_of(page['items'])
            pages += 1
            if not page['next_cursor']:
                break
            cursor = page['next_cursor']
            assert pages < 20
        assert seen == [
            'tg:1:14',
            'hn:103',
            'tg:1:13',
            'hn:102',
            'tg:1:12',
            'hn:101',
            'tg:1:11',
            'hn:100',
            'tg:1:10',
        ]
        assert len(seen) == len(set(seen))


def test_timeline_single_source_exhausts_then_other_continues(env):
    """One source running dry mid-pagination must not stall the other."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 8), md(1, 11, 9)])  # newest items are TG
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 1)
        seed_hn(102, 2)

        page1 = client.get('/api/timeline?limit=2').json()
        assert keys_of(page1['items']) == ['tg:1:11', 'tg:1:10']
        page2 = client.get(f'/api/timeline?limit=2&cursor={page1["next_cursor"]}').json()
        assert keys_of(page2['items']) == ['hn:102', 'hn:101']
        assert page2['next_cursor'] is None


def test_timeline_source_param_and_channel_scope(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 2)

        assert keys_of(client.get('/api/timeline?source=hn').json()['items']) == ['hn:101']
        assert keys_of(client.get('/api/timeline?source=telegram').json()['items']) == ['tg:1:10']
        # channel_id implies source=telegram
        assert keys_of(client.get('/api/timeline?channel_id=1').json()['items']) == ['tg:1:10']
        assert client.get('/api/timeline?source=rss').status_code == 422


def test_timeline_without_hn_subscription_shows_no_hn(env):
    """HN stories are invisible until an enabled subscription exists (and again after pause)."""
    with _client() as client:
        _login(client)
        seed_hn(101, 1)
        assert client.get('/api/timeline').json()['items'] == []

        subscribe_hn()
        assert keys_of(client.get('/api/timeline').json()['items']) == ['hn:101']

        db.update_hn_subscription('front', enabled=False)
        assert client.get('/api/timeline').json()['items'] == []


def test_hn_display_mode_top_n(env):
    """Reading is compressed query-time: only each day's top-N stories are visible."""
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'top10'})
        # 25 stories on one day, score = id so higher id wins
        for i in range(25):
            seed_hn(100 + i, i, score=100 + i)

        items = client.get('/api/timeline?limit=50').json()['items']
        assert len(items) == 10
        # the visible ones are the highest-scored, ordered by first_seen desc
        visible_ids = {it['hn']['id'] for it in items}
        assert visible_ids == {100 + i for i in range(15, 25)}

        db.update_hn_subscription('front', config={'display_mode': 'half'})
        assert len(client.get('/api/timeline?limit=50').json()['items']) == 13  # ceil(25/2)

        db.update_hn_subscription('front', config={'display_mode': 'all'})
        assert len(client.get('/api/timeline?limit=50').json()['items']) == 25

        db.update_hn_subscription('front', config={'display_mode': 'top20'})
        assert len(client.get('/api/timeline?limit=50').json()['items']) == 20


def test_hn_dead_stories_excluded(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(101, 1)
        seed_hn(102, 2, is_dead=True)
        assert keys_of(client.get('/api/timeline').json()['items']) == ['hn:101']


def test_timeline_date_filter_cross_source(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1), md(1, 11, 60 * 24 * 2)])  # day 1 + day 3
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 5)
        seed_hn(102, 60 * 24 * 2 + 5)

        keys = keys_of(client.get('/api/timeline?date=2026-06-01').json()['items'])
        assert set(keys) == {'tg:1:10', 'hn:101'}


def test_timeline_days_merged_across_sources(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1), md(1, 11, 2)])
        db.add_subscription(1)
        subscribe_hn(config={'display_mode': 'top10'})
        seed_hn(101, 5)
        seed_hn(102, 60 * 24 * 2)  # two days later
        # a hidden story (rank > N) must not count
        for i in range(11):
            seed_hn(200 + i, 10 + i, score=50 + i)

        days = {d['date']: d['count'] for d in client.get('/api/timeline/days').json()}
        # 2026-06-01: 2 TG units + top10 of that day's 12 stories
        assert days['2026-06-01'] == 2 + 10
        assert days['2026-06-03'] == 1


def test_timeline_new_composite_head_poll(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 2)

        head = client.get('/api/timeline').json()['head_cursor']
        assert head
        assert client.get(f'/api/timeline/new?after={head}').json()['count'] == 0

        # one new item per source arrives
        seed_messages([md(1, 11, 10)])
        from condenser import filters

        filters.recompute_messages(1, [11])
        seed_hn(102, 11)

        new = client.get(f'/api/timeline/new?after={head}').json()
        assert new['count'] == 2
        assert keys_of(new['items']) == ['hn:102', 'tg:1:11']


def test_end_cursor_resumes_after_fetch_older(env):
    """The composite end_cursor still anchors the last unit when history is exhausted."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1), md(1, 11, 2)])
        db.add_subscription(1)

        page = client.get('/api/timeline?limit=5').json()
        assert page['next_cursor'] is None
        assert page['end_cursor']

        seed_messages([md(1, 9, -5)])  # fetch-older imports older rows
        older = client.get(f'/api/timeline?limit=5&cursor={page["end_cursor"]}').json()
        assert keys_of(older['items']) == ['tg:1:9']


def test_invalid_cursor_returns_422(env):
    """Legacy (pre-Phase-2) and garbage cursors must 422, not 500 (F2)."""
    with _client() as client:
        _login(client)
        legacy = base64.urlsafe_b64encode('2026-06-01 12:00:00+00:00\x1f10'.encode()).decode()
        assert client.get(f'/api/timeline?cursor={legacy}').status_code == 422
        assert client.get('/api/timeline?cursor=garbage').status_code == 422
        # valid base64+JSON but not a source map
        not_a_map = base64.urlsafe_b64encode(b'[1,2]').decode()
        assert client.get(f'/api/timeline?cursor={not_a_map}').status_code == 422
        assert client.get(f'/api/timeline/new?after={legacy}').status_code == 422
        assert client.get('/api/timeline/new?after=garbage').status_code == 422


def test_merge_album_dense_page_keeps_global_order(env):
    """A TG page that drains below `limit` units with has_more must not let an
    older HN unit jump ahead of unfetched newer TG units (F3)."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        # 23 album rows (12+11) fill fetch_cap = limit(3) + buffer(20) exactly,
        # leaving a newer-than-HN single message unfetched on page 1.
        msgs = [md(1, 40 + i, 20, grouped_id=72, has_media=True, media_type='photo') for i in range(12)]
        msgs += [md(1, 20 + i, 10, grouped_id=71, has_media=True, media_type='photo') for i in range(11)]
        msgs += [md(1, 10, 5)]
        seed_messages(msgs)
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 1)

        page1 = client.get('/api/timeline?limit=3').json()
        assert keys_of(page1['items']) == ['tg:1:40', 'tg:1:20']  # short page, no HN leak
        assert page1['next_cursor']

        seen, dts, cursor, pages = [], [], None, 0
        while True:
            q = f'/api/timeline?limit=3{f"&cursor={cursor}" if cursor else ""}'
            page = client.get(q).json()
            seen += keys_of(page['items'])
            dts += [it['datetime'] for it in page['items']]
            pages += 1
            if not page['next_cursor']:
                break
            cursor = page['next_cursor']
            assert pages < 10
        assert seen == ['tg:1:40', 'tg:1:20', 'tg:1:10', 'hn:101']
        assert dts == sorted(dts, reverse=True) and len(set(dts)) == len(dts)


def _future_naive(minutes=5):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).replace(tzinfo=None)


def test_timeline_new_covers_source_with_empty_page(env):
    """A subscribed source with zero units on page 1 still gets a poll anchor (F4)."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        subscribe_hn()  # subscribed, but hn_stories is empty

        head = client.get('/api/timeline').json()['head_cursor']
        assert head

        fs = _future_naive()
        seed_hn(102, 0, first_seen_at=fs, day=str(fs.date()))
        new = client.get(f'/api/timeline/new?after={head}').json()
        assert new['count'] == 1
        assert keys_of(new['items']) == ['hn:102']


def test_timeline_new_covers_all_read_unread_view(env):
    """Unread view with every HN story read must still surface new stories (F4)."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 2)
        client.post('/api/read', json={'keys': ['hn:101']})

        head = client.get('/api/timeline?unread_only=true').json()['head_cursor']
        assert head

        fs = _future_naive()
        seed_hn(102, 0, first_seen_at=fs, day=str(fs.date()))
        new = client.get(f'/api/timeline/new?after={head}&unread_only=true').json()
        assert new['count'] == 1
        assert keys_of(new['items']) == ['hn:102']


def test_timeline_new_hn_count_not_capped_by_limit(env):
    """`count` reflects all new HN stories even when the poll asks for limit=1 (F5)."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(100, 1)

        head = client.get('/api/timeline').json()['head_cursor']
        for j in range(5):
            seed_hn(101 + j, 2 + j)

        new = client.get(f'/api/timeline/new?after={head}&limit=1').json()
        assert new['count'] == 5
        assert len(new['items']) == 1


def test_hn_half_mode_single_story_day_visible(env):
    """half = ceil(day_total / 2): a day with one story must not vanish (F6)."""
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'half'})
        seed_hn(101, 1)

        assert keys_of(client.get('/api/timeline').json()['items']) == ['hn:101']
        days = {d['date']: d['count'] for d in client.get('/api/timeline/days').json()}
        assert days == {'2026-06-01': 1}
        out = client.get('/api/sources').json()
        assert out[0]['subscriptions'][0]['unread'] == 1


# --- records by key (2.2/2.4) ------------------------------------------------


def test_record_saved_and_read_renders_is_read(env):
    """A saved item that is also read renders is_read=true (locks the C1 batch path)."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 2)

        client.post('/api/records', json={'key': 'tg:1:10'})
        client.post('/api/records', json={'key': 'hn:101'})
        client.post('/api/read', json={'keys': ['tg:1:10']})

        flags = {r['key']: r['is_read'] for r in client.get('/api/records').json()}
        assert flags == {'tg:1:10': True, 'hn:101': False}


def test_record_save_and_render_by_key_telegram(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1, text='precious')])
        db.add_subscription(1)

        assert client.post('/api/records', json={'key': 'tg:1:10'}).status_code == 200
        assert client.get('/api/timeline').json()['items'][0]['is_saved'] is True

        # snapshot renders after the source cache row is wiped
        db.tdb.db.execute_sql('DELETE FROM messages WHERE channel_id = 1 AND id = 10')
        recs = client.get('/api/records').json()
        assert len(recs) == 1
        assert recs[0]['source'] == 'telegram' and recs[0]['key'] == 'tg:1:10'
        assert recs[0]['is_saved'] is True
        assert recs[0]['telegram']['text'] == 'precious'
        assert recs[0]['telegram']['channel']['title'] == 'Tech'

        assert client.delete('/api/records/tg:1:10').status_code == 200
        assert client.get('/api/records').json() == []


def test_record_save_and_render_by_key_hn(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(101, 1, score=99)

        assert client.post('/api/records', json={'key': 'hn:101'}).status_code == 200
        assert client.get('/api/timeline').json()['items'][0]['is_saved'] is True

        # source-decoupled: renders after the hn_stories row is gone
        db.HNStory.delete().where(db.HNStory.id == 101).execute()
        recs = client.get('/api/records').json()
        assert len(recs) == 1
        assert recs[0]['source'] == 'hn' and recs[0]['key'] == 'hn:101'
        assert recs[0]['hn']['title'] == 'S101' and recs[0]['hn']['score'] == 99

        assert client.delete('/api/records/hn:101').status_code == 200
        assert client.get('/api/records').json() == []


def test_record_unknown_item_404(env):
    with _client() as client:
        _login(client)
        assert client.post('/api/records', json={'key': 'tg:1:999'}).status_code == 404
        assert client.post('/api/records', json={'key': 'hn:999'}).status_code == 404
        assert client.post('/api/records', json={'key': 'nope'}).status_code == 422


# --- GET /api/sources (2.4) --------------------------------------------------


def test_sources_lists_only_added_sources(env):
    with _client() as client:
        _login(client)
        assert client.get('/api/sources').json() == []

        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1), md(1, 11, 2)])
        db.add_subscription(1)

        out = client.get('/api/sources').json()
        assert [s['source'] for s in out] == ['telegram']
        tg_sub = out[0]['subscriptions'][0]
        assert tg_sub['channel_id'] == 1
        assert tg_sub['name'] == 'Tech'  # resolved from channels.title
        assert tg_sub['username'] == 'tech'
        assert tg_sub['enabled'] is True
        assert tg_sub['unread'] == 2

        subscribe_hn(config={'display_mode': 'top10'})
        seed_hn(101, 1)
        out = client.get('/api/sources').json()
        assert [s['source'] for s in out] == ['telegram', 'hn']
        hn_sub = out[1]['subscriptions'][0]
        assert hn_sub['channel_id'] == 'front'
        assert hn_sub['name'] == 'Hacker News Front Page'
        assert hn_sub['config'] == {'display_mode': 'top10'}
        assert hn_sub['unread'] == 1


def test_hn_unread_counts_only_visible_top_n(env):
    """HN unread must match the display filter, or the badge can never clear."""
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'top10'})
        for i in range(15):
            seed_hn(100 + i, i, score=100 + i)  # top10 = ids 105..114

        def hn_unread():
            out = client.get('/api/sources').json()
            return next(s for s in out if s['source'] == 'hn')['subscriptions'][0]['unread']

        assert hn_unread() == 10
        client.post('/api/read', json={'keys': ['hn:114', 'hn:113']})
        assert hn_unread() == 8
        # reading a hidden story changes nothing visible
        client.post('/api/read', json={'keys': ['hn:100']})
        assert hn_unread() == 8


def test_bulk_read_covers_hn(env):
    """Mark-all-read in the aggregate view clears HN unread too."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 2)

        assert client.post('/api/read/bulk', json={}).status_code == 200
        assert all(it['is_read'] for it in client.get('/api/timeline').json()['items'])


def test_bulk_read_scoped_to_one_source(env):
    """The source-scoped views' mark-all-read must not leak into other sources."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        subscribe_hn()
        seed_hn(101, 2)

        assert client.post('/api/read/bulk', json={'source': 'hn'}).status_code == 200
        by_key = {it['key']: it['is_read'] for it in client.get('/api/timeline').json()['items']}
        assert by_key['hn:101'] is True
        assert by_key['tg:1:10'] is False

        assert client.post('/api/read/bulk', json={'source': 'telegram'}).status_code == 200
        assert all(it['is_read'] for it in client.get('/api/timeline').json()['items'])


def test_bulk_read_rejects_unknown_source(env):
    with _client() as client:
        _login(client)
        assert client.post('/api/read/bulk', json={'source': 'rss'}).status_code == 422
