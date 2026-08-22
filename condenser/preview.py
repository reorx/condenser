"""Source-agnostic URL link-preview service.

Given a URL, fetch the page ourselves and extract unified preview metadata
(OpenGraph / Twitter Card / Dublin Core / meta / page) via ``metadata_parser``.
Telegram's own ``WebPagePreview`` is treated as a *bonus* seed, never the
standard — so future feed types (RSS, Twitter) can reuse the same ``LinkPreview``
shape. Results are cached in the condenser-owned ``link_previews`` table.

Concurrency: fetching is async (httpx) so it never blocks the shared Telethon
event loop; HTML parsing (CPU-bound) is dispatched to a worker thread.

Note: this is a single-user self-hosted app, so the proxy intentionally fetches
whatever URL it's given (no SSRF/private-IP guard). If this is ever exposed to
untrusted multi-tenant use, add a transport-level peer-IP check before connecting.
"""

import os

# metadata_parser reads this at import time; disable tldextract's network fetch of
# the public-suffix list so importing/using the library never blocks on the network.
os.environ.setdefault('METADATA_PARSER__DISABLE_TLDEXTRACT', '1')

import asyncio  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Callable, Literal, Optional  # noqa: E402
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit  # noqa: E402

import httpx  # noqa: E402
import metadata_parser  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import db, records  # noqa: E402
from .config import Settings, get_settings  # noqa: E402

# metadata_parser parses with lxml (a declared dependency here — it doesn't declare
# it itself). When lxml is missing it logs an ERROR *per parse* on the logger
# `metdata_parser` (upstream's typo) and falls back to the slower html.parser — a
# name-based suppression once lived here but aimed at the correctly-spelled name,
# so it never worked. Deliberately NOT muted now: with lxml installed the message
# can only mean the environment is genuinely broken, and we want to see that.

# Mirror of the frontend URL regex (lib/linkify.tsx) so extraction agrees on both sides.
_URL_RE = re.compile(r'(https?://[^\s<]+|www\.[^\s<]+)', re.I)
_TRAILING = re.compile(r"""[.,;:!?)\]}'"]+$""")
# Prefer OpenGraph/Twitter card data over the bare page <title>/meta for previews.
_STRATEGY = ['og', 'twitter', 'dc', 'meta', 'page']


class LinkPreview(BaseModel):
    """Unified preview for a single URL (source-agnostic).

    ``source`` records provenance: ``fetched`` = scraped by us; ``telegram`` = we
    fell back to Telegram's bonus preview because our fetch yielded nothing.
    ``tg_image_message_id``, when set, tells the frontend it can load the image
    for free via the existing media proxy for that Telegram message.
    """

    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    site_name: Optional[str] = None
    source: Literal['fetched', 'telegram'] = 'fetched'
    tg_image_message_id: Optional[int] = None
    error: Optional[str] = None


class PreviewError(Exception):
    """An expected, non-exceptional fetch failure (bad scheme, blocked host, non-HTML)."""


# --- URL helpers ------------------------------------------------------------


# Params that only tag the click, never the content. Kept to an explicit safelist —
# stripping unknown params risks conflating genuinely different pages.
_TRACKING_PARAMS = frozenset(('fbclid', 'gclid', 'igshid'))


