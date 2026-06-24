"""Behavior tests for the condenser backend (spec §7 scenarios). Telegram mocked."""

import os
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from telememo import db as tdb
from telememo.types import SignInResult

from condenser import db, filters
from condenser.app import create_app
from tests.conftest import md, seed_channel, seed_messages


# --- data layer: WAL journaling (robustness) --------------------------------


def test_init_db_enables_wal(env):
    """init_db must leave the file in WAL mode so concurrent reads/writes don't lock."""
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    mode = tdb.db.execute_sql('PRAGMA journal_mode').fetchone()[0]
    assert mode.lower() == 'wal'


def _client(env_unused=None):
    return TestClient(create_app())


def _login(client):
    r = client.post('/api/auth/login', json={'password': 'pw'})
    assert r.status_code == 200


# --- auth gate (C4 / D8) ----------------------------------------------------


def test_auth_required_and_login(env):
    with _client() as client:
        assert client.get('/api/subscriptions').status_code == 401
        assert client.post('/api/auth/login', json={'password': 'nope'}).status_code == 401
        _login(client)
        assert client.get('/api/subscriptions').status_code == 200


# --- timeline: filter materialization + album + read (§7) -------------------


def test_timeline_excludes_filtered_and_groups_album(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages(
            [
                md(1, 10, 1, text='hello world'),
                md(1, 11, 2, text='buy AD now'),
                md(1, 12, 3, text=None, grouped_id=99, has_media=True, media_type='photo'),
                md(1, 13, 3, text='album caption', grouped_id=99, has_media=True, media_type='photo'),
            ]
        )
        db.add_subscription(1)

        # exclude keyword "AD" (case-insensitive) -> message 11 filtered out
        r = client.post('/api/filters', json={'pattern': 'AD', 'channel_id': 1})
        assert r.status_code == 200

        items = client.get('/api/timeline').json()['items']
        ids = [it['id'] for it in items]
        assert 11 not in ids  # filtered
        assert 12 in ids  # album collapsed to its primary (min) id
        album = next(it for it in items if it['id'] == 12)
        assert album['is_album'] is True
        assert len(album['media_items']) == 2
        assert album['text'] == 'album caption'

        # delete the rule -> message 11 reappears (is_filtered recomputed to 0)
        fid = client.get('/api/filters').json()[0]['id']
        assert client.delete(f'/api/filters/{fid}').status_code == 200
        ids2 = [it['id'] for it in client.get('/api/timeline').json()['items']]
        assert 11 in ids2


def test_timeline_includes_webpage_preview(env):
    from telememo.types import WebPagePreview

    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages(
            [
                md(1, 10, 1, text='plain message'),
                md(
                    1,
                    11,
                    2,
                    text='see https://example.com',
                    media_type='webpage',
                    has_media=True,
                    webpage=WebPagePreview(
                        url='https://example.com',
                        title='Example',
                        description='A description',
                        site_name='Example Site',
                        has_photo=True,
                    ),
                ),
            ]
        )
        db.add_subscription(1)

        items = client.get('/api/timeline').json()['items']
        wp = next(it for it in items if it['id'] == 11)['webpage']
        assert wp['url'] == 'https://example.com'
        assert wp['title'] == 'Example'
        assert wp['site_name'] == 'Example Site'
        assert wp['has_photo'] is True
        # Messages without a link preview carry an explicit null.
        assert next(it for it in items if it['id'] == 10)['webpage'] is None


def test_filter_is_case_insensitive_substring(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1, text='广告ad促销')])
        db.add_subscription(1)
        client.post('/api/filters', json={'pattern': 'AD', 'channel_id': 1})
        assert client.get('/api/timeline').json()['items'] == []


