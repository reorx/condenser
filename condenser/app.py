"""FastAPI application factory + lifecycle wiring (spec C1)."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware, GZipResponder, IdentityResponder
from starlette.types import Message, Receive, Scope, Send

from . import db
from .cleanup import CleanupManager
from .config import get_settings
from .hn import HNManager
from .logconf import configure_logging
from .routers import (
    auth,
    channels,
    cleanup,
    forwards,
    hn,
    media,
    messages,
    preview,
    purifier,
    reading,
    rss,
    search,
    settings as settings_router,
    sources,
    subscriptions,
    tg,
    x,
)
from .rss import RssManager
from .tg import TgManager
from .verdict import VerdictManager

configure_logging()


class SPAStaticFiles(StaticFiles):
    """StaticFiles with an index.html fallback for client-side routes.

    ``html=True`` only serves index.html for directory requests; cold-loading a
    React Router path (/authorize, /saved, ...) must return the SPA shell instead
    of 404. Unmatched /api paths keep 404ing — this mount sits after the routers,
    so anything reaching it under /api is a genuinely unknown endpoint.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith('api/'):
                return await super().get_response('index.html', scope)
            raise


# Bodies that are already compressed (or that Safari streams and seeks in): gzipping
# them costs event-loop CPU (measured ~14ms/MB on a 3MB JPEG, review 2026-09-07 #8)
# and saves nothing. Starlette's middleware only excludes text/event-stream.
_UNCOMPRESSED_PREFIXES = ('image/', 'video/', 'audio/', 'font/')
_UNCOMPRESSED_TYPES = frozenset(
    {
        'application/font-woff',
        'application/font-woff2',
        'application/x-font-woff',
        'application/x-font-ttf',
        'application/x-font-otf',
        'application/font-sfnt',
        'application/vnd.ms-fontobject',
        'application/zip',
        'application/gzip',
        'application/pdf',
        'application/octet-stream',
    }
)


def already_compressed(content_type: str) -> bool:
    mime = content_type.split(';')[0].strip().lower()
    return mime.startswith(_UNCOMPRESSED_PREFIXES) or mime in _UNCOMPRESSED_TYPES


class _SelectiveGZipResponder(GZipResponder):
    async def send_with_compression(self, message: Message) -> None:
        # The parent only records the start message (nothing is sent until the first
        # body chunk), so the exclusion flag can be widened right after it.
        await super().send_with_compression(message)
        if message['type'] == 'http.response.start':
            if already_compressed(Headers(raw=message['headers']).get('content-type', '')):
                self.content_type_is_excluded = True


class SelectiveGZipMiddleware(GZipMiddleware):
    """``GZipMiddleware`` that passes image / media / font bodies through as identity.
    Every proxied byte the iOS app scrolls past (Telegram media, avatars, /pa images)
    shares the loop with Telethon ingest; HTML and JSON still compress."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':  # pragma: no cover
            await self.app(scope, receive, send)
            return
        responder: IdentityResponder
        if 'gzip' in Headers(scope=scope).get('Accept-Encoding', ''):
            responder = _SelectiveGZipResponder(self.app, self.minimum_size, compresslevel=self.compresslevel)
        else:
            responder = IdentityResponder(self.app, self.minimum_size)
        await responder(scope, receive, send)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 1. connect SQLite + build/migrate tables (+ the sqlite-vec KNN index)
        db.init_db(settings.condenser_db_path, settings.condenser_embedding_dimensions)
        # 2-3. reconnect stored TG session, resume listening + backfill
        app.state.tg = TgManager(settings)
        await app.state.tg.startup()
        # hn sampling loop (no-ops until an hn subscription exists)
        app.state.hn = HNManager(settings)
        await app.state.hn.startup()
        # rss polling loop (no-ops until an rss subscription exists; ships disabled)
        app.state.rss = RssManager(settings)
        await app.state.rss.startup()
        # For You verdicts; inert until labels exist (and until an embedding key does)
        app.state.verdict = VerdictManager(settings)
        await app.state.verdict.startup()
        # daily retention sweep; the cadence lives in app_meta, not in the loop
        app.state.cleanup = CleanupManager(settings)
        await app.state.cleanup.startup()
        yield
        await app.state.cleanup.shutdown()
        await app.state.verdict.shutdown()
        await app.state.rss.shutdown()
        await app.state.hn.shutdown()
        await app.state.tg.shutdown()
        db.close_db()

    app = FastAPI(title='Condenser', version='0.1.0', lifespan=lifespan)
    # Production Caddy has no `encode` block (compression was Cloudflare's job alone);
    # the purifier's proxy pages are up to 1MB of HTML on a bad connection, so the
    # app compresses itself. Global: API JSON benefits too; binary proxies are skipped.
    # Level 6, not the default 9: the last three levels cost CPU for ~1% of size.
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=1024, compresslevel=6)

    @app.get('/api/health')
    def health():
        return {'ok': True}

    app.include_router(auth.router)
    app.include_router(tg.router)
    app.include_router(subscriptions.router)
    app.include_router(reading.router)
    app.include_router(media.router)
    app.include_router(messages.router)
    app.include_router(channels.router)
    app.include_router(preview.router)
    app.include_router(settings_router.router)
    app.include_router(hn.router)
    app.include_router(x.router)
    app.include_router(rss.router)
    app.include_router(sources.router)
    app.include_router(cleanup.router)
    app.include_router(search.router)
    app.include_router(forwards.router)
    # /p + /pa + /api/purifier/ticket — before the SPA mount, which would swallow /p
    app.include_router(purifier.api_router)
    app.include_router(purifier.router)

    # 4. serve the React build (if present) as static assets at '/'
    static_dir = os.getenv('CONDENSER_STATIC_DIR', str(Path(__file__).resolve().parent.parent / 'frontend' / 'dist'))
    if Path(static_dir).is_dir():
        app.mount('/', SPAStaticFiles(directory=static_dir, html=True), name='static')

    return app
