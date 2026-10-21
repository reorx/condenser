"""Seed the demo server's Telegram source from public channels' web previews.

The App Store review demo must never carry a Telegram session — that would hand
a reviewer an account — yet the store copy names Telegram, so the reviewer should
find Telegram items. This fills the gap without an account: ``t.me/s/<channel>``
is Telegram's public, login-free preview of a public channel, and its posts are
written into the same rows a real backfill writes (telememo's ``channels`` /
``messages``, condenser's ``subscriptions``, the keyword-filter overlay and the
search index), so the timeline, sidebar, detail pane and search treat them as
ordinary Telegram items.

What a snapshot cannot be, accepted when the approach was chosen (2026-10-21):

* **No media.** The media proxy and the channel avatars stream from Telegram and
  answer 503 without a session, so a media flag would only draw a broken image.
  A captioned photo arrives as its caption, a post that is only a video is
  skipped, link previews carry no photo, avatars fall back to letters.
* **Frozen until re-run.** Nothing refreshes it on its own. Re-running is cheap
  and idempotent — new posts are added, known ones left alone, read state
  survives — so the per-submission checklist re-runs it.
* **Older history cannot be pulled.** iOS's pull-past-the-end calls
  ``/api/tg/fetch-older``, which needs a session.
* **Plain text, not Telethon's markdown** (see ``message_text``): the clients do
  not render markup, so a faithful copy would show asterisks.

Usage::

    # on the demo host: the DB and every dependency live in the container, so
    # the script is piped in rather than installed
    docker compose exec -T condenser-demo /app/.venv/bin/python - refresh < scripts/demo_tg_snapshot.py

    # preview what would be loaded (network only, touches no DB)
    uv run python scripts/demo_tg_snapshot.py fetch --out snapshot.json

    # load a snapshot fetched elsewhere
    ... /app/.venv/bin/python - load /data/snapshot.json < scripts/demo_tg_snapshot.py
"""

import argparse
import base64
import json
import sys
from datetime import datetime
from typing import Callable, Optional

import httpx
from lxml import html
from pydantic import BaseModel, TypeAdapter
from telememo import db as tdb
from telememo.types import ChannelInfo, MessageData, WebPagePreview

from condenser import db, filters, search
from condenser.config import get_settings

# Verified (blue-check) public channels only, so the reviewer sees nobody's
# private reading list and no unofficial re-poster. The three official Telegram
# channels: on topic, and nothing in them a review could object to. @guardian was
# the candidate for daily posts and was dropped (2026-10-21): it is The Guardian's
# Russia-Ukraine war channel, not its general one. A snapshot is re-run before
# each submission, so freshness matters less than content here.
CHANNELS = ('telegram', 'durov', 'TelegramTips')
# Per channel. The preview serves 20 posts a page.
POSTS_PER_CHANNEL = 40

PREVIEW_URL = 'https://t.me/s'
USER_AGENT = 'Mozilla/5.0 (compatible; condenser-demo-snapshot/1.0)'

# A broadcast post's sender is the channel itself, stored the way Telethon reports
# it: the Bot API peer id, -100 followed by the channel id.
_CHANNEL_PEER_OFFSET = -1_000_000_000_000

_SUFFIXES = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}

Getter = Callable[[str], bytes]


class PreviewPage(BaseModel):
    """One t.me/s/ page: the channel header, the readable posts, and the cursor
    to the next-older page (absent when the history has run out)."""

    channel: Optional[ChannelInfo]
    messages: list[MessageData]
    before: Optional[int] = None


class ChannelSnapshot(BaseModel):
    channel: ChannelInfo
    messages: list[MessageData]


class SnapshotError(Exception):
    """A preview that cannot become a snapshot (no such channel, no posts)."""


# --- parsing ---------------------------------------------------------------------


def parse_count(value: Optional[str]) -> Optional[int]:
    """The preview's abbreviated counts: '5.83M', '1.66K', '942'."""
    value = (value or '').strip().replace(',', '')
    if not value:
        return None
    multiplier = _SUFFIXES.get(value[-1].upper())
    if multiplier:
        return round(float(value[:-1]) * multiplier)
    return int(float(value))


def message_text(element) -> str:
    """A message text element as plain text.

    Deliberately not Telethon's markdown, the form a real backfill stores: both
    clients draw message text as plain text with linkified URLs, so on real rows
    the ``**`` / ``__`` / ``[text](url)`` markup shows up literally (a known
    issue). Official channels format nearly every post, and a reviewer reading
    asterisks sees a rendering bug.
    """
    return _inline(element).strip()


def _inline(element) -> str:
    parts = [element.text or '']
    for child in element:
        parts.append(_node(child))
        parts.append(child.tail or '')
    return ''.join(parts)


def _node(element) -> str:
    tag = element.tag if isinstance(element.tag, str) else ''
    if tag == 'br':
        return '\n'
    if tag == 'i' and 'emoji' in (element.get('class') or '').split():
        # custom emoji: an <i> drawing the image around the plain character
        return element.text_content()
    if tag == 'a':
        return _link(_inline(element), element.get('href') or '')
    # bold, italic, code, spoiler…: the text without its formatting
    return _inline(element)


