"""KNN index over the labeled tweet set, on sqlite-vec's vec0 virtual table.

This module is the only place that knows sqlite-vec exists. Everything above it
sees four operations — ``upsert`` / ``delete`` / ``knn`` / ``labeled_ids`` — so
swapping the backend is a rewrite of this file and nothing else.

Two properties decided the choice (plan Phase 4, "向量存储"):

* the index lives **in the same SQLite file** as the labels, so backup stays
  "copy one file" and there is no second store to keep alive;
* vec0 shadow tables **participate in the surrounding transaction**, so a label
  and its vector commit or roll back together and cannot drift.

Only the labeled set is indexed (hundreds of rows), never the full archive: the
judge query always searches "things you labeled", and keeping the index small
makes presence — not label values — the only thing that has to stay in sync.
The labels themselves are read back from ``item_feedback`` / ``saved_items``.

The index is a **rebuildable cache**: the vectors of record are BLOBs in
``x_embeddings``, so a version upgrade or a suspected drift is answered by
``verdict.rebuild_labeled_index()`` rather than by a migration.
"""

import logging
import struct
from typing import Optional

from telememo import db as tdb

log = logging.getLogger('condenser.vectors')

TABLE = 'x_vec_labeled'
DIMS_META_KEY = 'x_vec_dims'

# Set by setup(); every entry point checks it so an environment that cannot load
# the extension degrades to "no verdicts" instead of failing requests.
_available = False
_dims: Optional[int] = None


def pack(vector: list[float]) -> bytes:
    """float32 BLOB — sqlite-vec's wire format, and how x_embeddings stores vectors.

    Deliberately independent of the extension: vectors must be storable even where
    sqlite-vec cannot load, so they survive to be indexed on a host where it can.
    """
    return struct.pack(f'{len(vector)}f', *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f'{len(blob) // 4}f', blob))


def available() -> bool:
    return _available


def dims() -> Optional[int]:
    return _dims


def setup(dimensions: int) -> bool:
    """Load the extension on the shared peewee database and ensure the index table.

    peewee's connections are thread-local (uvicorn's threadpool vs. the event
    loop), so registering the extension on the *database* matters: peewee replays
    it on every connection it opens, rather than only on the current one.

    Must run after the ordinary tables are created — a vec0 table is created with
    raw SQL and the extension has to be loaded first.
    """
    global _available, _dims
    _available = False
    _dims = None
    try:
        import sqlite_vec

        tdb.db.load_extension(sqlite_vec.loadable_path())
        _ensure_table(dimensions)
    except Exception as e:  # noqa: BLE001 - a missing/unloadable extension is a degraded mode, not a crash
        log.warning('sqlite-vec unavailable, For You verdicts are disabled: %s', e)
        return False
    _available = True
    _dims = dimensions
    return True


def _ensure_table(dimensions: int) -> None:
    """Create the vec0 table, rebuilding it if the configured dimension changed.

    Changing dimensions invalidates every stored vector anyway (``x_embeddings.model``
    records ``model@dims``, and the reconcile re-embeds anything tagged otherwise),
    so dropping the index is the cheap half of that story.
    """
    from . import db

    previous = db.get_meta(DIMS_META_KEY)
    if previous is not None and previous != str(dimensions):
        log.info('embedding dimensions changed %s -> %s, dropping %s', previous, dimensions, TABLE)
        tdb.db.execute_sql(f'DROP TABLE IF EXISTS {TABLE}')
    tdb.db.execute_sql(
        f'CREATE VIRTUAL TABLE IF NOT EXISTS {TABLE} USING vec0(embedding float[{int(dimensions)}] distance_metric=cosine)'
    )
    db.set_meta(DIMS_META_KEY, str(dimensions))


def labeled_ids() -> set[int]:
    """Tweet ids currently in the index (its rowids are tweet ids)."""
    if not _available:
        return set()
    return {row[0] for row in tdb.db.execute_sql(f'SELECT rowid FROM {TABLE}').fetchall()}


def upsert(tweet_id: int, vector: list[float]) -> None:
    if not _available:
        return
    tdb.db.execute_sql(f'DELETE FROM {TABLE} WHERE rowid = ?', (tweet_id,))
    tdb.db.execute_sql(f'INSERT INTO {TABLE}(rowid, embedding) VALUES (?, ?)', (tweet_id, pack(vector)))


def delete(tweet_id: int) -> None:
    if not _available:
        return
    tdb.db.execute_sql(f'DELETE FROM {TABLE} WHERE rowid = ?', (tweet_id,))


def clear() -> None:
    if not _available:
        return
    tdb.db.execute_sql(f'DELETE FROM {TABLE}')


def knn(vector: list[float], k: int) -> list[tuple[int, float]]:
    """The k nearest labeled tweets as (tweet_id, cosine distance), nearest first."""
    if not _available:
        return []
    # k is interpolated because sqlite-vec expects a literal constraint; it is an
    # int by construction, so there is nothing to inject.
    cur = tdb.db.execute_sql(
        f'SELECT rowid, distance FROM {TABLE} WHERE embedding MATCH ? AND k = {int(k)} ORDER BY distance',
        (pack(vector),),
    )
    return [(row[0], row[1]) for row in cur.fetchall()]
