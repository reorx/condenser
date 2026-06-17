"""Telegram lifecycle + login state manager (spec C1).

Owns the single ``TelegramService`` instance, bridges step-login to encrypted
session storage, runs realtime ingest (computing ``is_filtered`` on arrival), and
schedules per-channel backfill. One instance lives on ``app.state.tg``.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from telethon.errors import FloodWaitError

from telememo import db as tdb
from telememo.service import TelegramService
from telememo.telegram import convert_channel_to_info
from telememo.types import ChannelInfo, DisplayMessage, SignInResult

from . import db, filters
from .config import Settings
from .crypto import decrypt_session, encrypt_session

log = logging.getLogger('condenser.tg')

# Oldest-possible sort key for channels whose dialog carries no last-message date.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class JoinedChannel:
    """A followed channel plus its Telegram-side activity signals (for the browse list)."""

    info: ChannelInfo
    last_message_date: Optional[datetime]
    unread_count: int


class TgManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.service: Optional[TelegramService] = None
        self._pending_phone: Optional[str] = None
        self._pending_code_hash: Optional[str] = None
        self._awaiting_2fa = False
        self._tasks: set[asyncio.Task] = set()
        # time-based cache of the account's joined broadcast channels (see list_joined_channels)
        self._dialogs_cache: Optional[list[JoinedChannel]] = None
        self._dialogs_cache_at: float = 0.0
        self._dialogs_lock = asyncio.Lock()  # collapse concurrent cold-cache fetches into one

    # ---- service construction / lifecycle ----
    def _new_service(self, session: Optional[str] = None) -> TelegramService:
        return TelegramService(self.settings.telegram_api_id, self.settings.telegram_api_hash, session)

    async def startup(self) -> None:
        """Reconnect with the stored session (if any) and resume listening/backfill."""
        row = db.get_tg_session()
        if not (row and row.authorized and row.session_enc):
            return
        session = decrypt_session(self.settings.condenser_secret_key, row.session_enc)
        self.service = self._new_service(session)
        try:
            await self.service.connect()
        except Exception:  # network/session failure at boot must not crash startup
            log.exception('telegram connect failed at startup')
            self.service = None
            return
        if self.service.is_authorized:
            self._pending_phone = row.phone
            log.info('telegram session restored (authorized) for %s', row.phone)
            await self.start_listening()
        else:
            log.warning('stored telegram session is no longer authorized; re-login required')
            self.service = None

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self.service is not None:
            await self.service.disconnect()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- status ----
    def status(self) -> str:
        if self.service is not None and self.service.is_authorized:
            return 'authorized'
        if self._pending_code_hash is not None:
            return 'awaiting_2fa' if self._awaiting_2fa else 'awaiting_code'
        return 'unauthorized'

    # ---- step login ----
    async def send_code(self, phone: str) -> None:
        log.info('requesting telegram login code for %s (this sends a code to the account)', phone)
        self.service = self._new_service()
        await self.service.connect()
        self._pending_code_hash = await self.service.send_code(phone)
        self._pending_phone = phone
        self._awaiting_2fa = False

    async def sign_in(self, code: str) -> SignInResult:
        if self.service is None or self._pending_code_hash is None:
            raise RuntimeError('no pending login; call send-code first')
        res = await self.service.sign_in_code(self._pending_phone, code, self._pending_code_hash)
        if res.status == '2fa_required':
            self._awaiting_2fa = True
            return res
        await self._on_authorized(res.session)
        return res

    async def sign_in_2fa(self, password: str) -> SignInResult:
        if self.service is None:
            raise RuntimeError('no pending login; call send-code first')
        res = await self.service.sign_in_2fa(password)
        await self._on_authorized(res.session)
        return res

    async def _on_authorized(self, session: str) -> None:
        enc = encrypt_session(self.settings.condenser_secret_key, session)
        db.save_tg_session(self._pending_phone, enc, authorized=True)
        self._pending_code_hash = None
        self._awaiting_2fa = False
        await self.start_listening()

    async def logout(self) -> None:
        if self.service is not None:
            try:
                await self.service.client.log_out()
            except Exception:
                log.exception('telegram log_out failed')
            await self.service.disconnect()
        self.service = None
        self._pending_phone = None
        self._pending_code_hash = None
        self._awaiting_2fa = False
        self._dialogs_cache = None
        self._dialogs_cache_at = 0.0
        db.clear_tg_session()

    def _require_service(self) -> TelegramService:
        if self.service is None or not self.service.is_authorized:
            raise RuntimeError('telegram not authorized')
        return self.service

    # ---- realtime + backfill ----
    async def start_listening(self) -> None:
        service = self._require_service()
        channels = db.enabled_channel_ids()
        if channels:
            await service.subscribe(channels, on_message=self._on_new_message, persist=True)
        for cid in db.pending_backfill_channel_ids():
            self._spawn(self._backfill_channel(cid))

    async def refresh_subscription(self) -> None:
        """Re-sync the realtime listener to the current enabled-channel set."""
        service = self._require_service()
        channels = db.enabled_channel_ids()
        if not channels:
            if service.is_listening:
                await service.unsubscribe()
            return
        if service.is_listening:
            await service.update_subscription(channels)
        else:
            await service.subscribe(channels, on_message=self._on_new_message, persist=True)

    async def _on_new_message(self, dm: DisplayMessage) -> None:
        ids = dm.raw_message_ids or [dm.id]
        filters.recompute_messages(dm.channel_id, ids)

    async def _backfill_channel(self, channel_id: int) -> int:
        """Pull the recent-days window for one channel; returns the number of rows ingested."""
        service = self._require_service()
        ids: list[int] = []
        try:
            async for dm in service.backfill(channel_id, since_days=self.settings.condenser_backfill_days):
                ids.extend(dm.raw_message_ids or [dm.id])
        except Exception:
            log.exception('backfill failed for channel %s', channel_id)
            return 0
        if ids:
            filters.recompute_messages(channel_id, ids)
        db.set_backfill_done(channel_id, True)
        return len(ids)

    # ---- manual refresh (used by routers) ----
    async def refresh_channel(self, channel_id: int) -> int:
        """Synchronously re-pull one channel's recent window; returns the count of *new* messages.

        Re-running backfill is idempotent (smart-save dedupes), so the useful number to
        report is how many ids landed above the prior watermark — not the whole rescan.
        """
        self._require_service()
        before = db.channel_max_message_id(channel_id)
        await self._backfill_channel(channel_id)
        return db.count_messages_after(channel_id, before)

    def refresh_all(self) -> int:
        """Fan out background backfill for every enabled channel; returns how many were queued."""
        self._require_service()
        channel_ids = db.enabled_channel_ids()
        for cid in channel_ids:
            self._spawn(self._backfill_channel(cid))
        return len(channel_ids)

    async def fetch_older(self, channel_id: int, count: int = 200) -> int:
        """Page further back into a channel's history (synchronous); returns rows fetched.

        Anchors on the oldest stored id and pulls up to ``count`` strictly-older messages,
        ignoring the recent-days cutoff. With nothing stored yet, anchors at the top.
        """
        service = self._require_service()
        oldest = db.channel_min_message_id(channel_id)
        ids: list[int] = []
        try:
            async for dm in service.backfill(channel_id, offset_id=oldest, max_messages=count, persist=True):
                ids.extend(dm.raw_message_ids or [dm.id])
        except Exception:
            log.exception('fetch-older failed for channel %s', channel_id)
            return 0
        if ids:
            filters.recompute_messages(channel_id, ids)
        return len(set(ids))

    # ---- subscription orchestration (used by routers) ----
    def _register_subscription(self, info: ChannelInfo) -> ChannelInfo:
        """Persist channel + subscription row + spawn backfill for an already-resolved channel.

        Does NOT refresh the realtime listener — callers refresh once after a batch.
        """
        tdb.get_or_create_channel(info)
        db.add_subscription(info.id)
        self._spawn(self._backfill_channel(info.id))
        return info

    async def _add_subscription(self, handle: str) -> ChannelInfo:
        """Resolve a handle then register the subscription (see _register_subscription)."""
        service = self._require_service()
        return self._register_subscription(await service.resolve_channel(handle))

    async def subscribe_channel(self, handle: str) -> ChannelInfo:
        """Subscribe to a single channel by handle (@username / t.me link / id)."""
        info = await self._add_subscription(handle)
        await self.refresh_subscription()
        return info

    async def subscribe_channels(self, channel_ids: list[int]) -> tuple[list[ChannelInfo], list[dict]]:
        """Subscribe to several channels by id, refreshing the realtime listener once.

        Channels picked from the browse list are already in ``_dialogs_cache``, so we
        reuse that ChannelInfo instead of re-resolving each id. One bad id (e.g. left the
        channel since listing) must not sink the rest, so failures are absorbed + reported.
        """
        self._require_service()
        cached = {c.info.id: c.info for c in (self._dialogs_cache or [])}
        added: list[ChannelInfo] = []
        failed: list[dict] = []
        for cid in channel_ids:
            try:
                added.append(
                    self._register_subscription(cached[cid])
                    if cid in cached
                    else await self._add_subscription(str(cid))
                )
            except Exception as e:  # noqa: BLE001 — batch resilience (top-level orchestrator)
                log.exception('batch subscribe failed for channel %s', cid)
                failed.append({'channel_id': cid, 'error': str(e)})
        if added:
            await self.refresh_subscription()
        return added, failed

    async def list_joined_channels(self, force: bool = False) -> list[JoinedChannel]:
        """List the account's joined broadcast channels, newest-activity first.

        Excludes groups/supergroups/DMs; carries each channel's Telegram-side unread count
        and last-message date. Served from a TTL cache (``condenser_dialogs_cache_ttl``)
        since ``iter_dialogs`` is slow and FloodWait-prone; ``force=True`` bypasses it.
        """
        ttl = self.settings.condenser_dialogs_cache_ttl

        def fresh() -> bool:
            return not force and self._dialogs_cache is not None and (time.monotonic() - self._dialogs_cache_at) < ttl

        if fresh():
            return self._dialogs_cache  # type: ignore[return-value]

        async with self._dialogs_lock:
            if fresh():  # another request refreshed it while we waited for the lock
                return self._dialogs_cache  # type: ignore[return-value]

            service = self._require_service()
            found: dict[int, JoinedChannel] = {}
            waited = 0
            while True:
                try:
                    async for dialog in service.client.iter_dialogs():
                        if dialog.is_channel and not dialog.is_group:
                            found[dialog.entity.id] = JoinedChannel(
                                info=convert_channel_to_info(dialog.entity),
                                last_message_date=dialog.date,
                                unread_count=dialog.unread_count or 0,
                            )
                    break
                except FloodWaitError as e:  # bounded back-off — an HTTP request can't hang forever
                    if waited + e.seconds > 60:
                        raise
                    waited += e.seconds + 1
                    await asyncio.sleep(e.seconds + 1)

            self._dialogs_cache = sorted(found.values(), key=lambda c: c.last_message_date or _EPOCH, reverse=True)
            self._dialogs_cache_at = time.monotonic()  # stamp after the fetch, not before the back-off
            return self._dialogs_cache
