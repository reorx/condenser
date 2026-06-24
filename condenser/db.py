"""Condenser data layer (spec Part B).

Condenser shares telememo's single SQLite file. telememo tables (channels,
messages, comments) are owned by telememo's Peewee models and the ``is_filtered``
extension column; the app-state tables below are condenser's own, bound to the
same Peewee database object so everything lives on one connection.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from peewee import (
    AutoField,
    BlobField,
    BooleanField,
    CharField,
    CompositeKey,
    DateTimeField,
    IntegerField,
    Model,
    TextField,
)

from telememo import db as tdb

# The condenser is_filtered overlay column declared on telememo's messages table.
MESSAGES_OPTIONAL_FIELDS = {
    'messages': [{'name': 'is_filtered', 'type': 'BOOLEAN', 'default': 0}],
}

# Bumped when condenser's own table shapes change; recorded in app_meta on init so a
# future startup can detect an upgrade and run a migration. Telememo manages its own
# table migrations separately (init_db optional_fields / ALTER TABLE).
SCHEMA_VERSION = 1


class CondenserBaseModel(Model):
    class Meta:
        database = tdb.db


class Subscription(CondenserBaseModel):
    channel_id = IntegerField(primary_key=True)
    enabled = BooleanField(default=True)
    backfill_done = BooleanField(default=False)
    added_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'subscriptions'


class KeywordFilter(CondenserBaseModel):
    id = AutoField()
    channel_id = IntegerField(null=True)  # NULL = global rule
    pattern = TextField()
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'keyword_filters'


class ReadMessage(CondenserBaseModel):
    channel_id = IntegerField()
    message_id = IntegerField()
    read_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'read_messages'
        primary_key = CompositeKey('channel_id', 'message_id')


class TelegramRecord(CondenserBaseModel):
    channel_id = IntegerField()
    message_id = IntegerField()
    raw_data = TextField()
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'telegram_records'
        primary_key = CompositeKey('channel_id', 'message_id')


class TgSession(CondenserBaseModel):
    id = IntegerField(primary_key=True)
    phone = CharField(null=True)
    session_enc = BlobField(null=True)
    authorized = BooleanField(default=False)
    updated_at = DateTimeField(null=True)

    class Meta:
        table_name = 'tg_session'


class AppMeta(CondenserBaseModel):
    key = CharField(primary_key=True)
    value = TextField(null=True)

    class Meta:
        table_name = 'app_meta'


class LinkPreviewCache(CondenserBaseModel):
    """Cache of self-fetched URL previews, keyed by a normalized URL.

    Condenser-owned (not a telememo table), so the extension-column contract does
    not apply — we may upsert freely. ``ok`` distinguishes successful previews from
    cached failures (negative caching with a shorter TTL). ``fetched_at`` is stored
    naive-UTC so peewee round-trips it in its default datetime format.
    """

    url = TextField(primary_key=True)
    ok = BooleanField()
    title = TextField(null=True)
    description = TextField(null=True)
    image = TextField(null=True)
    site_name = TextField(null=True)
    canonical_url = TextField(null=True)
    error = TextField(null=True)
    fetched_at = DateTimeField()

    class Meta:
        table_name = 'link_previews'


CONDENSER_TABLES = [Subscription, KeywordFilter, ReadMessage, TelegramRecord, TgSession, AppMeta, LinkPreviewCache]


def init_db(db_path: str) -> None:
    """Initialize the shared SQLite file: telememo tables (+ is_filtered) then condenser tables."""
    tdb.init_db(db_path, optional_fields=MESSAGES_OPTIONAL_FIELDS)
    tdb.db.create_tables(CONDENSER_TABLES)
    _enable_wal(db_path)
    set_meta('schema_version', str(SCHEMA_VERSION))


def _enable_wal(db_path: str) -> None:
    """Switch the database to WAL journaling so a writer and readers can coexist.

    Realtime ingest writes from the event-loop thread while user requests run on
    uvicorn's sync threadpool — multiple connections to one file. WAL lets readers
    proceed during a write instead of hitting ``database is locked``. The mode is a
    persistent property stored in the file header, so setting it once is enough; new
    per-thread connections inherit it. In-memory databases don't support WAL (each
    ``:memory:`` connection is a distinct db), so we skip them.
    """
    if db_path == ':memory:':
        return
    tdb.db.execute_sql('PRAGMA journal_mode=WAL')


def close_db() -> None:
    tdb.close_db()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_naive() -> datetime:
    """Current UTC time as a naive datetime (peewee round-trips naive datetimes cleanly)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- tg_session (single row, id=1) ------------------------------------------


def get_tg_session() -> Optional[TgSession]:
    return TgSession.get_or_none(TgSession.id == 1)


