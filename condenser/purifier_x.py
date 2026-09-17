"""The Purifier's X handler (plan kb/plans/2026-09-17-purifier-x-fxembed.md).

An X status link cannot go through the three renderings in ``purifier.py``: x.com
serves an empty SPA shell, and fixupx.com — the obvious stand-in — 302s every
browser User-Agent back to x.com (its pages are Open Graph cards for chat apps, with
an empty body). What does exist is FxEmbed's anonymous JSON API, so a status page is
*built* rather than fetched: one ``/2/conversation/{id}`` request (the ancestor
chain, the status, its replies) rendered into the reader template. The URL the
reader sees does not change (``/p/x.com/<user>/status/<id>``), so no client knows
FxEmbed exists — and within the server only this module does (``vectors.py`` /
``search.py``'s arrangement): the URL shapes, the fetch, the failure codes, the JSON
shape and the markup.

What the API actually does, measured 2026-09-17 — the code below leans on each:

* Cloudflare in front of it challenges a ``python-httpx/*`` User-Agent (403 + an HTML
  page); the project's own UA passes.
* the verdict is the body's ``code``, which can disagree with the HTTP status.
* ``thread`` is the ancestor chain *ending in the status itself*. A self-thread's
  continuation is not in it: it arrives among ``replies``.
* ``replies`` is X's conversation-module layout, not a flat list: each ranked
  top-level reply followed by the replies under it — and not always in tree order.
* facet indices and ``display_text_range`` count code points (the OpenAPI text says
  UTF-16; not for X), and a note tweet's media facet can point into the legacy
  truncated text — so every facet is checked against the text before it is used.

The only package import is the settings type. ``purifier.py`` hands in the ``link``
/ ``asset`` rewriters, so this module never learns what ``/p`` and ``/pa`` look like.
The markup is ours end to end — every string from the API is escaped here — which is
why the page skips the HTML sanitizer: it would also rewrite the links that must stay
absolute (a playable video file, "more replies on X", which would otherwise loop back
to this very page).
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from typing import Awaitable, Callable, Iterator, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import Settings

# x.com / twitter.com, plus the FixTweet-family mirrors serving the same paths —
# ``forward.py`` itself publishes fixupx.com links.
STATUS_HOSTS = frozenset({'x.com', 'twitter.com', 'fixupx.com', 'fxtwitter.com', 'vxtwitter.com', 'twittpr.com'})
_HOST_PREFIXES = ('www.', 'mobile.', 'm.')
# /<handle>/status/<id>, /i/status/<id>, /i/web/status/<id> (+ the legacy /statuses/),
# with the media / analytics tails X appends. A handle is X's own rule: 1-15 word chars.
_STATUS_PATH_RE = re.compile(
    r'^/(?:i/web|\w{1,15})/status(?:es)?/(\d{1,20})(?:/(?:photo|video)/\d{1,2}|/analytics)?/?$', re.ASCII
)
_HANDLE_RE = re.compile(r'^\w{1,15}$', re.ASCII)

# (HTTP status, parsed JSON body or None when the answer was not JSON)
FetchConversation = Callable[[str, Settings], Awaitable[tuple[int, Optional[dict]]]]
Rewrite = Callable[[str], str]


class FxEmbedError(Exception):
    """FxEmbed answered, and the answer is not a conversation."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def enabled(settings: Settings) -> bool:
    return bool(settings.condenser_purifier_x_api_base.strip())


def _bare_host(host: str) -> str:
    name = host.lower().rsplit('@', 1)[-1].split(':', 1)[0]
    for prefix in _HOST_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def parse_status_url(host: str, path: str) -> Optional[str]:
    """``(host, raw path)`` → the status id when it is an X status link, else None."""
    if _bare_host(host) not in STATUS_HOSTS:
        return None
    match = _STATUS_PATH_RE.match(path)
    return match.group(1) if match else None


# --- fetch --------------------------------------------------------------------


