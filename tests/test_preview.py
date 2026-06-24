"""Behavior tests for the link-preview backend (condenser/preview.py + router).

Network is fully mocked: helpers are tested directly, and the fetch/cache/endpoint
behavior is exercised by monkeypatching the single network seam ``_fetch_capped``.
"""

from fastapi.testclient import TestClient

from condenser import db, preview
from condenser.app import create_app
from tests.conftest import md, seed_channel, seed_messages

SAMPLE_HTML = """
<html><head>
<title>Plain Title</title>
<meta property="og:title" content="OG Title">
<meta property="og:description" content="OG description">
<meta property="og:image" content="/cover.png">
<meta property="og:site_name" content="Example Site">
<link rel="canonical" href="https://example.com/article">
</head><body><h1>hi</h1></body></html>
"""


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _capped(body: bytes, ctype: str = 'text/html; charset=utf-8'):
    """Build a fake ``_fetch_capped`` that returns canned content, honoring ``accept``."""

    async def _impl(url, settings, *, cap, accept):
        if not accept(ctype):
            raise preview.PreviewError(f'unsupported content-type: {ctype}')
        return url, ctype, body[:cap]

    return _impl


# --- pure helpers -----------------------------------------------------------


def test_extract_urls_dedupes_and_strips_trailing_punctuation():
    text = 'see https://a.com/x. and https://a.com/x again, plus www.b.org!'
    assert preview.extract_urls(text) == ['https://a.com/x', 'https://www.b.org']


def test_normalize_url_canonicalizes_for_cache_key():
    assert preview.normalize_url('HTTPS://Example.com/a/?b=2&a=1#frag') == 'https://example.com/a?a=1&b=2'
    assert preview.normalize_url('https://example.com') == 'https://example.com/'


def test_parse_metadata_prefers_opengraph_and_resolves_image():
    meta = preview._parse_metadata('https://example.com/page', SAMPLE_HTML)
    assert meta['title'] == 'OG Title'
    assert meta['description'] == 'OG description'
    assert meta['site_name'] == 'Example Site'
    assert meta['image'] == 'https://example.com/cover.png'
    assert meta['canonical'] == 'https://example.com/article'


# --- single-URL endpoint ----------------------------------------------------


def test_preview_requires_auth(env):
    with _client() as client:
        assert client.get('/api/preview', params={'url': 'https://x.com'}).status_code == 401


def test_preview_rejects_non_http_scheme(env):
    with _client() as client:
        _login(client)
        assert client.get('/api/preview', params={'url': 'ftp://x.com'}).status_code == 400


def test_preview_fetches_then_serves_from_cache(env, monkeypatch):
    calls = {'n': 0}

    async def fake(url, settings, *, cap, accept):
        calls['n'] += 1
        return url, 'text/html', SAMPLE_HTML.encode()

    monkeypatch.setattr(preview, '_fetch_capped', fake)
    with _client() as client:
        _login(client)
        data = client.get('/api/preview', params={'url': 'https://example.com/page'}).json()
        assert data['title'] == 'OG Title'
        assert data['image'] == 'https://example.com/cover.png'
        assert data['source'] == 'fetched'
        # A normalized-equivalent URL is a cache hit -> no second fetch.
        client.get('/api/preview', params={'url': 'https://example.com/page/'})
        assert calls['n'] == 1


def test_preview_failure_returns_error_and_negative_caches(env, monkeypatch):
    calls = {'n': 0}

    async def boom(url, settings, *, cap, accept):
        calls['n'] += 1
        raise preview.PreviewError('not html')

    monkeypatch.setattr(preview, '_fetch_capped', boom)
    with _client() as client:
        _login(client)
        r = client.get('/api/preview', params={'url': 'https://bad.com'})
        assert r.status_code == 200
        assert r.json()['error'] == 'not html'
        client.get('/api/preview', params={'url': 'https://bad.com'})
        assert calls['n'] == 1  # failure was cached


# --- per-message batch ------------------------------------------------------


def test_message_previews_dedupe_and_telegram_image_bonus(env, monkeypatch):
    from telememo.types import WebPagePreview

    # Our fetch yields a title/description but no image.
    html = (
        '<html><head><meta property="og:title" content="Fetched">'
        '<meta property="og:description" content="our desc"></head></html>'
    )
    monkeypatch.setattr(preview, '_fetch_capped', _capped(html.encode()))
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages(
            [
                md(
                    1,
                    10,
                    1,
                    text='look https://example.com/a and https://example.com/a again',
                    media_type='webpage',
                    has_media=True,
                    webpage=WebPagePreview(
                        url='https://example.com/a', title='TG', description='tgdesc', has_photo=True
                    ),
                ),
            ]
        )
        items = client.get('/api/messages/1/10/previews').json()
        assert len(items) == 1  # text URL + webpage URL collapse to one
        assert items[0]['title'] == 'Fetched'  # our fetch wins
        assert items[0]['tg_image_message_id'] == 10  # bonus: offer Telegram's image


def test_message_previews_telegram_fallback_when_fetch_fails(env, monkeypatch):
    from telememo.types import WebPagePreview

    async def boom(url, settings, *, cap, accept):
        raise preview.PreviewError('unreachable')

    monkeypatch.setattr(preview, '_fetch_capped', boom)
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages(
            [
                md(
                    1,
                    11,
                    2,
                    text='https://down.example.com',
                    media_type='webpage',
                    has_media=True,
                    webpage=WebPagePreview(url='https://down.example.com', title='TG Title', description='from tg'),
                ),
            ]
        )
        items = client.get('/api/messages/1/11/previews').json()
        assert len(items) == 1
        assert items[0]['source'] == 'telegram'
        assert items[0]['title'] == 'TG Title'
        assert items[0]['error'] is None


def test_message_previews_404_when_missing(env):
    with _client() as client:
        _login(client)
        assert client.get('/api/messages/1/999/previews').status_code == 404


# --- image proxy ------------------------------------------------------------


def test_image_proxy_streams_bytes(env, monkeypatch):
    monkeypatch.setattr(preview, '_fetch_capped', _capped(b'\x89PNG-bytes', 'image/png'))
    with _client() as client:
        _login(client)
        r = client.get('/api/preview/image', params={'url': 'https://cdn.example.com/x.png'})
        assert r.status_code == 200
        assert r.headers['content-type'] == 'image/png'
        assert r.content == b'\x89PNG-bytes'


def test_image_proxy_rejects_non_image(env, monkeypatch):
    monkeypatch.setattr(preview, '_fetch_capped', _capped(b'<html>', 'text/html'))
    with _client() as client:
        _login(client)
        assert client.get('/api/preview/image', params={'url': 'https://x.com/p'}).status_code == 502
