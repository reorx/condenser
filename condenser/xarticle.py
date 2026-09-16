"""X Article detail -> the HTML the detail pane renders (plan 2026-09-16 §4.1).

xbird hands the body over as Markdown (``content``) beside the metadata Markdown
has no room for: every image's size and caption (``media[]``) and a cover
(``coverMedia``) the body never mentions. Rendering happens here, once, rather
than in two clients, because both already have an HTML path for article bodies —
web's ``sanitizeHtml`` + prose styles, iOS's ``articleBlocks(fromHTML:)`` — and
because only this side holds the metadata: it is what puts ``width``/``height`` on
each ``<img>`` (iOS reserves the image's space from them, so the text does not jump
when it loads) and the cover in front of the body.

Three shape decisions the two clients rely on:

* an image alone in its paragraph is a ``<figure>`` with the caption as its
  ``<figcaption>`` — iOS lifts the image into an image block and the caption falls
  into the text block after it, which is exactly RSS's behavior;
* raw HTML in the Markdown is **escaped**, not passed through. X's MARKDOWN entity
  can carry anything an author pasted (code blocks and tables arrive that way),
  which is also why this is a real parser and not a hand-written subset;
* image URLs stay on ``pbs.twimg.com``. iOS already routes every block image through
  ``/api/preview/image``, so proxying here would nest one proxy inside another;
  web rewrites the ``src`` itself.

No package imports, ``text.py``'s arrangement: ``items.py`` renders through this,
and this must not reach back into anything that imports ``items``.
"""

from typing import Optional

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml

# The env key the image renderer reads its size table from (per render call).
_SIZES_ENV = 'x_article_sizes'


def _mark_figures(state) -> None:
    """Core rule: a paragraph holding nothing but one image renders as a figure.

    The paragraph tokens are hidden rather than removed — markdown-it's renderer
    emits nothing for a hidden token, which is how it draws tight lists — because
    ``<p><figure>`` is invalid nesting that a browser would silently re-parent.
    """
    tokens = state.tokens
    for i in range(1, len(tokens) - 1):
        inline = tokens[i]
        if inline.type != 'inline' or tokens[i - 1].type != 'paragraph_open' or tokens[i + 1].type != 'paragraph_close':
            continue
        children = [c for c in inline.children or [] if not (c.type == 'text' and not c.content.strip())]
        if len(children) == 1 and children[0].type == 'image':
            children[0].meta['figure'] = True
            tokens[i - 1].hidden = True
            tokens[i + 1].hidden = True


def _render_image(self, tokens, idx, options, env) -> str:
    token = tokens[idx]
    src = token.attrGet('src') or ''
    alt = self.renderInlineAsText(token.children or [], options, env)
    img = _img(src, alt, env.get(_SIZES_ENV, {}).get(src))
    if not token.meta.get('figure'):
        return img
    return _figure(img, alt)


_md = MarkdownIt('commonmark', {'html': False}).enable('table').enable('strikethrough')
_md.core.ruler.push('x_article_figures', _mark_figures)
_md.add_render_rule('image', _render_image)


def _size(value) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _img(src: str, alt: str, size: Optional[tuple]) -> str:
    width, height = size or (None, None)
    dims = f' width="{width}" height="{height}"' if width and height else ''
    return f'<img src="{escapeHtml(src)}"{dims} alt="{escapeHtml(alt)}" />'


def _figure(img: str, caption: str) -> str:
    figcaption = f'<figcaption>{escapeHtml(caption)}</figcaption>' if caption.strip() else ''
    return f'<figure>{img}{figcaption}</figure>\n'


def _size_table(detail: dict) -> dict[str, tuple]:
    """``{normalized url: (width, height)}`` over the body images and the cover.

    Keyed by the URL *as markdown-it will emit it*, so a URL the parser
    percent-encodes still finds its size.
    """
    entries = list(detail.get('media') or [])
    if isinstance(detail.get('coverMedia'), dict):
        entries.append(detail['coverMedia'])
    table = {}
    for media in entries:
        if not isinstance(media, dict) or not isinstance(media.get('url'), str):
            continue
        width, height = _size(media.get('width')), _size(media.get('height'))
        if width and height:
            table[_md.normalizeLink(media['url'])] = (width, height)
    return table


def _cover(detail: dict, sizes: dict[str, tuple]) -> str:
    cover = detail.get('coverMedia')
    if not isinstance(cover, dict) or not isinstance(cover.get('url'), str):
        return ''
    src = _md.normalizeLink(cover['url'])
    if not _md.validateLink(src):
        return ''
    return _figure(_img(src, '', sizes.get(src)), '')


def _plain_paragraphs(text: str) -> str:
    lines = (line.strip() for line in text.splitlines())
    return ''.join(f'<p>{escapeHtml(line)}</p>\n' for line in lines if line)


def render_html(detail: Optional[dict]) -> Optional[str]:
    """The stored ``article_detail`` as HTML, or None when there is no body.

    Markdown ``content`` when there is one; xbird's server-rendered ``plainText`` as
    paragraphs otherwise. A cover with no body is not an article — the card's
    preview is already the better thing to show.
    """
    if not isinstance(detail, dict):
        return None
    sizes = _size_table(detail)
    content = detail.get('content')
    plain = detail.get('plainText')
    if isinstance(content, str) and content.strip():
        body = _md.render(content, {_SIZES_ENV: sizes})
    elif isinstance(plain, str) and plain.strip():
        body = _plain_paragraphs(plain)
    else:
        return None
    return _cover(detail, sizes) + body
