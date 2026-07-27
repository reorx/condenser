"""Behavior tests for source-generic forwarding (`POST /api/forward`).

Telegram is the only outbound channel, so "forward" means two different things: a
Telegram item can be *natively* forwarded, while an HN story or a tweet has to be
**rendered** into a new message. These tests pin the rendered shape — approved
2026-07-27: a bold title line hyperlinked to the primary destination, then a source
line hyperlinked to the discussion.

Telegram stays fully mocked (same fakes as test_message_actions.py); HN stories and
tweets are seeded straight into their tables.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from condenser import db
from condenser.app import create_app
from tests.conftest import seed_channel

STORY_ID = 44123
TWEET_ID = 2080526422410752155


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _service(**client_calls):
    fake = MagicMock()
    fake.is_authorized = True
    fake.disconnect = AsyncMock()
    fake.client = MagicMock(**client_calls)
    return fake


def _armed(client, sent_id=999):
    """Configure a target channel + a fake client, returning its two send paths."""
    db.set_meta('forward_channel', '@mychannel')
    send_message = AsyncMock(return_value=MagicMock(id=sent_id))
    forward_messages = AsyncMock(return_value=MagicMock(id=sent_id))
    client.app.state.tg.service = _service(send_message=send_message, forward_messages=forward_messages)
    return send_message, forward_messages


def seed_story(**over):
    fields = dict(
        id=STORY_ID,
        title='Show HN: A tiny SQLite vector index',
        url='https://ex.com/vec',
        domain='ex.com',
        author='alice',
        text=None,
        type='story',
        submitted_at=datetime(2026, 7, 27, 9, 0),
        first_seen_at=datetime(2026, 7, 27, 9, 5),
        day='2026-07-27',
        score=342,
        comments_count=128,
    )
    fields.update(over)
    db.insert_hn_story(**fields)


def seed_tweet(feed='foryou', **over):
    fields = dict(
        id=TWEET_ID,
        author_handle='simonw',
        author_name='Simon Willison',
        text='the thing about embeddings is that they average everything',
        created_at=datetime(2026, 7, 27, 8, 0),
        fetched_at=datetime(2026, 7, 27, 9, 0),
    )
    fields.update(over)
    db.XTweet.create(**fields)
    db.XFeedItem.create(channel_id=feed, tweet_id=fields['id'], first_seen_at=datetime(2026, 7, 27, 9, 0))


def _sent_text(send_message):
    return send_message.await_args.args[1]


# --- Hacker News -------------------------------------------------------------


def test_forward_hn_story_renders_title_link_plus_source_line(env):
    """Title hyperlinks the article, the source line hyperlinks the discussion.

    Two links on two lines: Telegram builds its preview card from the first one
    (the article), and the discussion stays reachable without stealing the card.
    """
    with _client() as client:
        _login(client)
        seed_story()
        send_message, forward_messages = _armed(client)

        r = client.post('/api/forward', json={'key': f'hn:{STORY_ID}', 'comment': '值得一读'})
        assert r.status_code == 200, r.text
        assert r.json() == {'status': 'ok', 'mode': 'quote', 'link': 'https://t.me/mychannel/999'}

        assert _sent_text(send_message) == (
            '值得一读\n\n'
            '<b><a href="https://ex.com/vec">Show HN: A tiny SQLite vector index</a></b>\n'
            f'<a href="https://news.ycombinator.com/item?id={STORY_ID}">Hacker News · 342 分 · 128 评论</a>'
        )
        assert send_message.await_args.kwargs['parse_mode'] == 'html'
        forward_messages.assert_not_awaited()


def test_forward_hn_self_post_points_both_lines_at_the_discussion(env):
    """A self-post has no article, so the discussion *is* the destination."""
    with _client() as client:
        _login(client)
        seed_story(title='Ask HN: How do you back up SQLite?', url=None, domain=None, score=89, comments_count=54)
        send_message, _ = _armed(client)

        assert client.post('/api/forward', json={'key': f'hn:{STORY_ID}'}).status_code == 200
        comments = f'https://news.ycombinator.com/item?id={STORY_ID}'
        assert _sent_text(send_message) == (
            f'<b><a href="{comments}">Ask HN: How do you back up SQLite?</a></b>\n'
            f'<a href="{comments}">Hacker News · 89 分 · 54 评论</a>'
        )


def test_forward_escapes_html_in_source_text(env):
    """Source text is interpolated into HTML — an unescaped '<' would break parsing."""
    with _client() as client:
        _login(client)
        seed_story(title='Rust & C++: a <script> tag walks into a bar')
        send_message, _ = _armed(client)

        assert client.post('/api/forward', json={'key': f'hn:{STORY_ID}'}).status_code == 200
        assert 'Rust &amp; C++: a &lt;script&gt; tag walks into a bar' in _sent_text(send_message)
        assert '<script>' not in _sent_text(send_message)


# --- X -----------------------------------------------------------------------


def test_forward_x_sends_only_a_fixupx_link(env):
    """A bare tweet link is all X needs: fixupx.com serves Telegram the embed that
    x.com refuses, so the preview card carries the author, text and media — writing
    them into the message body too would just duplicate the card."""
    with _client() as client:
        _login(client)
        seed_tweet()
        send_message, forward_messages = _armed(client, sent_id=1000)

        r = client.post('/api/forward', json={'key': f'x:{TWEET_ID}'})
        assert r.status_code == 200, r.text
        assert r.json()['mode'] == 'forward'
        assert _sent_text(send_message) == f'https://fixupx.com/simonw/status/{TWEET_ID}'
        forward_messages.assert_not_awaited()


def test_forward_x_puts_the_link_below_the_comment(env):
    with _client() as client:
        _login(client)
        seed_tweet()
        send_message, _ = _armed(client)

        r = client.post('/api/forward', json={'key': f'x:{TWEET_ID}', 'comment': '说得对'})
        assert r.json()['mode'] == 'quote'
        assert _sent_text(send_message) == f'说得对\n\nhttps://fixupx.com/simonw/status/{TWEET_ID}'


def test_forward_x_uses_the_placeholder_handle_when_the_author_is_unknown(env):
    """fixupx keys off the status id, so an unknown handle still resolves."""
    with _client() as client:
        _login(client)
        seed_tweet(author_handle=None, author_name=None)
        send_message, _ = _armed(client)

        assert client.post('/api/forward', json={'key': f'x:{TWEET_ID}'}).status_code == 200
        assert _sent_text(send_message) == f'https://fixupx.com/i/status/{TWEET_ID}'


def test_forward_x_never_carries_the_tweet_text(env):
    """The card renders it; repeating it in the body would double every tweet."""
    with _client() as client:
        _login(client)
        seed_tweet(text='look at this chart https://t.co/AbC123xyz')
        send_message, _ = _armed(client)

        assert client.post('/api/forward', json={'key': f'x:{TWEET_ID}'}).status_code == 200
        assert 'chart' not in _sent_text(send_message)
        assert 't.co' not in _sent_text(send_message)


# --- comment / mode ----------------------------------------------------------


def test_forward_without_comment_omits_the_comment_block(env):
    """Empty comment on a non-TG item = share the link with nothing added (approved
    analogue of Telegram's native forward), and reports itself as 'forward'."""
    with _client() as client:
        _login(client)
        seed_story()
        send_message, _ = _armed(client)

        r = client.post('/api/forward', json={'key': f'hn:{STORY_ID}', 'comment': '   '})
        assert r.json()['mode'] == 'forward'
        assert _sent_text(send_message).startswith('<b><a href=')


# --- Telegram parity ---------------------------------------------------------


def test_forward_tg_key_still_uses_native_forward(env):
    """A TG item routed through the generic endpoint keeps its native-forward path."""
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        send_message, forward_messages = _armed(client)

        r = client.post('/api/forward', json={'key': 'tg:5:100'})
        assert r.json() == {'status': 'ok', 'mode': 'forward', 'link': 'https://t.me/mychannel/999'}
        assert forward_messages.await_args.kwargs['from_peer'] == '@technews'
        send_message.assert_not_awaited()


def test_forward_tg_with_comment_keeps_the_bare_tme_link(env):
    """Unchanged on purpose: Telegram expands a bare t.me link into a full message
    quote card (channel name, text, media), which beats a hyperlinked title."""
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        send_message, _ = _armed(client)

        assert client.post('/api/forward', json={'key': 'tg:5:100', 'comment': '值得一读'}).status_code == 200
        assert _sent_text(send_message) == '值得一读\n\nhttps://t.me/technews/100'
        assert send_message.await_args.kwargs.get('parse_mode') is None


def test_legacy_tg_endpoint_matches_the_generic_one(env):
    """The old path stays a thin shell so already-installed iOS builds keep working."""
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        send_message, _ = _armed(client)

        legacy = client.post('/api/messages/5/100/forward', json={'comment': 'hi'})
        generic = client.post('/api/forward', json={'key': 'tg:5:100', 'comment': 'hi'})
        assert legacy.status_code == 200
        assert legacy.json() == generic.json()


# --- errors ------------------------------------------------------------------


def test_forward_404_when_the_item_is_gone(env):
    with _client() as client:
        _login(client)
        _armed(client)

        r = client.post('/api/forward', json={'key': 'hn:999999'})
        assert r.status_code == 404
        assert r.json()['detail'] == 'item not found'


def test_forward_422_on_a_malformed_key(env):
    with _client() as client:
        _login(client)
        _armed(client)

        assert client.post('/api/forward', json={'key': 'nope:1'}).status_code == 422


def test_forward_422_when_target_not_configured(env):
    with _client() as client:
        _login(client)
        seed_story()
        client.app.state.tg.service = _service(send_message=AsyncMock(), forward_messages=AsyncMock())

        r = client.post('/api/forward', json={'key': f'hn:{STORY_ID}'})
        assert r.status_code == 422
        assert r.json()['detail'] == 'forward target channel not configured'


def test_forward_503_when_telegram_unauthorized(env):
    with _client() as client:
        _login(client)
        seed_story()
        db.set_meta('forward_channel', '@mychannel')
        client.app.state.tg.service = None

        r = client.post('/api/forward', json={'key': f'hn:{STORY_ID}'})
        assert r.status_code == 503
        assert r.json()['detail'] == 'telegram not authorized'
