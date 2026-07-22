"""Runtime app settings backed by app_meta (spec B2 — app_meta wiring)."""

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..auth import require_auth
from ..config import get_settings
from ..types import AppMetaPatch

router = APIRouter(prefix='/api/app', tags=['settings'], dependencies=[Depends(require_auth)])


@router.get('/meta')
def get_app_meta():
    """Current app-level settings: schema version (read-only) + effective backfill window."""
    settings = get_settings()
    return {
        'schema_version': int(db.get_meta('schema_version') or db.SCHEMA_VERSION),
        'backfill_days': db.effective_backfill_days(settings.condenser_backfill_days),
        # unset/cleared reads back as null, never ''
        'forward_channel': db.get_meta('forward_channel') or None,
    }


@router.patch('/meta')
def patch_app_meta(body: AppMetaPatch):
    """Override runtime settings without a restart: backfill_days (positive int), forward_channel."""
    if body.backfill_days is not None:
        if body.backfill_days <= 0:
            raise HTTPException(status_code=422, detail='backfill_days must be positive')
        db.set_meta('backfill_days', str(body.backfill_days))
    if body.forward_channel is not None:
        db.set_meta('forward_channel', body.forward_channel.strip())
    return get_app_meta()
