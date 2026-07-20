"""Shared provider contract for the federated timeline (plan 2.3)."""

from dataclasses import dataclass

# Separator inside a source-local cursor position ('{ts_raw}\x1f{item_id}').
_SEP = '\x1f'

# Extra rows fetched past `limit` in fetch_new so the reported `count` isn't
# capped by a small poll limit (the client polls with limit=1 but shows the
# real count in the banner). Numerically matches telegram's _ALBUM_BUFFER.
NEW_COUNT_BUFFER = 20


def pack_pos(ts_raw: str, item_id: int) -> str:
    """A source-local cursor position: the raw stored timestamp + tie-break id."""
    return f'{ts_raw}{_SEP}{item_id}'


def unpack_pos(raw: str) -> tuple[str, int]:
    ts_raw, _, item_id = raw.rpartition(_SEP)
    return ts_raw, int(item_id)


@dataclass
class SourceUnit:
    """One display unit as produced by a provider."""

    sort_ts: str  # normalized UTC 'YYYY-MM-DD HH:MM:SS' — the cross-source merge key
    envelope: dict  # the API item envelope (see items.py)
    boundary: str  # source position resuming strictly older than this unit
    head: str  # source position anchoring this unit's newest edge (for /timeline/new)


@dataclass
class SourcePage:
    units: list[SourceUnit]
    has_more: bool  # more units exist strictly older than the last returned