def save_tg_session(phone: Optional[str], session_enc: Optional[bytes], authorized: bool) -> None:
    """Upsert the single tg_session row."""
    TgSession.insert(id=1, phone=phone, session_enc=session_enc, authorized=authorized, updated_at=_now()).on_conflict(
        conflict_target=[TgSession.id],
        update={
            TgSession.phone: phone,
            TgSession.session_enc: session_enc,
            TgSession.authorized: authorized,
            TgSession.updated_at: _now(),
        },
    ).execute()


def clear_tg_session() -> None:
    TgSession.delete().where(TgSession.id == 1).execute()


# --- subscriptions ----------------------------------------------------------


def list_subscriptions() -> list[Subscription]:
    return list(Subscription.select().order_by(Subscription.added_at.desc()))


def get_subscription(channel_id: int) -> Optional[Subscription]:
    return Subscription.get_or_none(Subscription.channel_id == channel_id)


def add_subscription(channel_id: int) -> Subscription:
    sub, _ = Subscription.get_or_create(
        channel_id=channel_id, defaults={'enabled': True, 'backfill_done': False, 'added_at': _now()}
    )
    return sub


def set_subscription_enabled(channel_id: int, enabled: bool) -> None:
    Subscription.update(enabled=enabled).where(Subscription.channel_id == channel_id).execute()


def set_backfill_done(channel_id: int, done: bool = True) -> None:
    Subscription.update(backfill_done=done).where(Subscription.channel_id == channel_id).execute()


def delete_subscription(channel_id: int) -> None:
    Subscription.delete().where(Subscription.channel_id == channel_id).execute()


def enabled_channel_ids() -> list[int]:
    return [s.channel_id for s in Subscription.select().where(Subscription.enabled == True)]  # noqa: E712


def pending_backfill_channel_ids() -> list[int]:
    return [
        s.channel_id
        for s in Subscription.select().where(
            (Subscription.enabled == True) & (Subscription.backfill_done == False)  # noqa: E712
        )
    ]


def channel_max_message_id(channel_id: int) -> int:
    """Highest stored message id for a channel (0 if none) — a watermark for new-message diffs."""
    cur = tdb.db.execute_sql('SELECT MAX(id) FROM messages WHERE channel_id = ?', (channel_id,))
    return cur.fetchone()[0] or 0


def channel_min_message_id(channel_id: int) -> int:
    """Lowest stored message id for a channel (0 if none) — the page-back anchor for older fetches."""
    cur = tdb.db.execute_sql('SELECT MIN(id) FROM messages WHERE channel_id = ?', (channel_id,))
    return cur.fetchone()[0] or 0


def delete_channel_messages(channel_id: int) -> int:
    """Wipe a channel's cached messages, comments, and read markers; returns messages deleted.

    Saved records (``telegram_records``) and keyword filters are intentionally preserved —
    they are user assets / config, not re-syncable source cache.
    """
    deleted = tdb.get_message_count(channel_id)
    with tdb.db.atomic():
        ReadMessage.delete().where(ReadMessage.channel_id == channel_id).execute()
        tdb.db.execute_sql('DELETE FROM comments WHERE parent_channel_id = ?', (channel_id,))
        tdb.db.execute_sql('DELETE FROM messages WHERE channel_id = ?', (channel_id,))
    return deleted


def count_messages_after(channel_id: int, after_id: int) -> int:
    """Count stored messages with id above ``after_id`` (Telegram ids are monotonic per channel)."""
    cur = tdb.db.execute_sql('SELECT COUNT(*) FROM messages WHERE channel_id = ? AND id > ?', (channel_id, after_id))
    return cur.fetchone()[0]


# --- keyword filters --------------------------------------------------------


def list_all_filters() -> list[KeywordFilter]:
    """All filters across every channel, plus global rules (channel_id IS NULL)."""
    return list(KeywordFilter.select().order_by(KeywordFilter.channel_id.asc(nulls='FIRST'), KeywordFilter.created_at))


def add_filter(channel_id: Optional[int], pattern: str) -> KeywordFilter:
    return KeywordFilter.create(channel_id=channel_id, pattern=pattern, created_at=_now())


def get_filter(filter_id: int) -> Optional[KeywordFilter]:
    return KeywordFilter.get_or_none(KeywordFilter.id == filter_id)


def delete_filter(filter_id: int) -> None:
    KeywordFilter.delete().where(KeywordFilter.id == filter_id).execute()


# --- read markers -----------------------------------------------------------