async def fetch_conversation(status_id: str, settings: Settings) -> tuple[int, Optional[dict]]:
    """``GET {base}/2/conversation/{id}``. Judges nothing — ``check_conversation`` does.

    Not ``preview._fetch_capped``: its ``accept`` guard and byte cap are made for
    pages and assets. The User-Agent is not decoration (see the module docstring).
    """
    url = f'{settings.condenser_purifier_x_api_base.strip().rstrip("/")}/2/conversation/{status_id}'
    headers = {'User-Agent': settings.condenser_preview_user_agent, 'Accept': 'application/json'}
    async with httpx.AsyncClient(
        headers=headers, timeout=settings.condenser_preview_fetch_timeout, follow_redirects=True
    ) as client:
        resp = await client.get(url)
    if 'json' not in resp.headers.get('content-type', '').lower():
        return resp.status_code, None
    return resp.status_code, resp.json()


_FAILURES = {
    401: '这条推文受保护或有年龄限制，无法匿名读取。',
    404: '这条推文不存在：可能已被删除，或作者的账号不可用。',
    429: 'FxEmbed 暂时限流了，稍后再试。',
}


def check_conversation(http_status: int, payload) -> dict:
    """The answer → a conversation, or ``FxEmbedError`` naming why. The body's ``code``
    outranks the HTTP status: FxEmbed can say 401 under a 200."""
    code = payload.get('code') if isinstance(payload, dict) else None
    if code == 200 and isinstance(payload.get('status'), dict):
        return payload
    code = code if isinstance(code, int) else http_status
    raise FxEmbedError(_FAILURES.get(code) or f'FxEmbed 没有返回这条推文（{code}）。', code)


# --- the conversation's shape ---------------------------------------------------


def _handle(status: dict) -> str:
    return ((status.get('author') or {}).get('screen_name') or '').lower()


def _parent_id(status: dict) -> Optional[str]:
    replying_to = status.get('replying_to')
    return replying_to.get('status') if isinstance(replying_to, dict) else None


def ancestors_of(thread: list[dict], status_id: Optional[str]) -> list[dict]:
    """``thread`` ends in the status itself; everything before it is the chain above."""
    ids = [item.get('id') for item in thread]
    return thread[: ids.index(status_id)] if status_id in ids else thread


def split_continuation(status: dict, replies: list[dict]) -> tuple[list[dict], list[dict]]:
    """The author's own reply-to-self chain (a thread's next tweets) → out of the replies.

    Followed one link at a time from the status, first match in page order, so a second
    self-reply on the same tweet stays a reply (marked as the author's)."""
    author, current = _handle(status), status.get('id')
    chain: list[dict] = []
    remaining = list(replies)
    while True:
        nxt = next((r for r in remaining if _handle(r) == author and _parent_id(r) == current), None)
        if nxt is None:
            return chain, remaining
        chain.append(nxt)
        remaining.remove(nxt)
        current = nxt.get('id')


@dataclass
class ReplyNode:
    status: dict
    children: list['ReplyNode'] = field(default_factory=list)

    def walk(self) -> Iterator[tuple['ReplyNode', int]]:
        """Depth-first, the node itself first, with its depth below this one."""
        stack = [(self, 0)]
        while stack:
            node, depth = stack.pop()
            yield node, depth
            stack.extend((child, depth + 1) for child in reversed(node.children))


def reply_modules(replies: list[dict]) -> list[ReplyNode]:
    """The page's replies → one tree per top-level reply, in page (ranking) order.

    A reply hangs under its ``replying_to`` wherever the two sit in the list; one whose
    parent is not on the page (a reply to the status, or to a tweet we do not have) is
    a top-level thread of its own."""
    nodes: dict[str, ReplyNode] = {}
    for reply in replies:
        rid = reply.get('id')
        if isinstance(rid, str) and rid not in nodes:
            nodes[rid] = ReplyNode(reply)
    roots = []
    for rid, node in nodes.items():
        parent = _parent_id(node.status)
        if parent in nodes and parent != rid:
            nodes[parent].children.append(node)
        else:
            roots.append(node)
    return roots


