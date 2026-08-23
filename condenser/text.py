"""Feed HTML -> the prose a reader would see, and the excerpt cut from it.

A neutral home rather than a section of ``summary.py``, for two reasons. The
stripping is used by two unrelated things now — the LLM summariser's input and
the timeline's ``content_excerpt`` — and only one of them is billed, which is
exactly the distinction ``summary.py``'s module docstring exists to keep sharp.
And ``items.py`` needs the excerpt while ``summary.py`` imports ``db``, which
imports ``items``: a module with no package imports of its own is the only shape
that lets the payload layer share this code.
"""

import html
import re
from typing import Optional

# How much of an article the list payload carries. Sized against what the cards
# actually show: web clamps at five lines, iOS at three-to-eight, and both want
# enough left over that the clamp has something to hide. Bigger buys nothing a
# reader sees; the article is one tap away behind /api/rss/entries/{id}.
EXCERPT_CHARS = 500

# Appended when the body did not fit. It is also the *record* that it did not:
# ``items.rss_payload`` reads it back into ``content_truncated`` so no client has
# to sniff for a character whose constant lives here.
ELLIPSIS = '…'

_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')

# script/style *contents* are not prose: dropping only the tags would send a
# stylesheet to the model, paying for the tokens and getting a worse summary —
# and would print JavaScript on a timeline card.
_NOISE_OPEN_RE = re.compile(r'<(script|style)\b', re.IGNORECASE)
_NOISE_CLOSE_RE = {tag: re.compile(rf'</{tag}\s*>', re.IGNORECASE) for tag in ('script', 'style')}


def _drop_noise(value: str) -> str:
    """Remove every ``<script>`` / ``<style>`` block, contents included.

    A hand-written scan rather than the obvious ``<(script|style)\\b.*?</\\1\\s*>``
    substitution, and the reason is measured: that pattern is **quadratic** on a
    page carrying openers that never close, because the non-greedy tail rescans to
    the end of the document from every candidate. 64KB took 0.37s, 256KB 6.6s, 1MB
    97s — and production's largest archived entry is 7.1MB. Here each ``search``
    resumes where the last one stopped, so the whole pass is one sweep of the
    string (regression test in tests/test_rss_summary.py).

    An **unclosed** opener drops everything after it. That is not a fallback, it is
    the rule: a body truncated mid-``<script>`` would otherwise leak its source as
    "prose", inflating the text past the summariser's length gate and getting
    billed as the article.
    """
    out, pos = [], 0
    while (opener := _NOISE_OPEN_RE.search(value, pos)) is not None:
        out.append(value[pos : opener.start()])
        out.append(' ')
        closer = _NOISE_CLOSE_RE[opener.group(1).lower()].search(value, opener.end())
        if closer is None:
            return ''.join(out)
        pos = closer.end()
    out.append(value[pos:])
    return ''.join(out)


def plain_text(value: Optional[str]) -> str:
    """A feed body's HTML -> the prose a reader would see.

    Not ``search._strip_html``: that one feeds a tokenizer, which does not care
    about script contents or whitespace shape. This one feeds a language model and
    a timeline card, where both are paid for — by the token and by the line.
    """
    if not value:
        return ''
    text = _TAG_RE.sub(' ', _drop_noise(value))
    return _WS_RE.sub(' ', html.unescape(text)).strip()


def excerpt(value: Optional[str]) -> Optional[str]:
    """The list payload's body: ``EXCERPT_CHARS`` of prose, or None if there is none.

    None rather than '' so "this feed item is a bare link" stays distinguishable
    from "we stripped everything away" — the clients branch on it.

    The cut is by character count, mid-word if it lands there. Deliberate: the
    reader this is for reads Chinese, where there is no word boundary to back up
    to, and a rule that only tidies English would make the two look different for
    no reason a reader could name.
    """
    text = plain_text(value)
    if not text:
        return None
    if len(text) <= EXCERPT_CHARS:
        return text
    return text[:EXCERPT_CHARS].rstrip() + ELLIPSIS
