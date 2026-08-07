"""Daily-cleanup status.

Observability only — the mechanism runs without it. It exists because at a
15-day retention window the first weeks legitimately delete nothing, so
"never ran" and "ran and found nothing" are indistinguishable from the logs.
"""

from fastapi import APIRouter, Depends, Request

from ..auth import require_auth
from ..cleanup import CleanupManager

router = APIRouter(prefix='/api', tags=['cleanup'], dependencies=[Depends(require_auth)])


def get_cleanup(request: Request) -> CleanupManager:
    """Dependency: the process-wide CleanupManager from app state."""
    return request.app.state.cleanup


@router.get('/cleanup/status')
def cleanup_status(cleanup: CleanupManager = Depends(get_cleanup)):
    return cleanup.status()