def test_global_filter_create_list_and_preview(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_channel(2, 'News', 'news')
        seed_messages(
            [
                md(1, 10, 1, text='free pizza'),
                md(1, 11, 2, text='clean code'),
                md(2, 20, 3, text='PIZZA recipe'),
                md(2, 21, 4, text='politics'),
            ]
        )
        db.add_subscription(1)
        db.add_subscription(2)

        # Preview a global rule before creating — pattern hits across enabled channels.
        r = client.post('/api/filters/preview', json={'pattern': 'pizza'})
        body = r.json()
        assert body['matched'] == 2
        assert body['scanned'] == 4  # both channels combined
        assert {s['channel_id'] for s in body['samples']} == {1, 2}

        # Empty pattern short-circuits to a zero result without scanning.
        empty = client.post('/api/filters/preview', json={'pattern': '   '}).json()
        assert empty == {'scanned': 0, 'matched': 0, 'samples': []}

        # Create a global rule (channel_id omitted) and confirm both channels recompute.
        created = client.post('/api/filters', json={'pattern': 'pizza'}).json()
        assert created['channel_id'] is None
        ids = [it['id'] for it in client.get('/api/timeline').json()['items']]
        assert 10 not in ids and 20 not in ids  # both filtered by the global rule
        assert 11 in ids and 21 in ids

        # /api/filters returns the global rule plus channel rules with their titles.
        client.post('/api/filters', json={'pattern': 'politics', 'channel_id': 2})
        rows = client.get('/api/filters').json()
        assert len(rows) == 2
        global_row = next(r for r in rows if r['channel_id'] is None)
        ch_row = next(r for r in rows if r['channel_id'] == 2)
        assert global_row['channel_title'] is None
        assert ch_row['channel_title'] == 'News'

        # Deleting the global rule recomputes every enabled channel back to unfiltered.
        client.delete(f'/api/filters/{created["id"]}')
        ids2 = [it['id'] for it in client.get('/api/timeline').json()['items']]
        assert 10 in ids2 and 20 in ids2  # pizza messages reappear


def test_preview_scoped_to_channel(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C1')
        seed_channel(2, 'C2')
        seed_messages(
            [
                md(1, 10, 1, text='AD here'),
                md(1, 11, 2, text='no match'),
                md(2, 20, 3, text='also AD'),
            ]
        )
        db.add_subscription(1)
        db.add_subscription(2)

        # Channel-scoped preview only scans that channel.
        scoped = client.post('/api/filters/preview', json={'pattern': 'ad', 'channel_id': 1}).json()
        assert scoped['scanned'] == 2 and scoped['matched'] == 1
        assert scoped['samples'][0]['channel_id'] == 1


def test_timeline_date_and_channel_filter(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C1')
        seed_channel(2, 'C2')
        # 3 messages for channel 1 on 2026-06-01, one on a later day
        seed_messages(
            [
                md(1, 10, 1),
                md(1, 11, 2),
                md(1, 12, 3),
                md(1, 13, 60 * 24 * 2),  # two days later
                md(2, 20, 5),
            ]
        )
        db.add_subscription(1)
        db.add_subscription(2)

        items = client.get('/api/timeline?channel_id=1&date=2026-06-01').json()['items']
        assert sorted(it['id'] for it in items) == [10, 11, 12]
        # order is date desc
        assert [it['id'] for it in items] == [12, 11, 10]


def test_timeline_cursor_pagination(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10 + i, i) for i in range(5)])
        db.add_subscription(1)

        page1 = client.get('/api/timeline?limit=2').json()
        assert [it['id'] for it in page1['items']] == [14, 13]
        assert page1['next_cursor']

        page2 = client.get(f'/api/timeline?limit=2&cursor={page1["next_cursor"]}').json()
        assert [it['id'] for it in page2['items']] == [12, 11]

        page3 = client.get(f'/api/timeline?limit=2&cursor={page2["next_cursor"]}').json()
        assert [it['id'] for it in page3['items']] == [10]
        assert page3['next_cursor'] is None


def test_read_marks_and_unread_count(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1), md(1, 11, 2)])
        db.add_subscription(1)

        subs = client.get('/api/subscriptions').json()
        assert subs[0]['unread'] == 2

        r = client.post('/api/read', json={'items': [{'channel_id': 1, 'message_id': 11}]})
        assert r.status_code == 200

        items = client.get('/api/timeline').json()['items']
        read_flags = {it['id']: it['is_read'] for it in items}
        assert read_flags == {11: True, 10: False}
        assert client.get('/api/subscriptions').json()[0]['unread'] == 1


