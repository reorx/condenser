"""FastAPI application factory + lifecycle wiring (spec C1)."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db
from .config import get_settings
from .routers import auth, channels, media, reading, subscriptions, tg
from .tg import TgManager

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 1. connect SQLite + build/migrate tables
        db.init_db(settings.condenser_db_path)
        # 2-3. reconnect stored TG session, resume listening + backfill
        app.state.tg = TgManager(settings)
        await app.state.tg.startup()
        yield
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
    app.include_router(channels.router)

    # 4. serve the React build (if present) as static assets at '/'
    static_dir = os.getenv('CONDENSER_STATIC_DIR', str(Path(__file__).resolve().parent.parent / 'frontend' / 'dist'))
    if Path(static_dir).is_dir():
        app.mount('/', StaticFiles(directory=static_dir, html=True), name='static')

    return app
