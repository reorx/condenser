"""FastAPI application factory + lifecycle wiring (spec C1)."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db
from .cleanup import CleanupManager
from .config import get_settings
from .hn import HNManager
from .logconf import configure_logging
from .routers import (
    auth,
    channels,
    cleanup,
    hn,
    media,
    messages,
    preview,
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

    # 4. serve the React build (if present) as static assets at '/'
    static_dir = os.getenv('CONDENSER_STATIC_DIR', str(Path(__file__).resolve().parent.parent / 'frontend' / 'dist'))
    if Path(static_dir).is_dir():
        app.mount('/', SPAStaticFiles(directory=static_dir, html=True), name='static')

    return app
