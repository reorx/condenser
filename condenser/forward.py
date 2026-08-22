"""Rendering a non-Telegram item into a message for the user's own channel.

Telegram is the only outbound channel, so "forward" means two different things.
A Telegram item is *natively* forwardable, and that path — plus the bare t.me
link, which Telegram itself expands into a full message card — stays in ``tg.py``
because both are Telegram-native operations. Everything here is for the sources
Telegram knows nothing about: an HN story or a tweet has to be *written out* as a
new message.

Two shapes, because the two sources give Telegram different things to work with:

* **Hacker News** (approved 2026-07-27) is written out: a bold title line
  hyperlinked to the article, then a source line hyperlinked to the discussion.
  Two links on two lines rather than one line with a trailing link, because
  Telegram builds its preview card from the *first* URL — this way the card shows
  the article while the discussion stays one tap away.
* **X** (revised 2026-07-27) is just a link. x.com serves Telegram no embed, but
  ``fixupx.com`` (same path, FixTweet's x.com-branded host) does — so a bare
  rewritten link renders a card with the author, text and media. Writing those
  into the message body as well would print every tweet twice.
* **RSS** (2026-08-20) is HN's shape minus its second line: an article has one
  destination, and there is no discussion page to link beside it. Telegram builds
  its card from that URL, which is where the site name and blurb come from —
  writing the feed's own name into the body would only repeat it.
"""

import html
from typing import Optional

from . import db
from .items import ItemKey
from .sources import rss as rss_source
from .sources import x as x_source

# The embed-serving mirror of x.com — identical path, so only the host is swapped.
# One constant because these services do go down; swapping it is a one-line change.
X_EMBED_HOST = 'fixupx.com'


class ItemNotFound(Exception):
    """The key parses, but its source row is gone (purged archive, stale client)."""


def _esc(value: Optional[str]) -> str:
    return html.escape(value or '')


def _link(url: str, label: str, bold: bool = False) -> str:
    anchor = f'<a href="{html.escape(url, quote=True)}">{_esc(label)}</a>'
    return f'<b>{anchor}</b>' if bold else anchor


def hn_comments_url(story_id: int) -> str:
    return f'https://news.ycombinator.com/item?id={story_id}'


def x_embed_url(tweet_id: int, handle: Optional[str]) -> str:
    """A tweet's permalink on the embed mirror. Both hosts key off the status id, so
    'i' (X's own canonical stand-in) still resolves when the handle is unknown."""
    return f'https://{X_EMBED_HOST}/{handle or "i"}/status/{tweet_id}'


def _hn_body(story: db.HNStory) -> str:
    # A self-post has no article, so the discussion *is* the destination and both
    # lines point at it.
    comments = hn_comments_url(story.id)
    return '\n'.join(
        [
            _link(story.url or comments, story.title or '(untitled)', bold=True),
            _link(comments, f'Hacker News · {story.score} 分 · {story.comments_count} 评论'),
        ]
    )


def _rss_body(entry: dict) -> str:
    title = entry.get('title') or '(untitled)'
    link = entry.get('link')
    # An entry with no link is rare but real (a feed that carries the whole post
    # and nothing to point at); a bold plain title is the honest degradation.
    return _link(link, title, bold=True) if link else f'<b>{_esc(title)}</b>'


def render(key: ItemKey, comment: str = '') -> str:
    """The Telegram HTML body for a non-Telegram item.

    ``comment`` is escaped and prefixed when non-empty; an empty comment yields the
    body alone — the approved analogue of a native forward. Raises ``ItemNotFound``
    if the source row no longer exists.
    """
    if key.source == 'hn':
        story = db.get_hn_story(key.ref1)
        if story is None:
            raise ItemNotFound(key.key)
        body = _hn_body(story)
    elif key.source == 'x':
        row = x_source.get_row(key.ref1)
        if row is None:
            raise ItemNotFound(key.key)
        # Just the link: fixupx's card already carries the author, text, media and
        # quoted tweet, so anything written here would be printed twice.
        body = _esc(x_embed_url(row['id'], row.get('author_handle')))
    elif key.source == 'rss':
        entry = rss_source.get_row(key.ref1)
        if entry is None:
            raise ItemNotFound(key.key)
        body = _rss_body(entry)
    else:
        raise ValueError(f'{key.source!r} is forwarded natively, not rendered')

    return f'{_esc(comment)}\n\n{body}' if comment else body
