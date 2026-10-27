"""Materialize keyword rules into messages.is_filtered on the write side.

Spaced words require boundaries; CJK matches substrings because compounds and
particles attach directly. Edge stars widen matching. Custom boundaries let Latin
words touch CJK or underscores, unlike standard word boundaries. Preview shares this matcher
and its codepoint offsets with ingest and rebuilds.
"""

import logging
import re
from typing import Iterable, Optional

from telememo import db as tdb

from . import db
from .text import CJK_RANGES

log = logging.getLogger('condenser.filters')
# Bump whenever a change affects which texts match, so stored flags are rebuilt.
MATCHER_VERSION = 1
MATCHER_META_KEY = 'keyword_filter_matcher_version'
_WORD = rf'[^\W_{CJK_RANGES}]'
_WORD_RE = re.compile(_WORD)


def parse_rule(pattern: str) -> Optional[tuple[str, bool, bool]]:
    pattern = pattern.strip()
    core = pattern.strip('*').strip()
    if not core:
        return None
    return core, pattern.startswith('*'), pattern.endswith('*')


def rule_regex(core: str, open_start: bool, open_end: bool) -> str:
    expression = r'\s+'.join(re.escape(part) for part in core.split())
    if not open_start and _WORD_RE.fullmatch(core[0]):
        expression = f'(?<!{_WORD})' + expression
    if not open_end and _WORD_RE.fullmatch(core[-1]):
        expression += f'(?!{_WORD})'
    return expression


def compile_rules(patterns: Iterable[str]) -> Optional[re.Pattern]:
    rules = [rule_regex(*parsed) for pattern in patterns if (parsed := parse_rule(pattern))]
    if not rules:
        return None
    return re.compile('|'.join(f'(?:{rule})' for rule in rules), re.IGNORECASE)


def prepare(text: str) -> str:
    """Mask percent-encoded bytes with equal-length NULs to preserve offsets."""
    return re.sub(r'%[0-9A-Fa-f]{2}', '\x00' * 3, text)


def text_is_filtered(text: Optional[str], matcher: Optional[re.Pattern]) -> bool:
    return bool(text and matcher and matcher.search(prepare(text)))


def match_spans(text: Optional[str], matcher: Optional[re.Pattern]) -> list[tuple[int, int]]:
    """Return half-open codepoint ranges in the original text."""
    if not text or matcher is None:
        return []
    return [hit.span() for hit in matcher.finditer(prepare(text))]


def near_miss_example(text: str, core: str, open_start: bool, open_end: bool) -> Optional[tuple[str, str]]:
    prepared = prepare(text)
    hit = re.search(rule_regex(core, True, True), prepared, re.IGNORECASE)
    if hit is None:
        return None
    start, end = hit.span()
    while start > 0 and _WORD_RE.fullmatch(prepared[start - 1]):
        start -= 1
    while end < len(prepared) and _WORD_RE.fullmatch(prepared[end]):
        end += 1
    prefix = '*' if open_start or start < hit.start() else ''
    suffix = '*' if open_end or end > hit.end() else ''
    return text[start:end], prefix + core + suffix


def active_patterns(channel_id: int) -> list[str]:
    """Original exclude patterns in effect (global + channel-specific)."""
    cur = tdb.db.execute_sql(
        'SELECT pattern FROM keyword_filters WHERE channel_id IS NULL OR channel_id = ?',
        (channel_id,),
    )
    return [row[0] for row in cur.fetchall()]


def _chunked(seq: list, size: int = 500) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _recompute(channel_id: int, message_ids: Optional[list[int]]) -> None:
    """Recompute is_filtered for a channel (or a subset of its messages).

    Resets the scope to 0, then sets matched rows to 1 — so deleting a rule
    correctly clears previously-filtered messages.
    """
    matcher = compile_rules(active_patterns(channel_id))

    if message_ids is None:
        cur = tdb.db.execute_sql('SELECT id, text FROM messages WHERE channel_id = ?', (channel_id,))
        rows = cur.fetchall()
        tdb.db.execute_sql('UPDATE messages SET is_filtered = 0 WHERE channel_id = ?', (channel_id,))
    else:
        if not message_ids:
            return
        rows = []
        for chunk in _chunked(message_ids):
            placeholders = ','.join('?' for _ in chunk)
            cur = tdb.db.execute_sql(
                f'SELECT id, text FROM messages WHERE channel_id = ? AND id IN ({placeholders})',
                (channel_id, *chunk),
            )
            rows.extend(cur.fetchall())
            tdb.db.execute_sql(
                f'UPDATE messages SET is_filtered = 0 WHERE channel_id = ? AND id IN ({placeholders})',
                (channel_id, *chunk),
            )

    filtered_ids = [mid for (mid, text) in rows if text_is_filtered(text, matcher)]
    for chunk in _chunked(filtered_ids):
        placeholders = ','.join('?' for _ in chunk)
        tdb.db.execute_sql(
            f'UPDATE messages SET is_filtered = 1 WHERE channel_id = ? AND id IN ({placeholders})',
            (channel_id, *chunk),
        )


def recompute_channel(channel_id: int) -> None:
    """Recompute is_filtered for every message in a channel (used on rule changes)."""
    _recompute(channel_id, None)


def recompute_messages(channel_id: int, message_ids: list[int]) -> None:
    """Recompute is_filtered for specific freshly-ingested messages."""
    _recompute(channel_id, message_ids)


def recompute_for_rule_change(channel_id: Optional[int]) -> None:
    """Recompute the scope affected by adding/removing a rule.

    A channel-specific rule only affects that channel; a global rule
    (``channel_id is None``) affects every channel with archived messages.
    """
    if channel_id is not None:
        recompute_channel(channel_id)
        return
    for cid in db.message_channel_ids():
        recompute_channel(cid)


def ensure_materialized() -> None:
    """Rebuild all archived channels on a matcher change; mark only after success."""
    if db.get_meta(MATCHER_META_KEY) == str(MATCHER_VERSION):
        return
    channel_ids = db.message_channel_ids()
    for cid in channel_ids:
        recompute_channel(cid)
    db.set_meta(MATCHER_META_KEY, str(MATCHER_VERSION))
    log.info('Rebuilt keyword filters for %d channels', len(channel_ids))