def test_read_album_clears_unread_count(env):
    """Marking an album read via its primary id must clear the whole unit's unread count.

    Albums collapse to one display unit keyed by their primary (min) id, but unread
    counts / the unread filter operate per raw row. Marking only the primary leaves the
    sibling rows unread, so the album's grouped_id keeps getting counted (badge stuck).
    """
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages(
            [
                md(1, 10, 1, text='standalone'),
                md(1, 12, 3, text=None, grouped_id=99, has_media=True, media_type='photo'),
                md(1, 13, 3, text='album caption', grouped_id=99, has_media=True, media_type='photo'),
            ]
        )
        db.add_subscription(1)

        # album (1 unit) + standalone (1 unit) = 2 unread
        assert client.get('/api/subscriptions').json()[0]['unread'] == 2

        # mark the album read via its primary (display) id only
        r = client.post('/api/read', json={'items': [{'channel_id': 1, 'message_id': 12}]})
        assert r.status_code == 200

        # the whole album is gone from the count; only the standalone remains
        assert client.get('/api/subscriptions').json()[0]['unread'] == 1

        # and it reports read in both the full and unread-only timelines
        items = client.get('/api/timeline').json()['items']
        assert {it['id']: it['is_read'] for it in items} == {12: True, 10: False}
        unread_ids = [it['id'] for it in client.get('/api/timeline?unread_only=true').json()['items']]
        assert unread_ids == [10]


