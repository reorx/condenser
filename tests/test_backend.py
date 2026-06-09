"""Behavior tests for the condenser backend (spec §7 scenarios). Telegram mocked."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from telememo import db as tdb
from telememo.types import SignInResult

from condenser import db, filters
from condenser.app import create_app
from tests.conftest import md, seed_channel, seed_messages


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
        r = client.post('/api/subscriptions/1/filters', json={'pattern': 'AD'})
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
        fid = client.get('/api/subscriptions/1/filters').json()[0]['id']
        assert client.delete(f'/api/filters/{fid}').status_code == 200
        ids2 = [it['id'] for it in client.get('/api/timeline').json()['items']]
        assert 11 in ids2


def test_filter_is_case_insensitive_substring(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        seed_messages([md(1, 10, 1, text='广告ad促销')])
        db.add_subscription(1)
        client.post('/api/subscriptions/1/filters', json={'pattern': 'AD'})
        assert client.get('/api/timeline').json()['items'] == []


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
        client.post('/api/subscriptions/5/filters', json={'pattern': 'AD'})

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


def test_realtime_ingest_filtered_and_new_poll(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'C')
        db.add_subscription(1)
        client.post('/api/subscriptions/1/filters', json={'pattern': 'AD'})

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
