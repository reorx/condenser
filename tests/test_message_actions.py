"""Behavior tests for message stats (views/forwards/reactions) + forward-to-my-channel.

Plan: kb/plans/2026-07-21-tg-message-stats-forward.md. Telegram is fully mocked — the
manager talks to ``service.client.*`` directly (same layer as _enrich_channel), so the
fakes here stub ``get_messages`` / ``forward_messages`` / ``send_message``.
"""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    MessageReactions,
    ReactionCount,
    ReactionCustomEmoji,
    ReactionEmoji,
    ReactionPaid,
)

from condenser import db
from condenser.app import create_app
from tests.conftest import seed_channel

CUSTOM_DOC_ID = 5368221678337263242


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _service(**client_calls):
    """A fake authorized TelegramService whose raw ``client`` carries the given AsyncMocks."""
    fake = MagicMock()
    fake.is_authorized = True
    fake.disconnect = AsyncMock()
    fake.client = MagicMock(**client_calls)
    return fake


def _message(views=None, forwards=None, reactions=None):
    return MagicMock(views=views, forwards=forwards, reactions=reactions)


# --- GET /api/messages/{cid}/{mid}/stats ------------------------------------


def test_message_stats_returns_views_forwards_and_reactions(env):
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        msg = _message(
            views=1234,
            forwards=56,
            reactions=MessageReactions(
                results=[
                    ReactionCount(reaction=ReactionEmoji(emoticon='👍'), count=12),
                    ReactionCount(reaction=ReactionCustomEmoji(document_id=CUSTOM_DOC_ID), count=3, chosen_order=0),
                ]
            ),
        )
        get_messages = AsyncMock(return_value=msg)
        client.app.state.tg.service = _service(get_messages=get_messages)

        r = client.get('/api/messages/5/100/stats')
        assert r.status_code == 200
        assert r.json() == {
            'views': 1234,
            'forwards': 56,
            'reactions': [
                {'kind': 'emoji', 'emoji': '👍', 'document_id': None, 'count': 12, 'chosen': False},
                {'kind': 'custom', 'emoji': None, 'document_id': CUSTOM_DOC_ID, 'count': 3, 'chosen': True},
            ],
        }
        # resolved through the @username handle (StringSession entity-cache workaround)
        assert get_messages.await_args.args[0] == '@technews'
        assert get_messages.await_args.kwargs['ids'] == 100


def test_message_stats_unknown_reaction_kind_degrades_to_other(env):
    """A TL reaction type we don't model (ReactionPaid, future types) must not 500."""
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        msg = _message(
            views=None,
            forwards=None,
            reactions=MessageReactions(results=[ReactionCount(reaction=ReactionPaid(), count=7)]),
        )
        client.app.state.tg.service = _service(get_messages=AsyncMock(return_value=msg))

        body = client.get('/api/messages/5/100/stats').json()
        assert body['views'] is None and body['forwards'] is None
        assert body['reactions'] == [{'kind': 'other', 'emoji': None, 'document_id': None, 'count': 7, 'chosen': False}]


def test_message_stats_404_when_message_missing(env):
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        client.app.state.tg.service = _service(get_messages=AsyncMock(return_value=None))

        r = client.get('/api/messages/5/100/stats')
        assert r.status_code == 404
        assert r.json()['detail'] == 'message not found'


def test_message_stats_503_when_unauthorized(env):
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        client.app.state.tg.service = None

        r = client.get('/api/messages/5/100/stats')
        assert r.status_code == 503
        assert r.json()['detail'] == 'telegram not authorized'


def test_message_stats_429_on_flood_wait(env):
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        flood = FloodWaitError(request=None, capture=17)
        client.app.state.tg.service = _service(get_messages=AsyncMock(side_effect=flood))

        r = client.get('/api/messages/5/100/stats')
        assert r.status_code == 429
        assert r.headers['Retry-After'] == '17'


# --- POST /api/messages/{cid}/{mid}/forward ---------------------------------


