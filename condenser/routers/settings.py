"""Runtime app settings backed by app_meta (spec B2 — app_meta wiring)."""

import json
import re

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
        # unset and cleared are the same state: an empty whitelist filters nothing
        'languages': db.get_languages(),
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
    if body.languages is not None:
        codes = []
        for code in body.languages:
            code = code.strip().lower()
            # primary subtags only ('zh', not 'zh-cn') — the filter matches on them
            if not re.fullmatch(r'[a-z]{2,3}', code):
                raise HTTPException(status_code=422, detail=f'invalid language code: {code!r}')
            if code not in codes:
                codes.append(code)
        db.set_meta('languages', json.dumps(codes))
    return get_app_meta()
