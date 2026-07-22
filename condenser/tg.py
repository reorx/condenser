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

from pydantic import BaseModel
from telethon.errors import FloodWaitError, MessageIdInvalidError, UnauthorizedError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import ReactionCustomEmoji, ReactionEmoji

from telememo import db as tdb
from telememo.entity_cache import EntityNameCache
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


class TelegramMessageNotFound(Exception):
    """A message id no longer resolves on Telegram (deleted, or a bad id)."""


class ReactionCount(BaseModel):
    """One reaction bucket on a message.

    ``kind`` is the discriminator: ``emoji`` carries a unicode ``emoji``, ``custom`` carries a
    ``document_id`` (resolving its glyph needs an extra RPC — clients degrade to a generic
    icon), and ``other`` is the forward-compatible bucket for TL types we don't model
    (``ReactionPaid`` and whatever Telegram adds next), so a new type never 500s.
    """

    kind: str  # 'emoji' | 'custom' | 'other'
    emoji: Optional[str] = None
    document_id: Optional[int] = None
    count: int
    chosen: bool = False


class MessageStats(BaseModel):
    """Live engagement numbers for one message. ``None`` = the channel doesn't carry it."""

    views: Optional[int] = None
    forwards: Optional[int] = None
    reactions: list[ReactionCount] = []


def _normalize_target(target: str) -> str | int:
    """Coerce a configured forward target into something Telethon can resolve.

    A bare numeric string is an id (int); ``@handle`` / ``t.me/...`` links pass through
    untouched — Telethon resolves both.
    """
    target = target.strip()
    if target.lstrip('-').isdigit():
        return int(target)
    return target


def _target_username(target: str | int) -> Optional[str]:
    """The public username of a forward target, or None for a bare-id (private) target."""
    if isinstance(target, int):
        return None
    handle = target.strip().rstrip('/')
    if handle.startswith('@'):
        return handle[1:] or None
    if 't.me/' in handle:
        tail = handle.rsplit('t.me/', 1)[1]
        return tail or None
    return handle or None


def channel_message_url(channel_id: int, message_id: int) -> str:
    """Original t.me link for a stored message — public via @username, else the /c/ form.

    Mirrors the frontend's ``tgMessageUrl``; built server-side so a client can never
    inject the URL that gets published to the forward target.
    """
    channel = tdb.get_channel(channel_id)
    if channel is not None and channel.username:
        return f'https://t.me/{channel.username}/{message_id}'
    return f'https://t.me/c/{channel_id}/{message_id}'


def _sent_message_url(target: str | int, message_id: int) -> str:
    """t.me link for a message that just landed in the forward target channel."""
    username = _target_username(target)
    if username:
        return f'https://t.me/{username}/{message_id}'
    return f'https://t.me/c/{target}/{message_id}'