def test_read_bulk_clears_album_unread_count(env):
    """Bulk mark-read selects every raw row, so an album clears too (regression lock)."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages(
            [
                md(1, 12, 3, text=None, grouped_id=99, has_media=True, media_type='photo'),
                md(1, 13, 3, text='album caption', grouped_id=99, has_media=True, media_type='photo'),
            ]
        )
        db.add_subscription(1)
        assert client.get('/api/subscriptions').json()[0]['unread'] == 1

        assert client.post('/api/read/bulk', json={'channel_id': 1}).status_code == 200
        assert client.get('/api/subscriptions').json()[0]['unread'] == 0


def test_timeline_days(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1), md(1, 11, 2), md(1, 12, 60 * 24 * 3)])
        db.add_subscription(1)
        days = client.get('/api/timeline/days?channel_id=1').json()
        by_day = {d['date']: d['count'] for d in days}
        assert by_day['2026-06-01'] == 2
        assert by_day['2026-06-04'] == 1


def test_timeline_head_cursor_polls_only_newer(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1), md(1, 11, 2)])
        db.add_subscription(1)

        page = client.get('/api/timeline').json()
        head = page['head_cursor']
        assert head  # anchors the newest unit on the page

        # nothing is newer than the page head yet
        assert client.get(f'/api/timeline/new?after={head}').json()['count'] == 0

        # a newer message arrives -> the poll finds exactly it, not the older ones
        seed_messages([md(1, 12, 3)])
        filters.recompute_messages(1, [12])
        new = client.get(f'/api/timeline/new?after={head}').json()
        assert new['count'] == 1
        assert [it['id'] for it in new['items']] == [12]


# --- records: source-decoupled snapshot (§7) --------------------------------


def test_record_is_source_decoupled(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1, text='precious post')])
        db.add_subscription(1)

        assert client.post('/api/records', json={'channel_id': 1, 'message_id': 10}).status_code == 200

        # the source message is now flagged saved in the timeline
        item = client.get('/api/timeline').json()['items'][0]
        assert item['is_saved'] is True

        # wipe the telememo cache row -> record still renders from raw_data
        tdb.db.execute_sql('DELETE FROM messages WHERE channel_id = 1 AND id = 10')
        records = client.get('/api/records').json()
        assert len(records) == 1
        assert records[0]['id'] == 10
        assert records[0]['text'] == 'precious post'

        # unsave removes it
        assert client.delete('/api/records/1/10').status_code == 200
        assert client.get('/api/records').json() == []


# --- TG step login (C2) -----------------------------------------------------


def _fake_authorized_service():
    fake = MagicMock()
    type(fake).is_authorized = property(lambda self: True)
    type(fake).is_listening = property(lambda self: False)
    fake.subscribe = AsyncMock()
    fake.update_subscription = AsyncMock()
    fake.disconnect = AsyncMock()
    return fake


def test_subscribe_creates_rows_and_starts_backfill(env):
    from telememo.types import ChannelInfo

    with _client() as client:
        _login(client)
        fake = _fake_authorized_service()
        fake.resolve_channel = AsyncMock(return_value=ChannelInfo(id=5, title='TechNews', username='technews'))

        async def empty_backfill(channel, **kw):
            return
            yield  # make it an async generator

        fake.backfill = empty_backfill
        client.app.state.tg.service = fake

        r = client.post('/api/subscriptions', json={'handle': '@technews'})
        assert r.status_code == 200
        assert r.json()['channel_id'] == 5

        assert db.get_subscription(5) is not None
        from telememo import db as tdb

        assert tdb.get_channel(5).title == 'TechNews'
        fake.resolve_channel.assert_awaited_once_with('@technews')


def test_backfill_persists_filters_and_marks_done(env):
    import asyncio

    from telememo.types import DisplayMessage

    from tests.conftest import BASE

    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        db.add_subscription(5)
        client.post('/api/filters', json={'pattern': 'AD', 'channel_id': 5})

        async def fake_backfill(channel, since_days=None, since_date=None, persist=True):
            # the real service persists during iteration; emulate that here
            seed_messages([md(5, 60, 1, text='clean signal'), md(5, 61, 2, text='deal AD')])
            yield DisplayMessage(id=60, channel_id=5, date=BASE, raw_message_ids=[60])
            yield DisplayMessage(id=61, channel_id=5, date=BASE, raw_message_ids=[61])

        fake = _fake_authorized_service()
        fake.backfill = fake_backfill
        tg = client.app.state.tg
        tg.service = fake

        asyncio.run(tg._backfill_channel(5))

        assert db.get_subscription(5).backfill_done is True
        ids = [it['id'] for it in client.get('/api/timeline').json()['items']]
        assert 60 in ids and 61 not in ids  # backfilled + filtered materialized


def test_refresh_channel_pulls_recent_window_and_reports_new(env):
    """POST /api/tg/refresh/{id} re-pulls the recent window (sync) and reports new-message count."""
    from telememo.types import DisplayMessage

    from tests.conftest import BASE

    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        db.add_subscription(5)
        seed_messages([md(5, 60, 1, text='old post')])  # already have this one

        async def fake_backfill(channel, since_days=None, since_date=None, persist=True):
            # the real service persists during iteration; emulate two fresh posts arriving
            seed_messages([md(5, 61, 2, text='fresh one'), md(5, 62, 3, text='fresh two')])
            yield DisplayMessage(id=61, channel_id=5, date=BASE, raw_message_ids=[61])
            yield DisplayMessage(id=62, channel_id=5, date=BASE, raw_message_ids=[62])

        fake = _fake_authorized_service()
        fake.backfill = fake_backfill
        client.app.state.tg.service = fake

        r = client.post('/api/tg/refresh/5')
        assert r.status_code == 200
        assert r.json()['new'] == 2  # ids 61, 62 are above the prior max id (60)

        ids = [it['id'] for it in client.get('/api/timeline').json()['items']]
        assert 60 in ids and 61 in ids and 62 in ids


def test_refresh_all_queues_only_enabled_channels(env):
    """POST /api/tg/refresh fans out background backfill for every enabled channel."""
    with _client() as client:
        _login(client)
        seed_channel(5, 'A')
        seed_channel(6, 'B')
        seed_channel(7, 'C')
        db.add_subscription(5)
        db.add_subscription(6)
        db.add_subscription(7)
        db.set_subscription_enabled(7, False)  # disabled -> excluded from the fan-out

        async def empty_backfill(channel, **kw):
            return
            yield  # make it an async generator

        fake = _fake_authorized_service()
        fake.backfill = empty_backfill
        client.app.state.tg.service = fake

        r = client.post('/api/tg/refresh')
        assert r.status_code == 200
        assert r.json() == {'status': 'started', 'channels': 2}


def test_fetch_older_pages_back_into_history(env):
    """POST /api/tg/fetch-older/{id} anchors on the oldest stored id and pulls older messages."""
    from telememo.types import DisplayMessage

    from tests.conftest import BASE

    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        db.add_subscription(5)
        seed_messages([md(5, 60, 1, text='current oldest'), md(5, 61, 2, text='newer')])

        async def fake_backfill(
            channel, since_days=None, since_date=None, persist=True, offset_id=0, max_messages=None
        ):
            assert offset_id == 60  # anchors on the current oldest stored id
            assert max_messages == 200
            seed_messages([md(5, 59, -1, text='older two'), md(5, 58, -2, text='older one')])
            yield DisplayMessage(id=59, channel_id=5, date=BASE, raw_message_ids=[59])
            yield DisplayMessage(id=58, channel_id=5, date=BASE, raw_message_ids=[58])

        fake = _fake_authorized_service()
        fake.backfill = fake_backfill
        client.app.state.tg.service = fake

        r = client.post('/api/tg/fetch-older/5')
        assert r.status_code == 200
        assert r.json()['fetched'] == 2

        ids = sorted(it['id'] for it in client.get('/api/timeline').json()['items'])
        assert ids == [58, 59, 60, 61]


def test_reset_channel_wipes_messages_and_read_then_resyncs(env):
    """POST /api/tg/reset/{id} deletes cached messages + read markers, keeps saved records, re-syncs."""
    from telememo.types import DisplayMessage

    from tests.conftest import BASE

    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        db.add_subscription(5)
        db.set_backfill_done(5, True)
        seed_messages([md(5, 60, 1, text='old one'), md(5, 61, 2, text='old two')])
        # save message 60 (a user asset) and mark 61 read
        assert client.post('/api/records', json={'channel_id': 5, 'message_id': 60}).status_code == 200
        assert client.post('/api/read', json={'items': [{'channel_id': 5, 'message_id': 61}]}).status_code == 200

        async def fake_backfill(
            channel, since_days=None, since_date=None, persist=True, offset_id=0, max_messages=None
        ):
            seed_messages([md(5, 70, 5, text='fresh after reset')])
            yield DisplayMessage(id=70, channel_id=5, date=BASE, raw_message_ids=[70])

        fake = _fake_authorized_service()
        fake.backfill = fake_backfill
        client.app.state.tg.service = fake

        r = client.post('/api/tg/reset/5')
        assert r.status_code == 200
        assert r.json() == {'status': 'ok', 'deleted': 2, 'fetched': 1}

        # the old cache is gone; only the freshly re-synced message remains, and it reads as unread
        items = client.get('/api/timeline').json()['items']
        assert [it['id'] for it in items] == [70]
        assert items[0]['is_read'] is False

        # the saved record survived the wipe (source-decoupled) and subscription stays backfilled
        assert [rec['id'] for rec in client.get('/api/records').json()] == [60]
        assert db.get_subscription(5).backfill_done is True


def test_refresh_requires_telegram_authorized(env):
    """Refresh endpoints 503 when telegram is not connected."""
    with _client() as client:
        _login(client)
        assert client.post('/api/tg/refresh').status_code == 503
        assert client.post('/api/tg/refresh/5').status_code == 503
        assert client.post('/api/tg/fetch-older/5').status_code == 503
        assert client.post('/api/tg/reset/5').status_code == 503


def test_realtime_ingest_filtered_and_new_poll(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        db.add_subscription(1)
        client.post('/api/filters', json={'pattern': 'AD', 'channel_id': 1})

        # simulate two realtime messages already persisted by the service layer
        seed_messages([md(1, 50, 10, text='clean news'), md(1, 51, 11, text='promo AD')])
        # the on_message hook recomputes is_filtered for the freshly-ingested ids
        filters.recompute_messages(1, [50, 51])

        ids = [it['id'] for it in client.get('/api/timeline').json()['items']]
        assert 50 in ids and 51 not in ids

        # /timeline/new (poll) sees the unfiltered new message, not the filtered one
        from condenser.timeline import encode_cursor

        old_cursor = encode_cursor('2020-01-01 00:00:00+00:00', 0)
        new = client.get(f'/api/timeline/new?after={old_cursor}').json()
        assert new['count'] == 1
        assert [it['id'] for it in new['items']] == [50]


def test_media_proxy_streams(env):
    with _client() as client:
        _login(client)

        async def chunks():
            yield b'\x89PNG'
            yield b'data'

        fake = MagicMock()
        type(fake).is_authorized = property(lambda self: True)
        fake.get_media = AsyncMock(return_value=(chunks(), 'image/png'))
        fake.disconnect = AsyncMock()
        client.app.state.tg.service = fake

        r = client.get('/api/media/1/50?thumb=1')
        assert r.status_code == 200
        assert r.headers['content-type'] == 'image/png'
        assert r.content == b'\x89PNGdata'
        fake.get_media.assert_awaited_once_with(1, 50, thumb=True)


def test_channel_avatar_proxy(env):
    with _client() as client:
        _login(client)

        fake = MagicMock()
        type(fake).is_authorized = property(lambda self: True)
        fake.get_channel_photo = AsyncMock(return_value=(b'\x89PNGavatar', 'image/jpeg'))
        fake.disconnect = AsyncMock()
        client.app.state.tg.service = fake

        r = client.get('/api/channels/5/avatar')
        assert r.status_code == 200
        assert r.headers['content-type'] == 'image/jpeg'
        assert r.content == b'\x89PNGavatar'
        fake.get_channel_photo.assert_awaited_once_with(5)

        # a channel with no photo -> 404 (frontend falls back to a letter avatar)
        fake.get_channel_photo = AsyncMock(return_value=None)
        assert client.get('/api/channels/5/avatar').status_code == 404


def test_media_and_avatar_resolve_via_username(env):
    """Regression: after a restart Telethon's StringSession has no entity cache, so a bare
    channel id can't be resolved. When the channel has a username, both proxies must pass
    ``@username`` (which resolves reliably) instead of the int."""
    with _client() as client:
        _login(client)
        seed_channel(7, 'Tech', 'techchan')

        async def chunks():
            yield b'img'

        fake = MagicMock()
        type(fake).is_authorized = property(lambda self: True)
        fake.get_media = AsyncMock(return_value=(chunks(), 'image/png'))
        fake.get_channel_photo = AsyncMock(return_value=(b'avatar', 'image/jpeg'))
        fake.disconnect = AsyncMock()
        client.app.state.tg.service = fake

        assert client.get('/api/media/7/50?thumb=1').status_code == 200
        fake.get_media.assert_awaited_once_with('@techchan', 50, thumb=True)

        assert client.get('/api/channels/7/avatar').status_code == 200
        fake.get_channel_photo.assert_awaited_once_with('@techchan')


def _fake_dialog(cid, title, username=None, *, is_channel=True, is_group=False, unread=0, date=None):
    """Build a Telethon-like Dialog stub (entity has no ``full`` -> ChannelInfo stays null).

    ``date`` is the dialog's last-message date (used for recency sort); ``unread`` is the
    Telegram-side unread count.
    """
    from types import SimpleNamespace

    entity = SimpleNamespace(id=cid, title=title, username=username, date=None)
    return SimpleNamespace(is_channel=is_channel, is_group=is_group, entity=entity, date=date, unread_count=unread)


def _service_with_dialogs(get_dialogs, counter=None):
    """Authorized fake service whose client.iter_dialogs yields ``get_dialogs()`` each call."""
    fake = _fake_authorized_service()
    fake.client = MagicMock()

    async def iter_dialogs(**kw):
        if counter is not None:
            counter['n'] += 1
        for d in get_dialogs():
            yield d

    fake.client.iter_dialogs = iter_dialogs
    return fake


def test_list_joined_channels_filters_to_broadcast_and_marks_subscribed(env):
    with _client() as client:
        _login(client)
        dialogs = [
            _fake_dialog(5, 'TechNews', 'technews'),  # broadcast channel
            _fake_dialog(6, 'ChatGroup', 'grp', is_group=True),  # supergroup -> excluded
            _fake_dialog(7, 'Papers', 'papers'),  # broadcast channel, already subscribed
        ]
        client.app.state.tg.service = _service_with_dialogs(lambda: dialogs)
        db.add_subscription(7)

        out = client.get('/api/tg/dialogs').json()
        assert [c['channel_id'] for c in out] == [5, 7]  # group 6 excluded, order preserved
        by_id = {c['channel_id']: c for c in out}
        assert by_id[5]['title'] == 'TechNews' and by_id[5]['subscribed'] is False
        assert by_id[7]['subscribed'] is True


def test_list_joined_channels_sorted_by_recent_with_unread(env):
    from datetime import datetime, timezone

    with _client() as client:
        _login(client)
        dialogs = [
            _fake_dialog(1, 'Old', unread=0, date=datetime(2026, 6, 1, tzinfo=timezone.utc)),
            _fake_dialog(2, 'Newest', unread=5, date=datetime(2026, 6, 10, tzinfo=timezone.utc)),
            _fake_dialog(3, 'Mid', unread=2, date=datetime(2026, 6, 5, tzinfo=timezone.utc)),
        ]
        client.app.state.tg.service = _service_with_dialogs(lambda: dialogs)

        out = client.get('/api/tg/dialogs').json()
        assert [c['channel_id'] for c in out] == [2, 3, 1]  # newest-activity first
        assert {c['channel_id']: c['unread'] for c in out} == {2: 5, 3: 2, 1: 0}


def test_list_joined_channels_caches_by_time_and_refresh_bypasses(env):
    with _client() as client:
        _login(client)
        calls = {'n': 0}
        state = {'dialogs': [_fake_dialog(5, 'A')]}
        client.app.state.tg.service = _service_with_dialogs(lambda: state['dialogs'], counter=calls)

        assert [c['channel_id'] for c in client.get('/api/tg/dialogs').json()] == [5]
        assert calls['n'] == 1

        # the account's channel list changes, but the TTL cache hides it
        state['dialogs'] = [_fake_dialog(5, 'A'), _fake_dialog(9, 'B')]
        assert [c['channel_id'] for c in client.get('/api/tg/dialogs').json()] == [5]
        assert calls['n'] == 1  # served from cache

        # ?refresh=1 bypasses the cache and re-fetches
        assert [c['channel_id'] for c in client.get('/api/tg/dialogs?refresh=1').json()] == [5, 9]
        assert calls['n'] == 2


def test_batch_subscribe_refreshes_once_and_reports_failures(env):
    from telememo.types import ChannelInfo

    with _client() as client:
        _login(client)
        fake = _fake_authorized_service()

        def resolve(handle):
            if handle == '404':
                raise ValueError('no such channel')
            cid = int(handle)
            return ChannelInfo(id=cid, title=f'C{cid}', username=f'c{cid}')

        fake.resolve_channel = AsyncMock(side_effect=resolve)

        async def empty_backfill(channel, **kw):
            return
            yield  # make it an async generator

        fake.backfill = empty_backfill
        client.app.state.tg.service = fake

        r = client.post('/api/subscriptions/batch', json={'channel_ids': [5, 404, 7]})
        assert r.status_code == 200
        body = r.json()
        assert [c['channel_id'] for c in body['added']] == [5, 7]
        assert [f['channel_id'] for f in body['failed']] == [404]

        # both good channels persisted; the bad one did not
        assert db.get_subscription(5) is not None and db.get_subscription(7) is not None
        assert db.get_subscription(404) is None
        # realtime listener re-synced exactly once for the whole batch
        fake.subscribe.assert_awaited_once()


def test_batch_subscribe_reuses_dialog_cache_without_resolving(env):
    """Channels picked from the browse list reuse the already-fetched info (no re-resolve)."""
    with _client() as client:
        _login(client)
        dialogs = [_fake_dialog(5, 'TechNews', 'technews'), _fake_dialog(8, 'Papers', 'papers')]
        fake = _service_with_dialogs(lambda: dialogs)
        fake.resolve_channel = AsyncMock(side_effect=AssertionError('cached channels must not be re-resolved'))

        async def empty_backfill(channel, **kw):
            return
            yield  # make it an async generator

        fake.backfill = empty_backfill
        client.app.state.tg.service = fake

        # browsing populates the dialogs cache
        assert client.get('/api/tg/dialogs').status_code == 200

        r = client.post('/api/subscriptions/batch', json={'channel_ids': [5, 8]})
        assert r.status_code == 200
        assert [c['channel_id'] for c in r.json()['added']] == [5, 8]
        assert db.get_subscription(5) is not None and db.get_subscription(8) is not None
        fake.resolve_channel.assert_not_awaited()  # served from cache
        fake.subscribe.assert_awaited_once()  # realtime listener re-synced once


def test_tg_status_includes_phone(env):
    with _client() as client:
        _login(client)
        # no session stored yet -> no phone field
        assert 'phone' not in client.get('/api/tg/status').json()

        db.save_tg_session('+15551234', b'enc', authorized=True)
        body = client.get('/api/tg/status').json()
        assert body['phone'] == '+15551234'


def test_tg_step_login_with_2fa(env):
    with _client() as client:
        _login(client)

        fake = MagicMock()
        fake._authorized = False
        type(fake).is_authorized = property(lambda self: self._authorized)
        fake.connect = AsyncMock()
        fake.disconnect = AsyncMock()
        fake.send_code = AsyncMock(return_value='HASH')

        async def sign_in_code(phone, code, phone_code_hash):
            return SignInResult(status='2fa_required')

        async def sign_in_2fa(password):
            fake._authorized = True
            return SignInResult(status='ok', session='SESS')

        fake.sign_in_code = AsyncMock(side_effect=sign_in_code)
        fake.sign_in_2fa = AsyncMock(side_effect=sign_in_2fa)
        fake.subscribe = AsyncMock()
        fake.is_listening = False

        client.app.state.tg._new_service = lambda session=None: fake

        assert client.get('/api/tg/status').json()['status'] == 'unauthorized'

        r = client.post('/api/tg/send-code', json={'phone': '+100'})
        assert r.json()['status'] == 'awaiting_code'

        r = client.post('/api/tg/sign-in', json={'code': '12345'})
        assert r.json()['status'] == 'awaiting_2fa'

        r = client.post('/api/tg/sign-in-2fa', json={'password': 'pw2'})
        assert r.json()['status'] == 'authorized'

        # session persisted + encrypted
        row = db.get_tg_session()
        assert row is not None and row.authorized and row.session_enc
