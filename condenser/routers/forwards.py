"""Forward records: the log of what the reader republished (plan 2026-08-23).

Read-only plus a delete. There is no POST here — a record is created by the act
of forwarding (``POST /api/forward`` in ``messages.py``), never on its own, so an
endpoint that wrote one would be a way to claim a message that was never sent.

``DELETE`` removes the local record and nothing else: the message stays in the
target channel. That is a product decision, not a limitation — the record is a
note to self about a publish, and unpublishing is a separate act that this
release does not offer. The web dialog says so in as many words.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db, forwards
from ..auth import require_auth

router = APIRouter(prefix='/api', tags=['forwards'], dependencies=[Depends(require_auth)])


@router.get('/forwards')
def get_forwards(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict:
    """One page of ``{record, item}`` entries, newest first."""
    return forwards.list_rendered(limit=limit, offset=offset)


@router.delete('/forwards/{record_id}')
def delete_forward(record_id: int) -> dict:
    """Forget one publish locally. The Telegram message is not touched."""
    if not db.delete_forward_record(record_id):
        raise HTTPException(status_code=404, detail='forward record not found')
    return {'ok': True}
