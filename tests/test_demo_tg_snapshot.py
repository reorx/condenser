"""Behavior tests for scripts/demo_tg_snapshot.py — the demo server's Telegram seed.

The demo server carries no Telegram session, ever (kb.private demo-server.md), so
its Telegram source is a snapshot of public channels read through the t.me/s/ web
preview and written straight into the tables a real backfill would fill. Two
halves are pinned here:

* **parsing** — a t.me/s/ page becomes telememo ``MessageData`` in the shape a
  Telethon backfill stores (``-100``-prefixed sender ids, forward headers, link
  previews), except where the demo has to look right rather than faithful:
  plain text instead of Telethon's markdown, and no media (the media proxy needs
  a session, so a media flag would only draw a broken image);
* **loading** — the rows land where the reader looks: subscription, timeline,
  search; a re-run refreshes instead of duplicating, and ``replace`` rewrites
  rows a re-run would leave alone.

The script is not part of the package, so it is loaded by path (the
test_opml_picker precedent). Nothing here touches the network: ``fetch_channel``
takes its page getter as an argument.
"""

import base64
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from condenser.app import create_app

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'demo_tg_snapshot.py'


def _load():
    spec = importlib.util.spec_from_file_location('demo_tg_snapshot', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['demo_tg_snapshot'] = module
    spec.loader.exec_module(module)
    return module


snap = _load()

CHANNEL_ID = 1006503122


def _view(post_id: int, channel_id: int = CHANNEL_ID) -> str:
    raw = json.dumps({'c': -channel_id, 'p': post_id, 't': 1792556125, 'h': 'abc'}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def _post(post_id: int, body: str, when: str, views: str = '1.2K') -> str:
    return f"""
<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="demo/{post_id}" data-view="{_view(post_id)}">
  <div class="tgme_widget_message_bubble">
    <div class="tgme_widget_message_author accent_color"><a class="tgme_widget_message_owner_name" href="https://t.me/demo"><span dir="auto">Demo Channel</span></a></div>
    {body}
    <div class="tgme_widget_message_footer compact js-message_footer"><div class="tgme_widget_message_info short js-message_info">
      <span class="tgme_widget_message_views">{views}</span><span class="copyonly"> views</span>
      <span class="tgme_widget_message_meta"><a class="tgme_widget_message_date" href="https://t.me/demo/{post_id}"><time datetime="{when}" class="time">20:45</time></a></span>
    </div></div>
  </div>
</div></div>"""


def _page(*posts: str, before: int | None = None) -> str:
    more = (
        f'<div class="tgme_widget_message_centered js-messages_more_wrap"><a href="/s/demo?before={before}" '
        f'class="tme_messages_more js-messages_more" data-before="{before}"></a></div>'
        if before
        else ''
    )
    return f"""<!DOCTYPE html><html><body>
<div class="tgme_channel_info">
  <div class="tgme_channel_info_header">
    <div class="tgme_channel_info_header_title_wrap">
      <div class="tgme_channel_info_header_title"><span dir="auto">Demo Channel</span></div>
      <div class="tgme_channel_info_header_labels"><i class="verified-icon"> ✔</i></div>
    </div>
    <div class="tgme_channel_info_header_username"><a href="https://t.me/demo">@demo</a></div>
  </div>
  <div class="tgme_channel_info_counters">
    <div class="tgme_channel_info_counter"><span class="counter_value">10.3M</span> <span class="counter_type">subscribers</span></div>
    <div class="tgme_channel_info_counter"><span class="counter_value">1.2K</span> <span class="counter_type">photos</span></div>
  </div>
  <div class="tgme_channel_info_description">A public channel<br/>for the demo.</div>
</div>
<section class="tgme_channel_history js-message_history">{more}{''.join(posts)}</section>
</body></html>"""


RICH = _post(
    531,
    '<div class="tgme_widget_message_text js-message_text" dir="auto">'
    '<tg-emoji emoji-id="1"><i class="emoji" style="background-image:url(\'//x/E29CA8.png\')"><b>✨</b></i></tg-emoji> '
    '<b>Designers × AI<br/><br/></b>Read <a href="https://telegram.org/blog" target="_blank">the blog</a>, '
    'visit <a href="https://telegram.org/" target="_blank">https://telegram.org/</a>, '
    'follow <a href="https://t.me/durov">@durov</a> and <a href="?q=%23news">#news</a>. '
    '<i>Quietly</i> <code>v12</code>&#33;</div>',
    '2026-10-11T20:45:25+00:00',
    views='5.83M',
)

FORWARDED_WITH_PREVIEW = _post(
    532,
    '<div class="tgme_widget_message_forwarded_from accent_color">Forwarded from&nbsp;'
    '<a class="tgme_widget_message_forwarded_from_name" href="https://t.me/telegram/441"><span dir="auto">Telegram News</span></a></div>'
    '<a class="tgme_widget_message_photo_wrap" style="background-image:url(\'https://cdn4.telesco.pe/file/x.jpg\')"></a>'
    '<div class="tgme_widget_message_text js-message_text" dir="auto">A caption over a photo.</div>'
    '<a class="tgme_widget_message_link_preview" href="https://telegram.org/safety">'
    '<div class="link_preview_site_name accent_color" dir="auto">Telegram</div>'
    '<i class="link_preview_image" style="background-image:url(\'https://cdn4.telesco.pe/file/y.jpg\')"></i>'
    '<div class="link_preview_title" dir="auto">Telegram Safety Overview</div>'
    '<div class="link_preview_description" dir="auto">How moderation works.</div></a>',
    '2026-10-12T08:00:00+00:00',
    views='942',
)

MEDIA_ONLY = _post(
    533,
    '<a class="tgme_widget_message_video_player" href="https://t.me/demo/533"><video class="tgme_widget_message_video"></video></a>',
    '2026-10-13T08:00:00+00:00',
)

REPLY = _post(
    534,
    '<a class="tgme_widget_message_reply" href="https://t.me/demo/531">'
    '<div class="tgme_widget_message_author accent_color"><span class="tgme_widget_message_author_name">Demo Channel</span></div>'
    '<div class="tgme_widget_message_text js-message_text" dir="auto">The quoted parent text.</div></a>'
    '<div class="tgme_widget_message_text js-message_text" dir="auto">The reply itself.</div>',
    '2026-10-14T08:00:00+00:00',
)


# --- parsing ---------------------------------------------------------------------


def test_page_yields_channel_info_with_the_real_channel_id():
    page = snap.parse_page(_page(RICH))
    assert page.channel.id == CHANNEL_ID  # data-view carries -<id>; telememo stores the bare id
    assert page.channel.title == 'Demo Channel'
    assert page.channel.username == 'demo'
    assert page.channel.description == 'A public channel\nfor the demo.'
    assert page.channel.member_count == 10_300_000


def test_text_becomes_plain_text_the_clients_render():
    """Both clients draw message text as plain text with linkified URLs, so any
    markup would show up as literal asterisks; a text link keeps its target in
    parentheses, where the linkifier makes it tappable."""
    (message,) = snap.parse_page(_page(RICH)).messages
    assert message.text == (
        '✨ Designers × AI\n\n'
        'Read the blog (https://telegram.org/blog), visit https://telegram.org/, '
        'follow @durov and #news. Quietly v12!'
    )


def test_post_metadata_matches_a_telethon_backfill_row():
    (message,) = snap.parse_page(_page(RICH)).messages
    assert message.id == 531
    assert message.channel_id == CHANNEL_ID
    assert message.date == datetime(2026, 10, 11, 20, 45, 25, tzinfo=timezone.utc)
    assert message.views == 5_830_000
    assert message.sender_id == -1_000_000_000_000 - CHANNEL_ID
    assert message.sender_name == 'Demo Channel'


def test_media_is_never_flagged_and_link_previews_carry_no_photo():
    """The media proxy streams from Telegram and 503s without a session: a flag
    would draw a broken image, so a captioned photo arrives as its caption."""
    (message,) = snap.parse_page(_page(FORWARDED_WITH_PREVIEW)).messages
    assert message.text == 'A caption over a photo.'
    assert message.has_media is False
    assert message.webpage is not None
    assert message.webpage.url == 'https://telegram.org/safety'
    assert message.webpage.site_name == 'Telegram'
    assert message.webpage.title == 'Telegram Safety Overview'
    assert message.webpage.description == 'How moderation works.'
    assert message.webpage.has_photo is False


def test_forward_header_is_kept():
    (message,) = snap.parse_page(_page(FORWARDED_WITH_PREVIEW)).messages
    assert message.is_forwarded is True
    assert message.fwd_from_channel_name == 'Telegram News'


def test_posts_with_nothing_to_read_are_skipped():
    page = snap.parse_page(_page(RICH, MEDIA_ONLY))
    assert [m.id for m in page.messages] == [531]


def test_a_reply_keeps_its_own_text_not_the_quoted_parent():
    (message,) = snap.parse_page(_page(REPLY)).messages
    assert message.text == 'The reply itself.'


def test_counts_parse_with_their_suffixes():
    assert snap.parse_count('5.83M') == 5_830_000
    assert snap.parse_count('1.66K') == 1_660
    assert snap.parse_count('942') == 942
    assert snap.parse_count('') is None


def test_fetch_channel_pages_back_until_it_has_enough_posts():
    older = _post(
        529, '<div class="tgme_widget_message_text js-message_text">Older one.</div>', '2026-10-09T08:00:00+00:00'
    )
    oldest = _post(
        528, '<div class="tgme_widget_message_text js-message_text">Oldest.</div>', '2026-10-08T08:00:00+00:00'
    )
    pages = {
        'https://t.me/s/demo': _page(RICH, FORWARDED_WITH_PREVIEW, before=531),
        'https://t.me/s/demo?before=531': _page(oldest, older, before=528),
    }
    asked = []

    def get(url):
        asked.append(url)
        return pages[url].encode()

    snapshot = snap.fetch_channel('demo', limit=3, get=get)
    assert asked == ['https://t.me/s/demo', 'https://t.me/s/demo?before=531']
    assert [m.id for m in snapshot.messages] == [532, 531, 529]  # newest first, cut at the limit
    assert snapshot.channel.id == CHANNEL_ID


def test_fetch_channel_stops_when_the_history_runs_out():
    pages = {'https://t.me/s/demo': _page(RICH)}
    snapshot = snap.fetch_channel('demo', limit=40, get=lambda url: pages[url].encode())
    assert [m.id for m in snapshot.messages] == [531]


# --- loading ---------------------------------------------------------------------


def _snapshot(*posts):
    page = snap.parse_page(_page(*posts))
    return snap.ChannelSnapshot(channel=page.channel, messages=page.messages)


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def test_loaded_snapshot_is_a_subscribed_channel_on_the_timeline(env):
    stats = snap.load([_snapshot(RICH, FORWARDED_WITH_PREVIEW)])
    assert stats == {'channels': 1, 'added': 2, 'updated': 0, 'unchanged': 0}

    with TestClient(create_app()) as client:
        _login(client)
        subs = client.get('/api/subscriptions').json()
        assert [(s['channel_id'], s['username'], s['enabled']) for s in subs] == [(CHANNEL_ID, 'demo', True)]
        items = client.get('/api/timeline', params={'source': 'telegram'}).json()['items']
        assert [i['key'] for i in items] == [f'tg:{CHANNEL_ID}:532', f'tg:{CHANNEL_ID}:531']
        hits = client.get('/api/search', params={'q': 'caption', 'source': 'telegram'}).json()
        assert [h['key'] for h in hits['items']] == [f'tg:{CHANNEL_ID}:532']


def test_loading_marks_the_backfill_done(env):
    """No session will ever backfill this channel; an open backfill flag would
    leave the subscription reading as still syncing."""
    from condenser import db

    snap.load([_snapshot(RICH)])
    assert db.get_subscription(CHANNEL_ID).backfill_done is True


def test_reloading_refreshes_without_duplicating_or_losing_read_state(env):
    snap.load([_snapshot(RICH)])
    with TestClient(create_app()) as client:
        _login(client)
        assert client.post('/api/read', json={'keys': [f'tg:{CHANNEL_ID}:531']}).status_code == 200

    stats = snap.load([_snapshot(RICH, FORWARDED_WITH_PREVIEW)])
    assert stats == {'channels': 1, 'added': 1, 'updated': 0, 'unchanged': 1}

    with TestClient(create_app()) as client:
        _login(client)
        items = client.get('/api/timeline', params={'source': 'telegram'}).json()['items']
        assert [(i['key'], i['is_read']) for i in items] == [
            (f'tg:{CHANNEL_ID}:532', False),
            (f'tg:{CHANNEL_ID}:531', True),
        ]


def test_replace_rewrites_rows_a_plain_rerun_leaves_alone(env):
    """telememo only rewrites a row whose edit_date moved, so a change in how the
    snapshot renders text needs ``replace``: the snapshot channels are wiped (read
    markers and search documents with them) and written fresh."""
    first = _snapshot(RICH)
    snap.load([first])
    reworded = first.model_copy(update={'messages': [first.messages[0].model_copy(update={'text': 'Reworded.'})]})

    assert snap.load([reworded]) == {'channels': 1, 'added': 0, 'updated': 0, 'unchanged': 1}
    assert snap.load([reworded], replace=True) == {'channels': 1, 'added': 1, 'updated': 0, 'unchanged': 0}

    with TestClient(create_app()) as client:
        _login(client)
        items = client.get('/api/timeline', params={'source': 'telegram'}).json()['items']
        assert [i['telegram']['text'] for i in items] == ['Reworded.']
        hits = client.get('/api/search', params={'q': 'Designers', 'source': 'telegram'}).json()
        assert hits['items'] == []
