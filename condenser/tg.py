"""Telegram lifecycle + login state manager (spec C1).

Owns the single ``TelegramService`` instance, bridges step-login to encrypted
session storage, runs realtime ingest (computing ``is_filtered`` on arrival), and
schedules per-channel backfill. One instance lives on ``app.state.tg``.
"""

import asyncio
import logging
from typing import Optional

from telememo import db as tdb
from telememo.service import TelegramService
from telememo.types import ChannelInfo, DisplayMessage, SignInResult

from . import db, filters
from .config import Settings
from .crypto import decrypt_session, encrypt_session

log = logging.getLogger('condenser.tg')


class TgManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.service: Optional[TelegramService] = None
        self._pending_phone: Optional[str] = None
        self._pending_code_hash: Optional[str] = None
        self._awaiting_2fa = False
        self._tasks: set[asyncio.Task] = set()

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
            await self.start_listening()
        else:
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

    async def _backfill_channel(self, channel_id: int) -> None:
        service = self._require_service()
        ids: list[int] = []
        try:
            async for dm in service.backfill(channel_id, since_days=self.settings.condenser_backfill_days):
                ids.extend(dm.raw_message_ids or [dm.id])
        except Exception:
            log.exception('backfill failed for channel %s', channel_id)
            return
        if ids:
            filters.recompute_messages(channel_id, ids)
        db.set_backfill_done(channel_id, True)

    # ---- subscription orchestration (used by routers) ----
    async def subscribe_channel(self, handle: str) -> ChannelInfo:
        """Resolve a handle, persist channel + subscription, and start backfill + realtime."""
        service = self._require_service()
        info = await service.resolve_channel(handle)
        tdb.get_or_create_channel(info)
        db.add_subscription(info.id)
        await self.refresh_subscription()
        self._spawn(self._backfill_channel(info.id))
        return info