def _expand_album_siblings(channel_id: int, message_id: int) -> list[int]:
    """All raw message ids belonging to the same display unit as (channel_id, message_id).

    A display unit collapses an album (rows sharing ``grouped_id``) under its primary id,
    but unread counts and the unread filter operate per raw row — so marking a unit read
    must touch every sibling, not just the primary. Falls back to the id itself when the
    message is not (or no longer) in telememo's cache.
    """
    cur = tdb.db.execute_sql(
        'SELECT sib.id FROM messages tgt '
        'JOIN messages sib ON sib.channel_id = tgt.channel_id '
        '  AND (sib.id = tgt.id OR (tgt.grouped_id IS NOT NULL AND sib.grouped_id = tgt.grouped_id)) '
        'WHERE tgt.channel_id = ? AND tgt.id = ?',
        (channel_id, message_id),
    )
    sibs = [row[0] for row in cur.fetchall()]
    return sibs or [message_id]


def mark_read(items: list[tuple[int, int]]) -> int:
    """Mark (channel_id, message_id) pairs as read; idempotent. Returns count touched.

    Each pair is expanded to its album siblings so an album clears its unread count fully.
    """
    if not items:
        return 0
    pairs = {(c, sib) for c, m in items for sib in _expand_album_siblings(c, m)}
    rows = [{'channel_id': c, 'message_id': m, 'read_at': _now()} for c, m in pairs]
    with tdb.db.atomic():
        ReadMessage.insert_many(rows).on_conflict_ignore().execute()
    return len(rows)


def mark_read_bulk(channel_id: Optional[int], before_date: Optional[str]) -> None:
    """Mark every subscribed, unfiltered message before a date (optionally one channel) as read."""
    where = ['m.is_filtered IS NOT 1']
    params: list = []
    if channel_id is not None:
        where.append('m.channel_id = ?')
        params.append(channel_id)
    if before_date:
        where.append('substr(m.date, 1, 10) < ?')
        params.append(before_date)
    sql = (
        'INSERT OR IGNORE INTO read_messages (channel_id, message_id, read_at) '
        'SELECT m.channel_id, m.id, ? FROM messages m '
        'JOIN subscriptions s ON s.channel_id = m.channel_id AND s.enabled = 1 '
        'WHERE ' + ' AND '.join(where)
    )
    tdb.db.execute_sql(sql, (_now().isoformat(sep=' '), *params))


# --- records (user assets, source-decoupled) --------------------------------


def add_record(channel_id: int, message_id: int, raw_data: dict) -> None:
    TelegramRecord.insert(
        channel_id=channel_id, message_id=message_id, raw_data=json.dumps(raw_data), created_at=_now()
    ).on_conflict_ignore().execute()


def delete_record(channel_id: int, message_id: int) -> None:
    TelegramRecord.delete().where(
        (TelegramRecord.channel_id == channel_id) & (TelegramRecord.message_id == message_id)
    ).execute()


def list_records() -> list[TelegramRecord]:
    return list(TelegramRecord.select().order_by(TelegramRecord.created_at.desc()))


# --- app_meta ---------------------------------------------------------------


def get_meta(key: str) -> Optional[str]:
    row = AppMeta.get_or_none(AppMeta.key == key)
    return row.value if row else None


def set_meta(key: str, value: str) -> None:
    AppMeta.insert(key=key, value=value).on_conflict(
        conflict_target=[AppMeta.key], update={AppMeta.value: value}
    ).execute()


def effective_backfill_days(env_default: int) -> int:
    """Resolve the backfill window: an app_meta runtime override wins over the env default.

    ``CONDENSER_BACKFILL_DAYS`` sets the baseline, but the value can be tuned at runtime
    (via ``PATCH /api/app/meta``) without a restart. A malformed/absent override falls
    back to the env default.
    """
    raw = get_meta('backfill_days')
    if raw is None:
        return env_default
    try:
        days = int(raw)
    except ValueError:
        return env_default
    return days if days > 0 else env_default


# --- link preview cache -----------------------------------------------------


def get_cached_preview(url_key: str) -> Optional[LinkPreviewCache]:
    return LinkPreviewCache.get_or_none(LinkPreviewCache.url == url_key)


def upsert_preview(
    url_key: str,
    *,
    ok: bool,
    title: Optional[str] = None,
    description: Optional[str] = None,
    image: Optional[str] = None,
    site_name: Optional[str] = None,
    canonical_url: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Insert/replace a cached preview keyed by the normalized URL."""
    fields = {
        'ok': ok,
        'title': title,
        'description': description,
        'image': image,
        'site_name': site_name,
        'canonical_url': canonical_url,
        'error': error,
        'fetched_at': _now_naive(),
    }
    LinkPreviewCache.insert(url=url_key, **fields).on_conflict(
        conflict_target=[LinkPreviewCache.url],
        update={getattr(LinkPreviewCache, k): v for k, v in fields.items()},
    ).execute()
