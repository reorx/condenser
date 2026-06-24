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
    }


@router.patch('/meta')
def patch_app_meta(body: AppMetaPatch):
    """Override runtime settings without a restart. Currently: backfill_days (positive int)."""
    if body.backfill_days is not None:
        if body.backfill_days <= 0:
            raise HTTPException(status_code=422, detail='backfill_days must be positive')
        db.set_meta('backfill_days', str(body.backfill_days))
    return get_app_meta()
