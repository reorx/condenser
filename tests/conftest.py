"""Condenser test fixtures: env config + DB seeding helpers (Telegram fully mocked)."""

from datetime import datetime, timedelta, timezone

import pytest

from telememo import db as tdb
from telememo.types import ChannelInfo, MessageData

BASE = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('TELEGRAM_API_ID', '1')
    monkeypatch.setenv('TELEGRAM_API_HASH', 'hash')
    monkeypatch.setenv('CONDENSER_APP_PASSWORD', 'pw')
    monkeypatch.setenv('CONDENSER_SECRET_KEY', 'secret')
    monkeypatch.setenv('CONDENSER_DB_PATH', str(tmp_path / 'condenser.db'))
    monkeypatch.setenv('CONDENSER_BACKFILL_DAYS', '7')
    from condenser.config import get_settings

    get_settings.cache_clear()
    # peewee holds connections per-thread; the lifespan runs in a portal thread, so
    # close any stale main-thread connection before/after each test to avoid the
    # seed helpers reusing a previous test's DB file.
    if not tdb.db.is_closed():
        tdb.db.close()
    yield
    get_settings.cache_clear()
    if not tdb.db.is_closed():
        tdb.db.close()


def md(channel_id, mid, minutes, text='x', **extra):
    return MessageData(id=mid, channel_id=channel_id, text=text, date=BASE + timedelta(minutes=minutes), **extra)


def seed_channel(channel_id, title, username=None):
    tdb.get_or_create_channel(ChannelInfo(id=channel_id, title=title, username=username))


def seed_messages(message_datas):
    tdb.save_messages_batch_smart(message_datas, {})