def select_modules(roots: list[ReplyNode], author: str, limit: int) -> list[ReplyNode]:
    """The top ``limit`` threads, plus any later one the status author speaks in: an
    author's follow-up in the replies is the part of a discussion worth most, and it
    rarely ranks."""
    return [
        root
        for index, root in enumerate(roots)
        if index < limit or any(_handle(node.status) == author for node, _ in root.walk())
    ]


# --- small formatting helpers -------------------------------------------------------


def _is_http(url) -> bool:
    return isinstance(url, str) and url.lower().startswith(('https://', 'http://'))


def _attr(value: str) -> str:
    return escape(value, quote=True)


def sized(url: str, name: str) -> str:
    """A pbs.twimg.com image → its ``name=`` size variant. ``orig`` is a camera
    original; ``medium`` (≤1200px, ~100KB measured) is what a phone page needs."""
    parts = urlsplit(url)
    if parts.hostname != 'pbs.twimg.com':
        return url
    query = [pair for pair in parts.query.split('&') if pair and not pair.startswith('name=')]
    query.append(f'name={name}')
    return urlunsplit(parts._replace(query='&'.join(query)))


def _count(value) -> str:
    if not isinstance(value, int):
        return ''
    if value >= 100_000_000:
        return f'{value / 100_000_000:.1f}'.removesuffix('.0') + '亿'
    if value >= 10_000:
        return f'{value / 10_000:.1f}'.removesuffix('.0') + '万'
    return str(value)


def _when(timestamp) -> str:
    if not isinstance(timestamp, (int, float)):
        return ''
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def _duration(seconds) -> str:
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return ''
    minutes, secs = divmod(int(seconds), 60)
    return f'{minutes}:{secs:02d}'


def _dims(item: dict) -> str:
    width, height = item.get('width'), item.get('height')
    if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0:
        return f' width="{int(width)}" height="{int(height)}"'
    return ''


# Playable in a phone browser without stalling: the best mp4 up to ~720p.
_MAX_VIDEO_BITRATE = 2_500_000


def playable_video_url(video: dict) -> Optional[str]:
    mp4s = [
        f
        for f in video.get('formats') or []
        if isinstance(f, dict) and f.get('container') == 'mp4' and _is_http(f.get('url'))
    ]
    mp4s.sort(key=lambda f: f.get('bitrate') or 0)
    fitting = [f for f in mp4s if (f.get('bitrate') or 0) <= _MAX_VIDEO_BITRATE]
    if fitting:
        return fitting[-1]['url']
    if mp4s:
        return mp4s[0]['url']
    url = video.get('url')
    return url if _is_http(url) and '.mp4' in url else None


# --- text ---------------------------------------------------------------------------


def _display_range(value, length: int) -> tuple[int, int]:
    """X's own "what to show" span (leading @-mentions and the trailing media link cut
    off). Clamped: a note tweet's range can run past its text."""
    if isinstance(value, list) and len(value) == 2 and all(isinstance(v, int) for v in value):
        start, end = (max(0, min(v, length)) for v in value)
        if start <= end:
            return start, end
    return 0, length


def _locate(text: str, facet) -> Optional[tuple[int, int]]:
    """Where a facet really is. Its indices are trusted only when the text there matches;
    a url / media facet whose indices are stale is found by its t.co link instead (a
    link is unique in a tweet, a mention need not be)."""
    if not isinstance(facet, dict) or not isinstance(facet.get('original'), str) or not facet['original']:
        return None
    kind = facet.get('type')
    if kind in ('url', 'media'):
        expected = facet['original']
    elif kind == 'mention':
        expected = '@' + facet['original']
    else:
        return None
    indices = facet.get('indices')
    if isinstance(indices, list) and len(indices) == 2 and all(isinstance(i, int) for i in indices):
        start, end = indices
        if text[start:end].lower() == expected.lower():
            return start, end
    if kind == 'mention':
        return None
    found = text.find(expected)
    return (found, found + len(expected)) if found >= 0 else None