def test_forward_empty_comment_uses_native_forward(env):
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        db.set_meta('forward_channel', '@mychannel')
        forward_messages = AsyncMock(return_value=MagicMock(id=999))
        send_message = AsyncMock()
        client.app.state.tg.service = _service(forward_messages=forward_messages, send_message=send_message)

        r = client.post('/api/messages/5/100/forward', json={})
        assert r.status_code == 200
        assert r.json() == {'status': 'ok', 'mode': 'forward', 'link': 'https://t.me/mychannel/999'}

        assert forward_messages.await_args.args[0] == '@mychannel'
        assert forward_messages.await_args.args[1] == 100
        assert forward_messages.await_args.kwargs['from_peer'] == '@technews'
        send_message.assert_not_awaited()


def test_forward_with_comment_sends_quote_message_with_link(env):
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        db.set_meta('forward_channel', '@mychannel')
        send_message = AsyncMock(return_value=MagicMock(id=1000))
        forward_messages = AsyncMock()
        client.app.state.tg.service = _service(send_message=send_message, forward_messages=forward_messages)

        r = client.post('/api/messages/5/100/forward', json={'comment': '值得一读'})
        assert r.status_code == 200
        assert r.json() == {'status': 'ok', 'mode': 'quote', 'link': 'https://t.me/mychannel/1000'}

        assert send_message.await_args.args[0] == '@mychannel'
        assert send_message.await_args.args[1] == '值得一读\n\nhttps://t.me/technews/100'
        forward_messages.assert_not_awaited()


def test_forward_uses_private_link_when_channel_has_no_username(env):
    with _client() as client:
        _login(client)
        seed_channel(6, 'Private', None)
        db.set_meta('forward_channel', '@mychannel')
        send_message = AsyncMock(return_value=MagicMock(id=1001))
        client.app.state.tg.service = _service(send_message=send_message, forward_messages=AsyncMock())

        assert client.post('/api/messages/6/42/forward', json={'comment': 'hey'}).status_code == 200
        assert send_message.await_args.args[1] == 'hey\n\nhttps://t.me/c/6/42'


def test_forward_whitespace_comment_treated_as_empty(env):
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        db.set_meta('forward_channel', '@mychannel')
        forward_messages = AsyncMock(return_value=MagicMock(id=7))
        send_message = AsyncMock()
        client.app.state.tg.service = _service(forward_messages=forward_messages, send_message=send_message)

        assert client.post('/api/messages/5/100/forward', json={'comment': '   '}).json()['mode'] == 'forward'
        forward_messages.assert_awaited_once()
        send_message.assert_not_awaited()


def test_forward_422_when_target_not_configured(env):
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        client.app.state.tg.service = _service(forward_messages=AsyncMock(), send_message=AsyncMock())

        r = client.post('/api/messages/5/100/forward', json={})
        assert r.status_code == 422
        assert r.json()['detail'] == 'forward target channel not configured'


def test_forward_503_when_unauthorized(env):
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        db.set_meta('forward_channel', '@mychannel')
        client.app.state.tg.service = None

        r = client.post('/api/messages/5/100/forward', json={})
        assert r.status_code == 503
        assert r.json()['detail'] == 'telegram not authorized'


# --- app_meta.forward_channel -----------------------------------------------


def test_app_meta_forward_channel_roundtrip(env):
    with _client() as client:
        _login(client)

        assert client.get('/api/app/meta').json()['forward_channel'] is None

        assert (
            client.patch('/api/app/meta', json={'forward_channel': ' @mychannel '}).json()['forward_channel']
            == '@mychannel'
        )
        assert client.get('/api/app/meta').json()['forward_channel'] == '@mychannel'

        # an empty string clears the setting (reads back as null, not '')
        assert client.patch('/api/app/meta', json={'forward_channel': ''}).json()['forward_channel'] is None
        assert client.get('/api/app/meta').json()['forward_channel'] is None