def _link(text: str, href: str) -> str:
    """A text link keeps its target in parentheses, where the linkifier makes it
    tappable. Auto-detected URLs, mentions and hashtags already read as what they
    are, so they stay as shown."""
    shown = text.strip()
    if not shown or not href or href.startswith('?') or shown.startswith(('#', '@')):
        return text
    if _bare(shown) == _bare(href):
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    return f'{lead}{shown} ({href}){trail}'


def _bare(url: str) -> str:
    return url.split('://', 1)[-1].rstrip('/')


def _own(post, cls: str) -> list:
    """Elements of a class that belong to this post, not to the reply it quotes."""
    return post.xpath(
        f'.//*[contains(concat(" ", normalize-space(@class), " "), " {cls} ")]'
        '[not(ancestor::*[contains(@class, "tgme_widget_message_reply")])]'
    )


def _text_of(elements: list) -> Optional[str]:
    value = elements[0].text_content().strip() if elements else ''
    return value or None


def _channel_id(data_view: str) -> int:
    """``data-view`` is base64 JSON whose ``c`` is the negated channel id."""
    raw = base64.urlsafe_b64decode(data_view + '=' * (-len(data_view) % 4))
    return abs(int(json.loads(raw)['c']))


def _classed(cls: str) -> str:
    """An exact class-token test: a bare ``contains(@class, …)`` on
    ``…_header_title`` also matches ``…_header_title_wrap``, which carries the
    verified badge's '✔'."""
    return f'contains(concat(" ", normalize-space(@class), " "), " {cls} ")'


def _channel_info(tree, channel_id: int) -> ChannelInfo:
    title = _text_of(tree.xpath(f'//div[{_classed("tgme_channel_info_header_title")}]')) or ''
    username = _text_of(tree.xpath(f'//div[{_classed("tgme_channel_info_header_username")}]'))
    descriptions = tree.xpath(f'//div[{_classed("tgme_channel_info_description")}]')
    subscribers = tree.xpath(
        f'//div[{_classed("tgme_channel_info_counter")}][span[@class="counter_type"]="subscribers"]'
        '/span[@class="counter_value"]/text()'
    )
    return ChannelInfo(
        id=channel_id,
        title=title,
        username=username.lstrip('@') if username else None,
        description=message_text(descriptions[0]) or None if descriptions else None,
        member_count=parse_count(subscribers[0]) if subscribers else None,
    )


def _webpage(post) -> Optional[WebPagePreview]:
    previews = _own(post, 'tgme_widget_message_link_preview')
    if not previews:
        return None
    preview = previews[0]
    return WebPagePreview(
        url=preview.get('href'),
        site_name=_text_of(_own(preview, 'link_preview_site_name')),
        title=_text_of(_own(preview, 'link_preview_title')),
        description=_text_of(_own(preview, 'link_preview_description')),
        has_photo=False,
    )


def _message(post, channel: ChannelInfo) -> Optional[MessageData]:
    """One post as a backfill row, or None when nothing in it is readable."""
    dates = [t for el in _own(post, 'tgme_widget_message_date') for t in el.xpath('./time/@datetime')]
    texts = _own(post, 'tgme_widget_message_text')
    text = message_text(texts[0]) if texts else ''
    webpage = _webpage(post)
    if not dates or not (text or webpage):
        return None
    forwarded = _own(post, 'tgme_widget_message_forwarded_from')
    return MessageData(
        id=int(post.get('data-post').rsplit('/', 1)[1]),
        channel_id=channel.id,
        text=text or None,
        date=datetime.fromisoformat(dates[0]),
        sender_id=_CHANNEL_PEER_OFFSET - channel.id,
        sender_name=channel.title,
        views=parse_count(_text_of(_own(post, 'tgme_widget_message_views'))),
        has_media=False,
        webpage=webpage,
        is_forwarded=bool(forwarded),
        fwd_from_channel_name=_text_of(_own(post, 'tgme_widget_message_forwarded_from_name')) if forwarded else None,
    )


def parse_page(content: bytes | str) -> PreviewPage:
    tree = html.fromstring(content)
    posts = tree.xpath(
        '//div[contains(concat(" ", normalize-space(@class), " "), " tgme_widget_message ")][@data-post]'
    )
    views = [p.get('data-view') for p in posts if p.get('data-view')]
    if not views:
        return PreviewPage(channel=None, messages=[])
    channel = _channel_info(tree, _channel_id(views[0]))
    messages = [m for m in (_message(p, channel) for p in posts) if m is not None]
    before = tree.xpath('//a[contains(@class, "js-messages_more")]/@data-before')
    return PreviewPage(channel=channel, messages=messages, before=int(before[0]) if before else None)


# --- fetching --------------------------------------------------------------------