def facet_spans(text: str, facets) -> list[tuple[int, int, dict]]:
    spans = []
    for facet in facets if isinstance(facets, list) else []:
        located = _locate(text, facet)
        if located is not None:
            spans.append((*located, facet))
    spans.sort(key=lambda span: span[0])
    kept, last_end = [], -1
    for span in spans:
        if span[0] >= last_end:
            kept.append(span)
            last_end = span[1]
    return kept


# --- markup -----------------------------------------------------------------------------

_TOMBSTONES = {
    'deleted': '引用的推文已被删除',
    'suspended': '引用的推文来自一个已被封禁的账号',
    'private': '引用的推文受保护，无法查看',
    'blocked': '引用的推文无法查看（被屏蔽）',
    'unavailable': '引用的推文不可用',
}


@dataclass(frozen=True)
class XPage:
    title: str
    body_html: str
    original_url: str


class _Markup:
    """One conversation's markup. Holds the two rewriters and the status author, the
    three things nearly every piece needs."""

    def __init__(self, link: Rewrite, asset: Rewrite, author: str):
        self.link = link
        self.asset = asset
        self.author = author

    def tweet(self, status: dict, role: str) -> str:
        article = status.get('article') if isinstance(status.get('article'), dict) else None
        skip = {f'https://x.com/i/article/{article.get("id")}'} if article else set()
        badge = role == 'reply' and _handle(status) == self.author
        parts = [self.head(status, badge=badge)]
        text = self.text(status, skip_urls=skip)
        if text:
            parts.append(f'<div class="cd-x-text">{text}</div>')
        # The status the reader opened shows as it is; anything else flagged sensitive
        # keeps its words but hides its pictures behind a tap (no JS: <details>).
        parts.append(self.media(status, gated=role != 'focus' and status.get('possibly_sensitive') is True))
        if article:
            parts.append(self.article(article))
        parts.append(self.quote(status.get('quote')))
        parts.append(self.meta(status, focus=role == 'focus'))
        return f'<article class="cd-x-tweet cd-x-{role}">{"".join(parts)}</article>'

    def head(self, status: dict, *, badge: bool = False) -> str:
        author = status.get('author') or {}
        handle = author.get('screen_name') or ''
        name = author.get('name') or handle
        avatar = author.get('avatar_url')
        img = (
            f'<img class="cd-x-avatar" src="{_attr(self.asset(avatar))}" alt="" loading="lazy">'
            if _is_http(avatar)
            else '<span class="cd-x-avatar"></span>'
        )
        badge_html = '<span class="cd-x-badge">作者</span>' if badge else ''
        return (
            f'<header class="cd-x-head">{img}<span class="cd-x-name">{escape(name)}</span>'
            f'<span class="cd-x-handle">@{escape(handle)}</span>{badge_html}</header>'
        )

    def text(self, status: dict, *, skip_urls: set[str] = frozenset()) -> str:
        raw = status.get('raw_text')
        source = raw.get('text') if isinstance(raw, dict) else None
        if not isinstance(source, str):
            return escape(status.get('text') or '').strip()
        start, end = _display_range(raw.get('display_text_range'), len(source))
        out, pos = [], start
        for span_start, span_end, facet in facet_spans(source, raw.get('facets')):
            if span_start < pos or span_end > end:
                continue  # outside what X shows: leading mentions, the trailing media link
            out.append(escape(source[pos:span_start]))
            out.append(self.facet(facet, source[span_start:span_end], skip_urls))
            pos = span_end
        out.append(escape(source[pos:end]))
        return ''.join(out).strip()

    def facet(self, facet: dict, segment: str, skip_urls: set[str]) -> str:
        kind = facet.get('type')
        if kind == 'media':
            return ''  # the media renders below the text
        if kind == 'mention':
            handle = facet['original']
            if not _HANDLE_RE.match(handle):
                return escape(segment)
            return f'<a href="{_attr(self.link("https://x.com/" + handle))}">@{escape(handle)}</a>'
        target = facet.get('replacement')
        display = facet.get('display') or target or segment
        if target in skip_urls:
            return ''
        if not _is_http(target):
            return escape(display)
        return f'<a href="{_attr(self.link(target))}">{escape(display)}</a>'

    def media(self, status: dict, *, gated: bool) -> str:
        media = status.get('media') if isinstance(status.get('media'), dict) else {}
        parts = []
        photos = [p for p in media.get('photos') or [] if isinstance(p, dict) and _is_http(p.get('url'))]
        if photos:
            parts.append(self.photos(photos))
        for video in media.get('videos') or []:
            if isinstance(video, dict):
                parts.append(self.video(video, status))
        external = media.get('external')
        if isinstance(external, dict) and _is_http(external.get('url')):
            parts.append(f'<a class="cd-x-external" href="{_attr(self.link(external["url"]))}">▶ 外部视频</a>')
        if not parts:
            return ''
        html = f'<div class="cd-x-media">{"".join(parts)}</div>'
        if gated:
            return f'<details class="cd-x-sensitive"><summary>可能含敏感内容 · 点按显示</summary>{html}</details>'
        return html

    def photos(self, photos: list[dict]) -> str:
        cells = []
        for photo in photos[:4]:
            src = self.asset(sized(photo['url'], 'medium'))
            full = self.asset(sized(photo['url'], 'large'))
            alt = photo.get('altText') or ''
            cells.append(
                f'<a href="{_attr(full)}"><img src="{_attr(src)}" alt="{_attr(alt)}"{_dims(photo)} loading="lazy"></a>'
            )
        grid = ' cd-x-grid' if len(cells) > 1 else ''
        return f'<div class="cd-x-photos{grid}">{"".join(cells)}</div>'

    def video(self, video: dict, status: dict) -> str:
        """Video bytes do not go through /pa: the poster does, and the tile opens a
        ~720p mp4, which a phone browser plays without X's login wall. With no mp4 to
        offer, the tile goes to the tweet on X."""
        thumb = video.get('thumbnail_url')
        poster = (
            f'<img src="{_attr(self.asset(sized(thumb, "medium")))}" alt=""{_dims(video)} loading="lazy">'
            if _is_http(thumb)
            else ''
        )
        label = 'GIF' if video.get('type') == 'gif' else '视频'
        duration = _duration(video.get('duration'))
        playable = playable_video_url(video)
        if playable:
            href, caption = playable, f'▶ {label}' + (f' · {duration}' if duration else '')
        else:
            href, caption = status.get('url'), f'▶ {label} · 在 X 上看'
        play = f'<span class="cd-x-play">{escape(caption)}</span>'
        if not _is_http(href):
            return f'<div class="cd-x-video">{poster}{play}</div>'
        return f'<a class="cd-x-video" href="{_attr(href)}">{poster}{play}</a>'

    def article(self, article: dict) -> str:
        """FxEmbed's article block: title, lede and cover. Its ``content`` (Draft.js
        blocks) is not rendered — the card links to the full article on X."""
        cover_info = (article.get('cover_media') or {}).get('media_info') or {}
        cover_url = cover_info.get('original_img_url')
        cover = ''
        if _is_http(cover_url):
            dims = _dims(
                {'width': cover_info.get('original_img_width'), 'height': cover_info.get('original_img_height')}
            )
            cover = f'<img src="{_attr(self.asset(sized(cover_url, "medium")))}" alt=""{dims} loading="lazy">'
        title = article.get('title') or ''
        preview = article.get('preview_text') or ''
        article_id = str(article.get('id') or '')
        more = (
            f'<a href="{_attr(self.link("https://x.com/i/article/" + article_id))}">在 X 上读全文 ↗</a>'
            if article_id.isdigit()
            else ''
        )
        return (
            f'<div class="cd-x-article">{cover}<div class="cd-x-article-title">{escape(title)}</div>'
            f'<p>{escape(preview)}</p>{more}</div>'
        )

    def quote(self, quote) -> str:
        if not isinstance(quote, dict):
            return ''
        if quote.get('type') == 'tombstone':
            message = _TOMBSTONES.get(quote.get('reason')) or '引用的推文不可用'
            return f'<div class="cd-x-quote cd-x-tombstone">{escape(message)}</div>'
        parts = [self.head(quote)]
        text = self.text(quote)
        if text:
            parts.append(f'<div class="cd-x-text">{text}</div>')
        parts.append(self.media(quote, gated=quote.get('possibly_sensitive') is True))
        parts.append(self.meta(quote, focus=False))
        return f'<div class="cd-x-quote">{"".join(parts)}</div>'

    def meta(self, status: dict, *, focus: bool) -> str:
        when = escape(_when(status.get('created_timestamp')))
        if focus:
            stats = [('回复', 'replies'), ('转帖', 'reposts'), ('引用', 'quotes'), ('喜欢', 'likes'), ('浏览', 'views')]
            items = [when] if when else []
        else:
            # Any tweet but the open one links to its own discussion page.
            url = status.get('url')
            items = [f'<a href="{_attr(self.link(url))}">{when or "打开"}</a>'] if _is_http(url) else [when]
            stats = [('回复', 'replies'), ('喜欢', 'likes')]
        for label, key in stats:
            value = status.get(key)
            if isinstance(value, int) and value > 0:
                items.append(f'{_count(value)} {label}')
        return f'<footer class="cd-x-meta">{" · ".join(i for i in items if i)}</footer>'

    def replies(self, status: dict, modules: list[ReplyNode], *, hidden: int, shown: int) -> str:
        blocks = []
        for root in modules:
            nested = [self.tweet(node.status, 'reply') for node, depth in root.walk() if depth > 0]
            nested_html = f'<div class="cd-x-nested">{"".join(nested)}</div>' if nested else ''
            blocks.append(f'<div class="cd-x-module">{self.tweet(root.status, "reply")}{nested_html}</div>')
        total = status.get('replies')
        more = ''
        url = status.get('url')
        if _is_http(url) and (hidden > 0 or (isinstance(total, int) and total > shown)):
            count = f'共 {_count(total)} 条回复' if isinstance(total, int) and total > 0 else '更多回复'
            # Absolute on purpose: through the proxy it would be this page again.
            more = f'<p class="cd-x-more">{count} · <a href="{_attr(url)}">在 X 上看全部 ↗</a></p>'
        if not blocks and not more:
            return ''
        heading = '<h2 class="cd-x-section">回复</h2>' if blocks else ''
        return f'<section class="cd-x-replies">{heading}{"".join(blocks)}{more}</section>'


