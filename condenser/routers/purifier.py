"""The Purifier's endpoints (plan 2026-09-07 §1-2): ``/p`` documents, ``/pa`` assets,
and the ticket exchange under ``/api/purifier``.

Auth is the odd one out here. ``/p`` and ``/pa`` are opened by a browser navigation
and by ``<img>`` / ``<link>`` requests, which carry no Bearer header — so they accept
only the reader cookie (minted from a one-shot ticket the iOS app fetched with its
device token) or the app session cookie, and a failure is a small HTML page, not
JSON. Each handler is one broad-catch boundary: the module raises typed errors,
this file maps them to 400 / 401 / 415 / 502 pages that always carry the original link.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from .. import purifier, purifier_html
from ..auth import READER_COOKIE_MAX_AGE, READER_COOKIE_NAME, reader_authenticated, require_auth
from ..config import Settings, get_settings
from ..crypto import PURIFIER_TICKET_MAX_AGE, sign_purifier_ticket, sign_reader_cookie, verify_purifier_ticket

logger = logging.getLogger(__name__)

router = APIRouter(tags=['purifier'])
api_router = APIRouter(prefix='/api/purifier', tags=['purifier'], dependencies=[Depends(require_auth)])

# Injection seams (tests replace these; production never does).
_fetch_page = purifier.fetch_page
_fetch_puremd = purifier.fetch_puremd

# Only sent when scripts are allowed to survive: they may run, but not talk back.
_ALLOW_JS_CSP = (
    "default-src * data: blob: 'unsafe-inline' 'unsafe-eval'; "
    "connect-src 'none'; frame-src 'none'; form-action 'self'; base-uri 'self'"
)


@api_router.get('/ticket')
def purifier_ticket(settings: Settings = Depends(get_settings)) -> dict:
    """A 5-minute ticket the client appends as ``_pt=`` to its first /p URL."""
    return {'ticket': sign_purifier_ticket(settings.condenser_secret_key), 'ttl': PURIFIER_TICKET_MAX_AGE}


def _raw_path(request: Request) -> str:
    raw = request.scope.get('raw_path')
    return raw.decode('utf-8', errors='replace') if raw else request.url.path


def _own_hosts(request: Request) -> set[str]:
    return {request.url.netloc.lower(), (request.url.hostname or '').lower()}


def _own_origin(request: Request) -> str:
    return f'{request.url.scheme}://{request.url.netloc}'


def _is_https(request: Request) -> bool:
    return request.url.scheme == 'https' or request.headers.get('x-forwarded-proto', '').lower() == 'https'


def _target(request: Request, prefix: str) -> purifier.Target:
    host, path = purifier.split_raw_path(_raw_path(request), prefix)
    return purifier.parse_target(host, path, request.url.query, own_hosts=_own_hosts(request))


def _bad_target(request: Request, exc: Exception) -> HTMLResponse:
    guess = 'https://' + _raw_path(request).split('/', 2)[-1]
    return HTMLResponse(purifier_html.error_page('无法代理这个地址', str(exc), guess), status_code=400)


@router.get('/p/{host}/{path:path}')
@router.get('/p/{host}')
async def purified_document(request: Request, host: str, settings: Settings = Depends(get_settings)):
    try:
        target = _target(request, '/p/')
    except purifier.BadTargetError as exc:
        return _bad_target(request, exc)

    if target.ticket and verify_purifier_ticket(settings.condenser_secret_key, target.ticket):
        return _exchange_ticket(request, settings)
    if not reader_authenticated(request, settings):
        return HTMLResponse(purifier_html.unauthorized_page(target.url), status_code=401)

    full_page_url = target.own_path('p', '_mode=proxy')
    try:
        result = await purifier.render_document(
            target, settings, own_origin=_own_origin(request), fetch_page=_fetch_page, fetch_puremd=_fetch_puremd
        )
    except (purifier.PurifierError, httpx.HTTPError) as exc:
        logger.info('purifier failed %s: %s', target.url, exc)
        page = purifier_html.error_page('无法获取这个页面', f'{exc}', target.url, full_page_url)
        return HTMLResponse(page, status_code=502)
    logger.info('purifier %s %s', result.mode, target.url)
    headers = {'Cache-Control': 'private, max-age=60'}
    if settings.condenser_purifier_allow_js:
        headers['Content-Security-Policy'] = _ALLOW_JS_CSP
    return HTMLResponse(result.html, headers=headers)


def _exchange_ticket(request: Request, settings: Settings) -> RedirectResponse:
    """A valid ticket → the reader cookie + a 302 to the same URL minus ``_pt`` only."""
    query, _ = purifier.strip_params(request.url.query, ('_pt',))
    location = _raw_path(request) + (f'?{query}' if query else '')
    response = RedirectResponse(location, status_code=302)
    response.set_cookie(
        READER_COOKIE_NAME,
        sign_reader_cookie(settings.condenser_secret_key),
        max_age=READER_COOKIE_MAX_AGE,
        httponly=True,
        samesite='lax',
        secure=_is_https(request),
        path='/',
    )
    return response


@router.get('/pa/{host}/{path:path}')
async def purified_asset(request: Request, host: str, settings: Settings = Depends(get_settings)):
    try:
        target = _target(request, '/pa/')
    except purifier.BadTargetError as exc:
        return PlainTextResponse(str(exc), status_code=400)
    if not reader_authenticated(request, settings):
        return HTMLResponse(purifier_html.unauthorized_page(target.url), status_code=401)
    try:
        asset = await purifier.render_asset(target, settings, own_origin=_own_origin(request), fetch_page=_fetch_page)
    except purifier.UnsupportedAssetError as exc:
        return PlainTextResponse(str(exc), status_code=415)
    except (purifier.PurifierError, httpx.HTTPError) as exc:
        return PlainTextResponse(f'could not fetch asset: {exc}', status_code=502)
    return Response(
        content=asset.body,
        media_type=asset.content_type,
        headers={'Cache-Control': f'private, max-age={settings.condenser_purifier_asset_cache_seconds}'},
    )