def fetch_channel(username: str, limit: int, get: Getter) -> ChannelSnapshot:
    """The channel's newest ``limit`` readable posts, newest first, paging back
    through ``?before=`` until there are enough or the history runs out."""
    url = f'{PREVIEW_URL}/{username}'
    channel: Optional[ChannelInfo] = None
    messages: dict[int, MessageData] = {}
    while True:
        page = parse_page(get(url))
        channel = channel or page.channel
        for message in page.messages:
            messages.setdefault(message.id, message)
        if len(messages) >= limit or page.before is None:
            break
        url = f'{PREVIEW_URL}/{username}?before={page.before}'
    if channel is None:
        raise SnapshotError(f'@{username}: no public preview, or no posts in it')
    newest = sorted(messages.values(), key=lambda m: m.id, reverse=True)[:limit]
    return ChannelSnapshot(channel=channel, messages=newest)


def http_getter(client: httpx.Client) -> Getter:
    def get(url: str) -> bytes:
        res = client.get(url)
        res.raise_for_status()
        return res.content

    return get


def fetch_all(channels: list[str], limit: int) -> list[ChannelSnapshot]:
    headers = {'User-Agent': USER_AGENT}
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as client:
        get = http_getter(client)
        return [fetch_channel(name, limit, get) for name in channels]


# --- loading ---------------------------------------------------------------------


def load(snapshots: list[ChannelSnapshot], replace: bool = False) -> dict[str, int]:
    """Write snapshots into the configured DB the way a backfill would.

    A plain re-run only adds: telememo rewrites a row only when its edit_date
    moved, so posts already stored keep their text, and the reader's read state
    survives. ``replace`` is for when the snapshot itself changed shape (how text
    is rendered, say): each snapshot channel's rows are wiped first — read
    markers and search documents with them, saved items kept
    (``db.delete_channel_messages``) — and written fresh.
    """
    settings = get_settings()
    db.init_db(settings.condenser_db_path, settings.condenser_embedding_dimensions)
    stats = {'channels': 0, 'added': 0, 'updated': 0, 'unchanged': 0}
    for snapshot in snapshots:
        if replace:
            db.delete_channel_messages(snapshot.channel.id)
        added, updated, unchanged = _load_channel(snapshot)
        stats['channels'] += 1
        stats['added'] += added
        stats['updated'] += updated
        stats['unchanged'] += unchanged
    return stats


def _load_channel(snapshot: ChannelSnapshot) -> tuple[int, int, int]:
    channel_id = snapshot.channel.id
    tdb.get_or_create_channel(snapshot.channel)
    db.add_subscription(channel_id)
    # no session will ever backfill this channel; an open flag reads as "syncing"
    db.set_backfill_done(channel_id, True)
    ids = [m.id for m in snapshot.messages]
    existing = tdb.get_messages_by_ids(channel_id, ids)
    _, added, updated, unchanged = tdb.save_messages_batch_smart(snapshot.messages, existing)
    filters.recompute_messages(channel_id, ids)
    for message_id in ids:
        search.index_telegram_unit(channel_id, message_id)
    return added, updated, unchanged


# --- CLI -------------------------------------------------------------------------

_SNAPSHOTS = TypeAdapter(list[ChannelSnapshot])


def _summary(snapshots: list[ChannelSnapshot]) -> str:
    lines = []
    for s in snapshots:
        dates = [m.date for m in s.messages]
        span = f'{min(dates):%Y-%m-%d} … {max(dates):%Y-%m-%d}' if dates else 'no posts'
        lines.append(f'· @{s.channel.username} ({s.channel.title}): {len(s.messages)} posts, {span}')
    return '\n'.join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('fetch', 'refresh'):
        command = commands.add_parser(name)
        command.add_argument('channels', nargs='*', default=list(CHANNELS), help='usernames, default: %(default)s')
        command.add_argument('--limit', type=int, default=POSTS_PER_CHANNEL, help='posts per channel')
    commands.choices['fetch'].add_argument('--out', help='write the snapshot JSON here instead of stdout')
    commands.add_parser('load').add_argument('file', help='a snapshot JSON written by `fetch`')
    for name in ('refresh', 'load'):
        commands.choices[name].add_argument(
            '--replace', action='store_true', help="wipe the snapshot channels' rows first (see load())"
        )
    args = parser.parse_args(argv)

    try:
        if args.command == 'load':
            with open(args.file, 'rb') as f:
                snapshots = _SNAPSHOTS.validate_json(f.read())
        else:
            snapshots = fetch_all(args.channels, args.limit)
        print(_summary(snapshots), file=sys.stderr)
        if args.command == 'fetch':
            payload = _SNAPSHOTS.dump_json(snapshots, indent=2).decode()
            if args.out:
                with open(args.out, 'w', encoding='utf-8') as f:
                    f.write(payload)
            else:
                print(payload)
            return 0
        stats = load(snapshots, replace=args.replace)
    except (SnapshotError, httpx.HTTPError) as exc:
        print(f'FAIL  {exc}', file=sys.stderr)
        return 1
    print(
        f'OK  {stats["channels"]} channel(s): {stats["added"]} added, '
        f'{stats["updated"]} updated, {stats["unchanged"]} unchanged'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