def render(conversation: dict, *, link: Rewrite, asset: Rewrite, replies_limit: int) -> XPage:
    """A checked conversation → the page body. ``link`` rewrites a document URL (the
    proxy's ``/p``, or left absolute), ``asset`` an image URL (``/pa``)."""
    status = conversation['status']
    author = status.get('author') or {}
    markup = _Markup(link, asset, _handle(status))

    thread = [item for item in conversation.get('thread') or [] if isinstance(item, dict)]
    replies = [item for item in conversation.get('replies') or [] if isinstance(item, dict)]
    continuation, replies = split_continuation(status, replies)
    roots = reply_modules(replies)
    modules = select_modules(roots, _handle(status), replies_limit)

    chain = [markup.tweet(item, 'ancestor') for item in ancestors_of(thread, status.get('id'))]
    chain.append(markup.tweet(status, 'focus'))
    chain.extend(markup.tweet(item, 'continuation') for item in continuation)
    body = (
        f'<div class="cd-x"><div class="cd-x-thread">{"".join(chain)}</div>'
        f'{markup.replies(status, modules, hidden=len(roots) - len(modules), shown=len(modules) + bool(continuation))}</div>'
    )
    title = f'{author.get("name") or author.get("screen_name") or "X"} @{author.get("screen_name") or ""}'
    url = status.get('url')
    return XPage(title=title, body_html=body, original_url=url if _is_http(url) else '')