def _convert_reactions(reactions) -> list[ReactionCount]:
    """Flatten Telethon's ``MessageReactions`` into our transport model (unknown kinds degrade)."""
    if reactions is None:
        return []
    out: list[ReactionCount] = []
    for result in reactions.results or []:
        reaction = result.reaction
        chosen = result.chosen_order is not None
        if isinstance(reaction, ReactionEmoji):
            out.append(ReactionCount(kind='emoji', emoji=reaction.emoticon, count=result.count, chosen=chosen))
        elif isinstance(reaction, ReactionCustomEmoji):
            out.append(
                ReactionCount(kind='custom', document_id=reaction.document_id, count=result.count, chosen=chosen)
            )
        else:
            out.append(ReactionCount(kind='other', count=result.count, chosen=chosen))
    return out


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
        # Persistent forward-source name cache, shared across service rebuilds.
        self._entity_cache = EntityNameCache(settings.condenser_entity_cache_path)

    # ---- service construction / lifecycle ----
    def _new_service(self, session: Optional[str] = None) -> TelegramService:
        return TelegramService(
            self.settings.telegram_api_id,
            self.settings.telegram_api_hash,
            session,
            entity_cache=self._entity_cache,
        )

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
            self._spawn(self._warm_entity_cache())
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

    async def _warm_entity_cache(self) -> None:
        """Re-populate Telethon's in-session entity cache from the account's dialogs.

        ``StringSession`` persists only the auth_key + DC, not the entity cache, so after a
        restart a bare-id ``get_entity`` for a private (username-less) channel fails until
        Telethon has "met" the peer this process — breaking the media/avatar proxies for
        those channels. Iterating dialogs registers every joined channel's access_hash, so
        the bare-id fallback resolves again. Username channels already route around this via
        ``_channel_handle``; this covers the private ones (you must be a member to read them,
        so they appear in dialogs). Best-effort: reuses the FloodWait-bounded dialogs path and
        swallows failures so a warm miss never crashes startup.
        """
        try:
            channels = await self.list_joined_channels(force=True)
            log.info('entity cache warmed from %d joined channels', len(channels))
        except Exception:
            log.exception('entity cache warm failed (non-fatal)')

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

    @staticmethod
    def _is_auth_error(exc: BaseException) -> bool:
        """Whether an exception means the *authorization* is dead (vs. a transient network error).

        AuthKeyUnregistered / SessionRevoked / UserDeactivated all subclass UnauthorizedError.
        """
        return isinstance(exc, UnauthorizedError)

    async def _demote_session(self) -> None:
        """Tear down a session Telegram no longer accepts (revoked / auth key invalidated).

        Telethon transparently reconnects dropped transports, but an invalidated
        *authorization* never self-heals — every RPC keeps failing. Drop the service and
        mark the stored session unauthorized (clearing the dead session blob so a restart
        won't retry it) so ``status()`` reports ``unauthorized`` and the UI prompts a fresh
        login. The phone is kept to pre-fill the login form. Best-effort disconnect of the
        old client so it stops its background reconnect loop.
        """
        log.warning('telegram session invalidated; demoting to unauthorized (re-login required)')
        old, self.service = self.service, None
        self._pending_code_hash = None
        self._awaiting_2fa = False
        self._dialogs_cache = None
        self._dialogs_cache_at = 0.0
        row = db.get_tg_session()
        db.save_tg_session(row.phone if row else self._pending_phone, None, authorized=False)
        if old is not None:
            try:
                await old.disconnect()
            except Exception:
                log.exception('disconnect of demoted session failed')

    def _channel_handle(self, channel_id: int) -> str | int:
        """Prefer ``@username`` over a raw id for Telethon's ``get_entity``.

        Telethon needs an access_hash to resolve a bare int, which it only has
        if it has interacted with that peer in the current session — flaky after
        a fresh login (e.g., after wiping ``condenser.db``). A public username
        resolves reliably via the resolveUsername API. Falls back to the int for
        private channels (no username) — same behaviour as before.
        """
        channel = tdb.get_channel(channel_id)
        if channel is not None and channel.username:
            return f'@{channel.username}'
        return channel_id

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
        """Pull the recent-days window for one channel; returns the number of rows ingested.

        Marks the subscription as backfilled even on failure so the UI doesn't
        get stuck on "backfilling…" — the run is over either way. Users can hit
        "更新数据" / "重置数据" to retry.
        """
        service = self._require_service()
        ids: list[int] = []
        handle = self._channel_handle(channel_id)
        since_days = db.effective_backfill_days(self.settings.condenser_backfill_days)
        try:
            async for dm in service.backfill(handle, since_days=since_days):
                ids.extend(dm.raw_message_ids or [dm.id])
        except Exception as e:
            if self._is_auth_error(e):
                await self._demote_session()
                return 0
            log.exception('backfill failed for channel %s', channel_id)
            return 0
        finally:
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
        handle = self._channel_handle(channel_id)
        ids: list[int] = []
        try:
            async for dm in service.backfill(handle, offset_id=oldest, max_messages=count, persist=True):
                ids.extend(dm.raw_message_ids or [dm.id])
        except Exception as e:
            if self._is_auth_error(e):
                await self._demote_session()
                return 0
            log.exception('fetch-older failed for channel %s', channel_id)
            return 0
        if ids:
            filters.recompute_messages(channel_id, ids)
        return len(set(ids))

    async def reset_channel(self, channel_id: int) -> dict:
        """Destructive: wipe a channel's cached messages + read state, then re-sync from scratch.

        Clears messages, comments, and read markers (saved records + keyword filters survive),
        resets the sync watermark, then re-runs the recent-window backfill. Returns
        ``{'deleted': N, 'fetched': M}``.
        """
        self._require_service()
        deleted = db.delete_channel_messages(channel_id)
        tdb.update_channel_sync_status(channel_id, 0)
        db.set_backfill_done(channel_id, False)
        fetched = await self._backfill_channel(channel_id)
        return {'deleted': deleted, 'fetched': fetched}

    # ---- message actions (live Telegram reads/writes, used by routers) ----
    async def get_message_stats(self, channel_id: int, message_id: int) -> MessageStats:
        """Fetch a message's live views/forwards/reactions. Nothing is persisted."""
        service = self._require_service()
        try:
            message = await service.client.get_messages(self._channel_handle(channel_id), ids=message_id)
        except UnauthorizedError:  # session died mid-call — demote, then surface as 503
            await self._demote_session()
            raise
        if message is None:
            raise TelegramMessageNotFound(f'message {channel_id}/{message_id} not found')
        return MessageStats(
            views=getattr(message, 'views', None),
            forwards=getattr(message, 'forwards', None),
            reactions=_convert_reactions(getattr(message, 'reactions', None)),
        )

    async def forward_message(self, channel_id: int, message_id: int, comment: Optional[str] = None) -> dict:
        """Republish a message to the configured target channel.

        With a comment: a *new* message ``comment\\n\\n<t.me link>`` (Telegram renders the link
        as a quote card). Without one: a native ``forward_messages`` keeping the "Forwarded
        from" header. Returns the mode plus the t.me link of the message that just landed.
        """
        service = self._require_service()
        configured = db.get_meta('forward_channel')
        if not configured:
            raise LookupError('forward target channel not configured')
        target = _normalize_target(configured)
        comment = (comment or '').strip()
        try:
            if comment:
                text = f'{comment}\n\n{channel_message_url(channel_id, message_id)}'
                sent = await service.client.send_message(target, text)
                mode = 'quote'
            else:
                sent = await service.client.forward_messages(
                    target, message_id, from_peer=self._channel_handle(channel_id)
                )
                mode = 'forward'
        except MessageIdInvalidError:  # the source message is gone
            raise TelegramMessageNotFound(f'message {channel_id}/{message_id} not found')
        except UnauthorizedError:
            await self._demote_session()
            raise
        # forward_messages may hand back a list when Telethon batches; the id we want is the first
        sent_id = sent[0].id if isinstance(sent, list) else sent.id
        return {'status': 'ok', 'mode': mode, 'link': _sent_message_url(target, sent_id)}

    # ---- subscription orchestration (used by routers) ----
    def _register_subscription(self, info: ChannelInfo) -> ChannelInfo:
        """Persist channel + subscription row + spawn backfill for an already-resolved channel.

        Does NOT refresh the realtime listener — callers refresh once after a batch.
        """
        tdb.get_or_create_channel(info)
        db.add_subscription(info.id)
        self._spawn(self._backfill_channel(info.id))
        self._spawn(self._enrich_channel(info))
        return info

    async def _enrich_channel(self, info: ChannelInfo) -> None:
        """Fill member_count/description, which a plain ``resolve_channel`` doesn't carry.

        ``resolve_channel`` uses ``get_entity``, whose result lacks the full-chat stats — so
        the subscription list shows no member count. Fetch them once via ``GetFullChannelRequest``
        and persist through telememo's own writer (``get_or_create_channel`` updates the native
        title/username/description/member_count columns), preserving the rest of ``info``.
        Best-effort + auth-aware: a failure just leaves the basic info in place.
        """
        if self.service is None:
            return
        handle = self._channel_handle(info.id)
        try:
            entity = await self.service.client.get_entity(handle)
            full = await self.service.client(GetFullChannelRequest(entity))
        except Exception as e:  # noqa: BLE001 — background enrichment must never crash a subscribe
            if self._is_auth_error(e):
                await self._demote_session()
                return
            log.exception('full-channel enrich failed for %s', info.id)
            return
        about = getattr(full.full_chat, 'about', None)
        participants = getattr(full.full_chat, 'participants_count', None)
        if about:
            info.description = about
        if participants is not None:
            info.member_count = participants
        tdb.get_or_create_channel(info)

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
                except UnauthorizedError:  # session died mid-listing — demote, then surface
                    await self._demote_session()
                    raise

            self._dialogs_cache = sorted(found.values(), key=lambda c: c.last_message_date or _EPOCH, reverse=True)
            self._dialogs_cache_at = time.monotonic()  # stamp after the fetch, not before the back-off
            return self._dialogs_cache