def normalize_url(url: str) -> str:
    """Canonicalize for use as a stable cache key (lowercase scheme/host, sorted
    query minus tracking params, no fragment, no trailing slash except root)."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or 'https').lower()
    netloc = parts.netloc.lower()
    path = parts.path or '/'
    if path != '/' and path.endswith('/'):
        path = path.rstrip('/')
    pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith('utm_') or k.lower() in _TRACKING_PARAMS)
    ]
    query = urlencode(sorted(pairs))
    return urlunsplit((scheme, netloc, path, query, ''))


def extract_urls(text: Optional[str]) -> list[str]:
    """URLs found in message text, de-duplicated by normalized form, order preserved."""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _URL_RE.finditer(text):
        url = _TRAILING.sub('', m.group(0))
        if url.lower().startswith('www.'):
            url = 'https://' + url
        key = normalize_url(url)
        if key not in seen:
            seen.add(key)
            out.append(url)
    return out


# --- capped fetch -----------------------------------------------------------


async def _fetch_capped(
    url: str, settings: Settings, *, cap: int, accept: Callable[[str], bool]
) -> tuple[str, str, bytes]:
    """Fetch ``url`` (httpx follows redirects), enforcing a content-type guard + byte cap.

    Returns ``(final_url, content_type, body_bytes)``. Raises ``PreviewError`` when the
    content type isn't accepted; httpx errors (timeout, status, too-many-redirects)
    propagate to the caller.
    """
    headers = {'User-Agent': settings.condenser_preview_user_agent}
    async with httpx.AsyncClient(
        headers=headers,
        timeout=settings.condenser_preview_fetch_timeout,
        follow_redirects=True,
        max_redirects=settings.condenser_preview_max_redirects,
    ) as client:
        async with client.stream('GET', url) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get('content-type', '')
            if not accept(ctype):
                raise PreviewError(f'unsupported content-type: {ctype or "unknown"}')
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) >= cap:
                    break
            return str(resp.url), ctype, bytes(body[:cap])


# --- metadata extraction (sync; runs in a worker thread) --------------------


def _parse_metadata(url: str, html: str) -> dict:
    """Extract unified preview fields from HTML. CPU-bound; call via ``asyncio.to_thread``."""
    mp = metadata_parser.MetadataParser(url=url, html=html, search_head_only=False)
    pr = mp.parsed_result
    return {
        'canonical': mp.get_discrete_url() or url,
        'title': pr.select_first_match('title', strategy=_STRATEGY),
        'description': pr.select_first_match('description', strategy=_STRATEGY),
        'site_name': pr.select_first_match('site_name', strategy=['og', 'meta']),
        'image': mp.get_metadata_link('image'),
    }


# --- fetch + cache orchestration --------------------------------------------


async def fetch_preview(url: str) -> LinkPreview:
    """Fetch and parse a single URL into a LinkPreview (no cache). Raises on failure."""
    settings = get_settings()
    final_url, _ctype, raw = await _fetch_capped(
        url, settings, cap=settings.condenser_preview_max_bytes, accept=lambda c: 'html' in c.lower()
    )
    html = raw.decode(_charset(raw, _ctype), errors='replace')
    meta = await asyncio.to_thread(_parse_metadata, final_url, html)
    return LinkPreview(
        url=meta['canonical'] or final_url,
        title=meta['title'],
        description=meta['description'],
        image=meta['image'],
        site_name=meta['site_name'],
    )


async def get_preview(url: str) -> LinkPreview:
    """Cached single-URL preview. Never raises — failures become ``LinkPreview(error=...)``.

    This is the orchestration boundary, so it is the one place we catch broadly
    (per the project's "handle errors only in top-level functions" convention):
    a failed fetch is an expected outcome we cache (negatively) and surface to the UI.
    """
    settings = get_settings()
    key = normalize_url(url)
    cached = db.get_cached_preview(key)
    if cached is not None and _cache_fresh(cached, settings):
        return _from_cache(url, cached)

    try:
        preview = await fetch_preview(url)
    except Exception as e:  # noqa: BLE001 - boundary: any failure is cached + shown
        message = _error_message(e)
        db.upsert_preview(key, ok=False, error=message)
        return LinkPreview(url=url, error=message)

    db.upsert_preview(
        key,
        ok=True,
        title=preview.title,
        description=preview.description,
        image=preview.image,
        site_name=preview.site_name,
        canonical_url=preview.url,
    )
    return preview


async def get_message_previews(channel_id: int, message_id: int) -> Optional[list[LinkPreview]]:
    """Previews for every URL in a message (album-aware), with the Telegram bonus applied.

    Returns ``None`` when the message is not in the cache (router → 404).
    """
    settings = get_settings()
    snapshot = records.build_snapshot(channel_id, message_id)
    if snapshot is None:
        return None

    urls: list[str] = []
    seen: set[str] = set()
    tg_by_key: dict[str, dict] = {}
    for row in snapshot['messages']:
        for url in extract_urls(row.get('text')):
            key = normalize_url(url)
            if key not in seen:
                seen.add(key)
                urls.append(url)
        webpage = row.get('webpage')
        webpage = json.loads(webpage) if isinstance(webpage, str) else webpage
        if webpage and webpage.get('url'):
            key = normalize_url(webpage['url'])
            tg_by_key[key] = {
                'title': webpage.get('title'),
                'description': webpage.get('description'),
                'site_name': webpage.get('site_name'),
                'has_photo': bool(webpage.get('has_photo')),
                'message_id': row['id'],
            }
            if key not in seen:
                seen.add(key)
                urls.append(webpage['url'])

    urls = urls[: settings.condenser_preview_max_urls]
    semaphore = asyncio.Semaphore(settings.condenser_preview_max_concurrency)

    async def _one(u: str) -> LinkPreview:
        async with semaphore:
            return await get_preview(u)

    previews = list(await asyncio.gather(*[_one(u) for u in urls]))
    for requested, preview in zip(urls, previews):
        _apply_telegram_bonus(preview, tg_by_key.get(normalize_url(requested)))
    return previews


def _apply_telegram_bonus(preview: LinkPreview, tg: Optional[dict]) -> None:
    """Use Telegram's preview as a bonus: fill gaps our fetch left, and offer its image."""
    if not tg:
        return
    if preview.error or not (preview.title or preview.description):
        if tg['title'] or tg['description']:
            preview.title = preview.title or tg['title']
            preview.description = preview.description or tg['description']
            preview.site_name = preview.site_name or tg['site_name']
            preview.source = 'telegram'
            preview.error = None
    if not preview.image and tg['has_photo']:
        preview.tg_image_message_id = tg['message_id']


async def fetch_image(url: str) -> tuple[bytes, str]:
    """Fetch an image URL through the SSRF-guarded, byte-capped path. Raises on failure."""
    settings = get_settings()
    _final, ctype, raw = await _fetch_capped(
        url,
        settings,
        cap=settings.condenser_preview_image_max_bytes,
        accept=lambda c: c.lower().startswith('image/'),
    )
    return raw, ctype.split(';')[0].strip()


# --- small helpers ----------------------------------------------------------


def _charset(raw: bytes, content_type: str) -> str:
    for part in content_type.split(';'):
        part = part.strip().lower()
        if part.startswith('charset='):
            return part[len('charset=') :].strip() or 'utf-8'
    return 'utf-8'


def _cache_fresh(row: 'db.LinkPreviewCache', settings: Settings) -> bool:
    ttl = settings.condenser_preview_cache_ttl if row.ok else settings.condenser_preview_neg_cache_ttl
    fetched = row.fetched_at
    if isinstance(fetched, str):
        fetched = datetime.fromisoformat(fetched)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - fetched).total_seconds() < ttl


def _from_cache(requested_url: str, row: 'db.LinkPreviewCache') -> LinkPreview:
    if not row.ok:
        return LinkPreview(url=requested_url, error=row.error or 'preview unavailable')
    return LinkPreview(
        url=row.canonical_url or requested_url,
        title=row.title,
        description=row.description,
        image=row.image,
        site_name=row.site_name,
    )


def _error_message(e: Exception) -> str:
    if isinstance(e, PreviewError):
        return str(e)
    if isinstance(e, httpx.HTTPStatusError):
        return f'HTTP {e.response.status_code}'
    if isinstance(e, httpx.TimeoutException):
        return 'request timed out'
    if isinstance(e, httpx.HTTPError):
        return 'could not reach the site'
    return type(e).__name__
