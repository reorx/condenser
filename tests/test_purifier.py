"""Behavior tests for the Purifier — the iOS reading proxy (condenser/purifier.py +
purifier_html.py + routers/purifier.py; plan kb/plans/2026-09-07-purifier.md).

Shape follows tests/test_preview.py: pure helpers → injected fetch seams → TestClient
behavior. No test touches the network: the document/asset fetch is injected through
``fetch_page`` / ``fetch_puremd``, and the scheme-retry test monkeypatches the one
transport seam (``preview._fetch_capped``).
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from condenser import crypto, preview, purifier
from condenser.app import create_app
from condenser.auth import COOKIE_NAME, READER_COOKIE_NAME

OWN = 'https://condenser.example'
BASE = 'https://blog.example/posts/hello/'


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _device_token(client):
    _login(client)
    token = client.post('/api/auth/device', json={'name': 'phone'}).json()['token']
    client.cookies.clear()
    return token


def _page(body: bytes, ctype: str = 'text/html; charset=utf-8', final_url: str | None = None):
    """An injectable ``fetch_page`` returning canned bytes (honoring ``accept`` like the real one)."""

    async def _impl(url, settings, *, cap, accept):
        if not accept(ctype):
            raise preview.PreviewError(f'unsupported content-type: {ctype}')
        return final_url or url, ctype, body[:cap]

    return _impl


ARTICLE = (
    '<html><head><title>Hello World</title></head><body>'
    '<nav><a href="/">home</a><a href="/about">about</a></nav>'
    '<article><h1>Hello World</h1>'
    + ''.join(
        f'<p>Paragraph {i} of a reasonably long article body that readability will keep. ' * 3 + '</p>'
        for i in range(12)
    )
    + '<p><img src="img/one.png" alt="one"> and <a href="../other">another post</a></p>'
    '</article><footer>© blog</footer></body></html>'
)

SHORT = '<html><head><title>Stub</title></head><body><article><p>Too short.</p></article></body></html>'


@pytest.fixture(autouse=True)
def _fresh_cache():
    purifier.clear_cache()
    yield
    purifier.clear_cache()


# --- crypto: three salts, none interchangeable ------------------------------


def test_purifier_signatures_are_not_interchangeable():
    key = 'secret'
    ticket = crypto.sign_purifier_ticket(key)
    reader = crypto.sign_reader_cookie(key)
    session = crypto.sign_cookie(key)
    assert crypto.verify_purifier_ticket(key, ticket)
    assert crypto.verify_reader_cookie(key, reader)
    assert crypto.verify_cookie(key, session)
    # cross-salt: every other combination fails
    assert not crypto.verify_purifier_ticket(key, reader)
    assert not crypto.verify_purifier_ticket(key, session)
    assert not crypto.verify_reader_cookie(key, ticket)
    assert not crypto.verify_reader_cookie(key, session)
    assert not crypto.verify_cookie(key, ticket)
    assert not crypto.verify_cookie(key, reader)
    # and a different secret fails too
    assert not crypto.verify_purifier_ticket('other', ticket)


def test_purifier_ticket_expires():
    key = 'secret'
    ticket = crypto.sign_purifier_ticket(key)
    assert crypto.verify_purifier_ticket(key, ticket, max_age=300)
    assert not crypto.verify_purifier_ticket(key, ticket, max_age=-1)


# --- URL helpers ------------------------------------------------------------


def test_parse_target_splits_host_path_query_and_strips_control_params():
    t = purifier.parse_target('News.YCombinator.com', '/item', 'id=1&_pt=abc&_mode=proxy&p=2')
    assert t.host == 'news.ycombinator.com'
    assert t.path == '/item'
    assert t.query == 'id=1&p=2'
    assert t.ticket == 'abc'
    assert t.mode_override == 'proxy'
    assert t.url == 'https://news.ycombinator.com/item?id=1&p=2'


def test_parse_target_keeps_raw_bytes_and_other_params_untouched():
    # %2F stays encoded, the original site's params keep their order and encoding
    t = purifier.parse_target('a.example', '/x%2Fy/z%20w', 'b=%2Fq&a=1%202&_pt=t')
    assert t.path == '/x%2Fy/z%20w'
    assert t.query == 'b=%2Fq&a=1%202'
    assert t.url == 'https://a.example/x%2Fy/z%20w?b=%2Fq&a=1%202'


def test_parse_target_control_params_at_every_position():
    assert purifier.parse_target('a.example', '', '_pt=t').query == ''
    assert purifier.parse_target('a.example', '', '_pt=t&x=1').query == 'x=1'
    assert purifier.parse_target('a.example', '', 'x=1&_pt=t').query == 'x=1'
    assert purifier.parse_target('a.example', '', 'x=1&_pt=t&y=2').query == 'x=1&y=2'
    # a site param that merely starts with the same letters is not ours
    assert purifier.parse_target('a.example', '', '_ptx=1&_mode_x=2').query == '_ptx=1&_mode_x=2'


def test_parse_target_empty_path_and_port_and_userinfo():
    t = purifier.parse_target('user:pw@Host.example:8080', '', '')
    assert t.host == 'host.example:8080'
    assert t.path == ''
    assert t.url == 'https://host.example:8080'


def test_parse_target_rejects_bad_hosts():
    for bad in ('localhost', 'LOCALHOST', '127.0.0.1', '[::1]', 'intranet', '10.0.0.1:8080', ''):
        with pytest.raises(purifier.BadTargetError):
            purifier.parse_target(bad, '/', '')
    with pytest.raises(purifier.BadTargetError):
        purifier.parse_target('condenser.example', '/p/x', '', own_hosts={'condenser.example'})


def test_host_allowed_rejects_non_canonical_loopback_spellings():
    """Review 2026-09-07 #3: ``127.1`` / ``0x7f.1`` / ``0177.0.0.1`` are not IP literals to
    ``ipaddress`` but resolve to 127.0.0.1 for the socket layer; a trailing dot slipped
    past the ``localhost`` compare. The server would have fetched itself."""
    for bad in ('127.1', '0x7f.1', '0177.0.0.1', '0x7f.0x0.0x0.0x1', 'localhost.', '127.0.0.1.', 'LOCALHOST.'):
        assert not purifier.host_allowed(bad), bad
        with pytest.raises(purifier.BadTargetError):
            purifier.parse_target(bad, '/', '')
    # a numeric label is fine as long as the name is not numeric all the way through
    for ok in ('a.example', '1password.com', '123.example', '0x.example', 'a.example:8080'):
        assert purifier.host_allowed(ok), ok


def test_parse_target_invalid_mode_override_is_ignored():
    assert purifier.parse_target('a.example', '', '_mode=puremd').mode_override is None
    assert purifier.parse_target('a.example', '', '_mode=readable').mode_override == 'readable'


def test_split_raw_path():
    assert purifier.split_raw_path('/p/news.ycombinator.com/item', '/p/') == ('news.ycombinator.com', '/item')
    assert purifier.split_raw_path('/p/a.example', '/p/') == ('a.example', '')
    assert purifier.split_raw_path('/p/a.example/', '/p/') == ('a.example', '/')
    assert purifier.split_raw_path('/pa/a.example/x%2Fy', '/pa/') == ('a.example', '/x%2Fy')


def test_rewrite_url_branches():
    rw = lambda href, kind='p': purifier.rewrite_url(href, BASE, OWN, kind)  # noqa: E731
    # ordinary link → /p ; relative resolved against base
    assert rw('https://a.example/x?y=1#frag') == '/p/a.example/x?y=1#frag'
    assert rw('../other') == '/p/blog.example/posts/other'
    assert rw('img/one.png', 'pa') == '/pa/blog.example/posts/hello/img/one.png'
    assert rw('//cdn.example/f.css', 'pa') == '/pa/cdn.example/f.css'
    # untouchable
    for raw in ('', '#top', 'mailto:a@b.c', 'javascript:void(0)', 'data:image/png;base64,AAAA', 'tel:+1'):
        assert rw(raw) == raw
    # excluded hosts keep their absolute form
    assert rw('https://x.com/a/status/1') == 'https://x.com/a/status/1'
    assert rw('https://www.twitter.com/a') == 'https://www.twitter.com/a'
    assert rw('https://t.me/chan/1') == 'https://t.me/chan/1'
    # already ours: never double-wrapped
    assert rw(f'{OWN}/p/a.example/x') == f'{OWN}/p/a.example/x'
    assert rw(f'{OWN}/pa/a.example/x.png', 'pa') == f'{OWN}/pa/a.example/x.png'
    assert rw(f'{OWN}/api/health') == f'{OWN}/api/health'
    # hosts we would refuse to proxy stay absolute rather than becoming a 400
    assert rw('http://localhost:3000/x') == 'http://localhost:3000/x'
    # host lowercased, userinfo dropped
    assert rw('https://User@A.Example/X') == '/p/a.example/X'


def test_idn_hosts_round_trip_through_the_proxy_path():
    """Review 2026-09-07 #7: ``rewrite_url`` emitted ``/p/例え.jp/x``; Safari sends the
    host percent-encoded, ``split_raw_path`` deliberately does not decode, and httpx
    neither decodes nor IDNA-encodes a percent-encoded host → DNS failure. The host
    segment is now unquoted (httpx then IDNA-encodes it); path and query stay raw."""
    assert purifier.rewrite_url('https://例え.jp/x', BASE, OWN, 'p') == '/p/例え.jp/x'
    t = purifier.parse_target('%E4%BE%8B%E3%81%88.jp', '/x%2Fy', 'q=%E3%81%82')
    assert t.host == '例え.jp'
    assert t.url == 'https://例え.jp/x%2Fy?q=%E3%81%82'
    assert httpx.URL(t.url).raw_host == b'xn--r8jz45g.jp'
    # decoding must not open a way past the host guard
    for smuggled in ('a%2Fb.example', 'a.example%2F..', 'a.example%3Fx', 'a.example%23f', 'a%09.example', 'a.example%25'):
        with pytest.raises(purifier.BadTargetError):
            purifier.parse_target(smuggled, '/', '')


def test_resolve_base_honors_base_href():
    html = '<html><head><base href="https://cdn.example/root/"></head><body></body></html>'
    assert purifier.resolve_base(html, 'https://a.example/page') == 'https://cdn.example/root/'
    assert (
        purifier.resolve_base('<html><head><base href="/sub/"></head></html>', 'https://a.example/page')
        == 'https://a.example/sub/'
    )
    assert purifier.resolve_base('<html></html>', 'https://a.example/page') == 'https://a.example/page'


def test_resolve_mode_priority():
    assert purifier.resolve_mode('news.ycombinator.com', None) == 'proxy'
    assert purifier.resolve_mode('news.ycombinator.com', 'readable') == 'readable'
    assert purifier.resolve_mode('blog.example', None) == 'readable'
    assert purifier.resolve_mode('blog.example', 'proxy') == 'proxy'
    assert purifier.resolve_mode('blog.example', 'puremd') == 'readable'  # never selectable
    assert purifier.resolve_mode('news.ycombinator.com:443', None) == 'proxy'


# --- CSS / srcset -----------------------------------------------------------


def test_rewrite_css_urls_and_imports():
    css = (
        '@import "theme.css";\n@import url(\'https://cdn.example/x.css\') screen;\n'
        'body{background:url(img/bg.png)} .a{background:url("/abs.png")} '
        ".b{background:url( 'rel.png' )} .c{background:url(data:image/gif;base64,R0lGOD)}"
    )
    out = purifier.rewrite_css(css, BASE, OWN)
    assert '@import "/pa/blog.example/posts/hello/theme.css"' in out
    assert "@import url('/pa/cdn.example/x.css') screen" in out
    assert 'url(/pa/blog.example/posts/hello/img/bg.png)' in out
    assert 'url("/pa/blog.example/abs.png")' in out
    assert "url('/pa/blog.example/posts/hello/rel.png')" in out
    assert 'url(data:image/gif;base64,R0lGOD)' in out


def test_rewrite_css_attribute_selectors_follow_the_html_rewrite():
    """HN's mobile stylesheet shrinks its indent spacers with
    ``img[src='s.gif'][width='40'] { width: 12px }``. Once the HTML's ``src`` is
    ``/pa/...`` those selectors match nothing and a thread is 558px wide on a 390px
    phone (measured 2026-09-07). Exact-match selectors are rewritten by the same
    rule as the attribute; prefix/suffix forms are left alone."""
    css = (
        "img[src='s.gif'][width='40']{width:12px} a[href=\"item\"]{color:red} "
        "video[poster=poster.jpg]{x:y} img[src$='.png']{a:b} img[src^='https://a']{c:d} [data-x='s.gif']{e:f}"
    )
    out = purifier.rewrite_css(css, BASE, OWN)
    assert "img[src='/pa/blog.example/posts/hello/s.gif'][width='40']" in out
    assert 'a[href="/p/blog.example/posts/hello/item"]' in out
    assert 'video[poster=/pa/blog.example/posts/hello/poster.jpg]' in out
    assert "img[src$='.png']" in out and "img[src^='https://a']" in out and "[data-x='s.gif']" in out


def test_rewrite_srcset_keeps_descriptors():
    out = purifier.rewrite_srcset('a.png 1x, https://cdn.example/b.png 2x,c.png 640w', BASE, OWN)
    assert out == (
        '/pa/blog.example/posts/hello/a.png 1x, /pa/cdn.example/b.png 2x, /pa/blog.example/posts/hello/c.png 640w'
    )


# --- proxy sanitizing -------------------------------------------------------


PROXY_HTML = """<!DOCTYPE html><html><head>
<base href="https://cdn.example/root/">
<meta http-equiv="refresh" content="0;url=https://evil.example">
<link rel="preload" href="a.js" as="script"><link rel="preconnect" href="https://x.example">
<link rel="stylesheet" href="news.css" integrity="sha256-abc">
<style>body{background:url(bg.png)}</style>
<script src="hn.js"></script><script>alert(1)</script>
</head><body onload="go()">
<iframe src="https://ads.example"></iframe><object data="x.swf"></object><embed src="y.swf">
<a href="item?id=1" onclick="track()">thread</a>
<a href="javascript:void(0)">[–]</a>
<a href="https://x.com/u/status/1">tweet</a>
<form action="reply?id=1" method="post"><input name="q"></form>
<img src="s.gif" srcset="s.gif 1x, s2.gif 2x" width="14">
<picture><source srcset="p.webp 1x"><img src="p.png"></picture>
<video poster="poster.jpg" src="v.mp4"></video>
<div style="background: url('inline.png')">x</div>
<noscript><img src="lazy.png"></noscript>
</body></html>"""


def _proxy(html=PROXY_HTML, **kw):
    base = purifier.resolve_base(html, 'https://news.ycombinator.com/item?id=1')
    return purifier.sanitize_and_rewrite_proxy(html, base, OWN, **kw)


def test_proxy_strips_scripts_handlers_and_embeds():
    out = _proxy()
    for gone in (
        '<script',
        'alert(1)',
        'onload',
        'onclick',
        '<iframe',
        '<object',
        '<embed',
        'http-equiv="refresh"',
        '<base',
        'rel="preload"',
        'rel="preconnect"',
        'integrity=',
    ):
        assert gone not in out, gone
    assert 'javascript:' not in out
    assert '[–]' in out  # the anchor text survives, only its href is gone


def test_proxy_rewrites_every_resource_and_link_against_base():
    out = _proxy()
    assert 'href="/pa/cdn.example/root/news.css"' in out
    assert 'url(/pa/cdn.example/root/bg.png)' in out
    assert 'href="/p/cdn.example/root/item?id=1"' in out
    assert 'action="/p/cdn.example/root/reply?id=1"' in out
    assert 'src="/pa/cdn.example/root/s.gif"' in out
    assert 'srcset="/pa/cdn.example/root/s.gif 1x, /pa/cdn.example/root/s2.gif 2x"' in out
    assert 'srcset="/pa/cdn.example/root/p.webp 1x"' in out
    assert 'poster="/pa/cdn.example/root/poster.jpg"' in out
    assert "url('/pa/cdn.example/root/inline.png')" in out
    # excluded host stays a real link out
    assert 'href="https://x.com/u/status/1"' in out
    # media the asset proxy would refuse is absolutized instead of broken
    assert 'src="https://cdn.example/root/v.mp4"' in out
    # <noscript> is unwrapped so its fallback <img> renders (we never run scripts anyway)
    assert '<noscript>' not in out and 'src="/pa/cdn.example/root/lazy.png"' in out


def test_proxy_adds_viewport_and_toolbar():
    toolbar = purifier.Toolbar(original_url='https://news.ycombinator.com/item?id=1', mode='proxy', full_page_url=None)
    out = _proxy(toolbar=toolbar)
    assert 'name="viewport"' in out
    assert 'cd-purifier-bar' in out
    assert 'href="https://news.ycombinator.com/item?id=1"' in out
    assert 'target="_blank"' in out
    # the toolbar is the first thing in <body>
    body = out[out.index('<body') :]
    assert body.index('cd-purifier-bar') < body.index('thread')


def test_proxy_keeps_existing_viewport_once():
    html = '<html><head><meta name="viewport" content="width=device-width"></head><body>x</body></html>'
    assert purifier.sanitize_and_rewrite_proxy(html, 'https://a.example/', OWN).count('name="viewport"') == 1


def test_proxy_allow_js_keeps_scripts():
    out = _proxy(allow_js=True)
    assert 'alert(1)' in out
    assert 'src="https://cdn.example/root/hn.js"' in out  # absolutized, never proxied
    assert 'onclick' not in out  # handlers still go


def test_proxy_strips_script_schemes_from_every_url_attribute():
    """Review 2026-09-07 #1: only ``href`` dropped ``javascript:``; ``action``,
    ``formaction`` and SVG's ``xlink:href`` went through untouched — a click ran
    script on condenser's origin, next to the reader cookie."""
    html = (
        '<html><body>'
        '<form action="javascript:alert(1)"><button formaction="javascript:alert(2)">go</button></form>'
        '<svg><a xlink:href="javascript:alert(3)"><text>y</text></a><image xlink:href="i.png"/></svg>'
        '<a href="JAVASCRIPT:alert(4)">u</a><a href="java\tscript:alert(5)">w</a>'
        '<a href="vbscript:msgbox(6)">v</a><a href="data:text/html,<script>alert(7)</script>">d</a>'
        '<input type="image" formaction="submit" src="data:image/png;base64,AAAA">'
        '<form action="post?x=1"></form>'
        '</body></html>'
    )
    out = purifier.sanitize_and_rewrite_proxy(html, 'https://a.example/dir/', OWN)
    assert 'javascript' not in out.lower() and 'vbscript' not in out.lower()
    assert 'alert(' not in out
    assert 'data:text/html' not in out
    # the text survives; the attributes are gone rather than the elements
    for kept in ('>go<', '<text>y</text>', '>u<', '>w<', '>v<', '>d<'):
        assert kept in out, kept
    # http(s) values on the same attributes are rewritten like href / action
    assert 'formaction="/p/a.example/dir/submit"' in out
    assert 'action="/p/a.example/dir/post?x=1"' in out
    assert 'xlink:href="/pa/a.example/dir/i.png"' in out
    # data: images stay images
    assert 'src="data:image/png;base64,AAAA"' in out


def test_proxy_promotes_lazy_images():
    html = (
        '<html><body><img data-src="real.png" src="data:image/gif;base64,R0lGOD"><img data-src="two.png"></body></html>'
    )
    out = purifier.sanitize_and_rewrite_proxy(html, 'https://a.example/', OWN)
    assert 'src="/pa/a.example/real.png"' in out
    assert 'src="/pa/a.example/two.png"' in out
    assert 'data:image/gif' not in out


# --- readable ---------------------------------------------------------------


def test_extract_readable_returns_title_body_and_chars():
    result = purifier.extract_readable(ARTICLE, BASE, OWN)
    assert result is not None
    title, body, chars = result
    assert title == 'Hello World'
    assert 'Paragraph 3' in body
    assert 'src="/pa/blog.example/posts/hello/img/one.png"' in body
    assert 'href="/p/blog.example/posts/other"' in body
    assert '© blog' not in body
    assert chars > 500


def test_extract_readable_returns_none_when_unparseable():
    assert purifier.extract_readable('', BASE, OWN) is None


def test_reader_template_is_self_contained():
    from condenser import purifier_html

    toolbar = purifier.Toolbar(
        original_url='https://a.example/x', mode='readable', full_page_url='/p/a.example/x?_mode=proxy'
    )
    out = purifier_html.reader_page(title='T <b>', body_html='<p>hi</p>', toolbar=toolbar, notice=None)
    assert 'prefers-color-scheme: dark' in out
    assert 'T &lt;b&gt;' in out
    assert 'href="/p/a.example/x?_mode=proxy"' in out
    assert 'name="viewport"' in out
    assert 'http' not in out.replace('https://a.example/x', '')  # no external resource at all


# --- puremd -----------------------------------------------------------------


PUREMD = """---
title: "A Title: with colon"
url: https://a.example/x
description: desc here
access_date: 2026-09-07
---

# Heading

Some *text* with ![a diagram](IMAGE) inline and [a link](https://a.example/y).

<script>alert(1)</script>
"""


def test_parse_puremd_frontmatter():
    title, description, body = purifier.parse_puremd(PUREMD)
    assert title == 'A Title: with colon'
    assert description == 'desc here'
    assert body.startswith('# Heading')
    assert purifier.parse_puremd('no frontmatter') == (None, None, 'no frontmatter')


def test_render_puremd_html_replaces_image_placeholders_with_alt():
    out = purifier.render_puremd_html(purifier.parse_puremd(PUREMD)[2])
    assert '<img' not in out
    assert 'a diagram' in out
    assert '<em>text</em>' in out
    assert 'href="https://a.example/y"' in out


# --- fetch: scheme retry + encoding -----------------------------------------


async def test_fetch_page_falls_back_to_http_only_on_transport_errors(env, monkeypatch):
    from condenser.config import get_settings

    calls = []

    async def capped(url, settings, *, cap, accept):
        calls.append(url)
        if url.startswith('https://'):
            raise httpx.ConnectError('refused')
        return url, 'text/html', b'<p>ok</p>'

    monkeypatch.setattr(preview, '_fetch_capped', capped)
    final, _ctype, body = await purifier.fetch_page(
        'https://a.example/x', get_settings(), cap=10, accept=lambda c: True
    )
    assert calls == ['https://a.example/x', 'http://a.example/x']
    assert final == 'http://a.example/x' and body == b'<p>ok</p>'


async def test_fetch_page_does_not_retry_http_status_errors(env, monkeypatch):
    from condenser.config import get_settings

    calls = []

    async def capped(url, settings, *, cap, accept):
        calls.append(url)
        req = httpx.Request('GET', url)
        raise httpx.HTTPStatusError('403', request=req, response=httpx.Response(403, request=req))

    monkeypatch.setattr(preview, '_fetch_capped', capped)
    with pytest.raises(purifier.UpstreamFetchError) as exc:
        await purifier.fetch_page('https://a.example/x', get_settings(), cap=10, accept=lambda c: True)
    assert calls == ['https://a.example/x']
    assert exc.value.status == 403


async def test_fetch_page_does_not_retry_read_timeouts(env, monkeypatch):
    from condenser.config import get_settings

    calls = []

    async def capped(url, settings, *, cap, accept):
        calls.append(url)
        raise httpx.ReadTimeout('slow')

    monkeypatch.setattr(preview, '_fetch_capped', capped)
    with pytest.raises(purifier.UpstreamFetchError):
        await purifier.fetch_page('https://a.example/x', get_settings(), cap=10, accept=lambda c: True)
    assert calls == ['https://a.example/x']


def test_detect_charset_priority():
    gbk_meta = b'<html><head><meta charset="gbk"></head></html>'
    assert purifier.detect_charset(gbk_meta, 'text/html; charset=big5') == 'big5'
    assert purifier.detect_charset(gbk_meta, 'text/html') == 'gbk'
    equiv = b'<html><head><meta http-equiv="Content-Type" content="text/html; charset=Shift_JIS"></head></html>'
    assert purifier.detect_charset(equiv, 'text/html') == 'shift_jis'
    assert purifier.detect_charset(b'<html></html>', 'text/html') == 'utf-8'
    assert purifier.detect_charset(b'<meta charset="no-such-charset">', '') == 'utf-8'


# --- render_document orchestration ------------------------------------------


def _settings(**overrides):
    from condenser.config import get_settings

    s = get_settings()
    for k, v in overrides.items():
        object.__setattr__(s, k, v)
    return s


async def test_render_readable_uses_template_when_long_enough(env):
    target = purifier.parse_target('blog.example', '/posts/hello/', '')
    result = await purifier.render_document(target, _settings(), own_origin=OWN, fetch_page=_page(ARTICLE.encode()))
    assert result.mode == 'readable'
    assert 'Hello World' in result.html and 'Paragraph 5' in result.html
    assert '/pa/blog.example/posts/hello/img/one.png' in result.html
    assert '_mode=proxy' in result.html  # the full-page link
    assert 'href="https://blog.example/posts/hello/"' in result.html  # original link


async def test_render_falls_back_to_puremd_when_body_too_short(env):
    seen = []

    async def puremd(url, settings):
        seen.append(url)
        return PUREMD

    target = purifier.parse_target('a.example', '/x', '')
    result = await purifier.render_document(
        target,
        _settings(condenser_puremd_api_key='k'),
        own_origin=OWN,
        fetch_page=_page(SHORT.encode()),
        fetch_puremd=puremd,
    )
    assert result.mode == 'puremd'
    assert seen == ['https://a.example/x']
    assert 'A Title: with colon' in result.html
    assert 'a diagram' in result.html and '<img' not in result.html
    assert 'alert(1)' not in result.html
    assert 'href="/p/a.example/y"' in result.html  # links inside the markdown go through the proxy too


async def test_render_falls_back_to_puremd_on_non_html_and_fetch_errors(env):
    async def puremd(url, settings):
        return PUREMD

    async def boom(url, settings, *, cap, accept):
        raise purifier.UpstreamFetchError('HTTP 403', status=403)

    target = purifier.parse_target('a.example', '/x', '')
    s = _settings(condenser_puremd_api_key='k')
    pdf = await purifier.render_document(
        target, s, own_origin=OWN, fetch_page=_page(b'%PDF', 'application/pdf'), fetch_puremd=puremd
    )
    assert pdf.mode == 'puremd'
    purifier.clear_cache()
    denied = await purifier.render_document(target, s, own_origin=OWN, fetch_page=boom, fetch_puremd=puremd)
    assert denied.mode == 'puremd'


async def test_render_without_puremd_key_shows_short_body_with_notice(env):
    target = purifier.parse_target('a.example', '/x', '')
    result = await purifier.render_document(
        target, _settings(condenser_puremd_api_key=''), own_origin=OWN, fetch_page=_page(SHORT.encode())
    )
    assert result.mode == 'readable'
    assert 'Too short.' in result.html
    assert 'cd-purifier-notice' in result.html


async def test_render_without_puremd_key_and_no_body_raises(env):
    async def boom(url, settings, *, cap, accept):
        raise purifier.UpstreamFetchError('HTTP 403', status=403)

    target = purifier.parse_target('a.example', '/x', '')
    with pytest.raises(purifier.UpstreamFetchError):
        await purifier.render_document(target, _settings(condenser_puremd_api_key=''), own_origin=OWN, fetch_page=boom)


async def test_render_puremd_failure_still_shows_short_body(env):
    async def puremd(url, settings):
        raise purifier.PuremdError('429')

    target = purifier.parse_target('a.example', '/x', '')
    result = await purifier.render_document(
        target,
        _settings(condenser_puremd_api_key='k'),
        own_origin=OWN,
        fetch_page=_page(SHORT.encode()),
        fetch_puremd=puremd,
    )
    assert result.mode == 'readable' and 'Too short.' in result.html


async def test_render_proxy_mode_for_hn(env):
    target = purifier.parse_target('news.ycombinator.com', '/item', 'id=1')
    result = await purifier.render_document(target, _settings(), own_origin=OWN, fetch_page=_page(PROXY_HTML.encode()))
    assert result.mode == 'proxy'
    assert 'href="/p/cdn.example/root/item?id=1"' in result.html
    assert 'cd-purifier-bar' in result.html


async def test_render_proxy_mode_propagates_fetch_errors(env):
    async def boom(url, settings, *, cap, accept):
        raise purifier.UpstreamFetchError('HTTP 500', status=500)

    target = purifier.parse_target('news.ycombinator.com', '/item', 'id=1')
    with pytest.raises(purifier.UpstreamFetchError):
        await purifier.render_document(target, _settings(), own_origin=OWN, fetch_page=boom)


async def test_render_proxy_mode_maps_parser_failures_to_purifier_errors(env):
    """Review 2026-09-07 #4: an XHTML page with an ``<?xml … encoding=…?>`` prologue
    made lxml raise ``ValueError``, an empty body ``ParserError`` — neither a
    ``PurifierError``, so the 502 error page never rendered and SFSafariViewController
    got a bare Internal Server Error, with no way back to the original link."""
    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml">'
        '<head><title>X</title></head><body><p>xhtml body</p></body></html>'
    )
    target = purifier.parse_target('news.ycombinator.com', '/item', 'id=1')
    result = await purifier.render_document(target, _settings(), own_origin=OWN, fetch_page=_page(xhtml.encode()))
    assert result.mode == 'proxy' and 'xhtml body' in result.html  # the prologue is stripped, not fatal
    purifier.clear_cache()
    with pytest.raises(purifier.PurifierError):
        await purifier.render_document(target, _settings(), own_origin=OWN, fetch_page=_page(b'   '))


async def test_render_decodes_meta_charset(env):
    html = (
        '<html><head><meta charset="gbk"><title>标题</title></head><body><article>'
        + '<p>中文正文内容。</p>' * 80
        + '</article></body></html>'
    )
    target = purifier.parse_target('a.example', '/x', '')
    result = await purifier.render_document(
        target, _settings(), own_origin=OWN, fetch_page=_page(html.encode('gbk'), 'text/html')
    )
    assert '中文正文内容' in result.html


# --- cache ------------------------------------------------------------------


async def test_cache_hits_by_url_and_mode_and_expires(env, monkeypatch):
    calls = {'n': 0}

    async def fetch(url, settings, *, cap, accept):
        calls['n'] += 1
        return url, 'text/html', ARTICLE.encode()

    clock = {'t': 1000.0}
    monkeypatch.setattr(purifier, '_clock', lambda: clock['t'])
    s = _settings(condenser_purifier_cache_ttl=60)
    target = purifier.parse_target('blog.example', '/posts/hello/', '')
    await purifier.render_document(target, s, own_origin=OWN, fetch_page=fetch)
    await purifier.render_document(target, s, own_origin=OWN, fetch_page=fetch)
    assert calls['n'] == 1
    await purifier.render_document(target, s, own_origin=OWN, mode_override='proxy', fetch_page=fetch)
    assert calls['n'] == 2  # a different mode is a different document
    clock['t'] += 61
    await purifier.render_document(target, s, own_origin=OWN, fetch_page=fetch)
    assert calls['n'] == 3


# --- render_asset -----------------------------------------------------------


async def test_render_asset_passes_images_and_rewrites_css(env):
    target = purifier.parse_target('cdn.example', '/root/news.css', '')
    css = await purifier.render_asset(
        target, _settings(), own_origin=OWN, fetch_page=_page(b'body{background:url(bg.png)}', 'text/css')
    )
    assert css.content_type.startswith('text/css')
    assert css.body == b'body{background:url(/pa/cdn.example/root/bg.png)}'
    img = await purifier.render_asset(
        purifier.parse_target('cdn.example', '/s.gif', ''),
        _settings(),
        own_origin=OWN,
        fetch_page=_page(b'GIF89a', 'image/gif'),
    )
    assert img.content_type == 'image/gif' and img.body == b'GIF89a'


async def test_render_asset_refuses_scripts(env):
    target = purifier.parse_target('cdn.example', '/hn.js', '')
    with pytest.raises(purifier.UnsupportedAssetError):
        await purifier.render_asset(
            target, _settings(), own_origin=OWN, fetch_page=_page(b'alert(1)', 'application/javascript')
        )


# --- router + auth ----------------------------------------------------------


def _install(monkeypatch, fetch_page=None, fetch_puremd=None):
    from condenser.routers import purifier as router

    if fetch_page is not None:
        monkeypatch.setattr(router, '_fetch_page', fetch_page)
    if fetch_puremd is not None:
        monkeypatch.setattr(router, '_fetch_puremd', fetch_puremd)


def test_ticket_endpoint_requires_auth_and_returns_verifiable_ticket(env):
    with _client() as client:
        assert client.get('/api/purifier/ticket').status_code == 401
        token = _device_token(client)
        r = client.get('/api/purifier/ticket', headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 200
        data = r.json()
        assert data['ttl'] == 300
        assert crypto.verify_purifier_ticket('secret', data['ticket'])


def test_document_without_cookie_or_ticket_is_401_html(env, monkeypatch):
    _install(monkeypatch, _page(ARTICLE.encode()))
    with _client() as client:
        r = client.get('/p/blog.example/posts/hello/')
        assert r.status_code == 401
        assert r.headers['content-type'].startswith('text/html')
        assert 'https://blog.example/posts/hello/' in r.text


def test_valid_ticket_sets_reader_cookie_and_redirects_without_it(env, monkeypatch):
    _install(monkeypatch, _page(ARTICLE.encode()))
    ticket = crypto.sign_purifier_ticket('secret')
    with _client() as client:
        r = client.get(f'/p/blog.example/posts/hello/?orig=1&_pt={ticket}&_mode=proxy', follow_redirects=False)
        assert r.status_code == 302
        assert r.headers['location'] == '/p/blog.example/posts/hello/?orig=1&_mode=proxy'
        assert READER_COOKIE_NAME in r.cookies
        assert crypto.verify_reader_cookie('secret', r.cookies[READER_COOKIE_NAME])
        assert 'httponly' in r.headers['set-cookie'].lower()
        # the cookie alone now opens documents
        r2 = client.get('/p/blog.example/posts/hello/?orig=1')
        assert r2.status_code == 200
        assert 'Hello World' in r2.text


def test_ticket_only_strips_itself(env, monkeypatch):
    _install(monkeypatch, _page(ARTICLE.encode()))
    ticket = crypto.sign_purifier_ticket('secret')
    with _client() as client:
        r = client.get(f'/p/blog.example/posts/hello/?_pt={ticket}', follow_redirects=False)
        assert r.headers['location'] == '/p/blog.example/posts/hello/'


def test_forged_or_expired_ticket_is_401(env, monkeypatch):
    _install(monkeypatch, _page(ARTICLE.encode()))
    with _client() as client:
        assert client.get('/p/blog.example/x?_pt=forged', follow_redirects=False).status_code == 401
        expired = crypto.sign_purifier_ticket('secret')
        monkeypatch.setattr(crypto, 'PURIFIER_TICKET_MAX_AGE', -1)
        r = client.get(f'/p/blog.example/x?_pt={expired}', follow_redirects=False)
        assert r.status_code == 401
        assert READER_COOKIE_NAME not in r.cookies


def test_app_session_cookie_also_opens_documents(env, monkeypatch):
    _install(monkeypatch, _page(ARTICLE.encode()))
    with _client() as client:
        _login(client)
        assert COOKIE_NAME in client.cookies
        r = client.get('/p/blog.example/posts/hello/')
        assert r.status_code == 200 and 'Hello World' in r.text


def test_reader_cookie_cannot_reach_api_or_device_management(env, monkeypatch):
    with _client() as client:
        client.cookies.set(READER_COOKIE_NAME, crypto.sign_reader_cookie('secret'))
        assert client.get('/api/subscriptions').status_code == 401
        assert client.post('/api/auth/device', json={'name': 'x'}).status_code == 401


def test_bearer_is_not_accepted_on_documents(env, monkeypatch):
    _install(monkeypatch, _page(ARTICLE.encode()))
    with _client() as client:
        token = _device_token(client)
        assert client.get('/p/blog.example/x', headers={'Authorization': f'Bearer {token}'}).status_code == 401


def test_hn_is_proxied_and_query_is_forwarded_raw(env, monkeypatch):
    seen = []

    async def fetch(url, settings, *, cap, accept):
        seen.append(url)
        return url, 'text/html', PROXY_HTML.encode()

    _install(monkeypatch, fetch)
    with _client() as client:
        _login(client)
        r = client.get('/p/news.ycombinator.com/item?id=49537553&p=2&x=a%2Fb')
        assert r.status_code == 200
        assert seen == ['https://news.ycombinator.com/item?id=49537553&p=2&x=a%2Fb']
        assert 'cd-purifier-bar' in r.text
        assert '整页' in r.text and '_mode=proxy' not in r.text  # no full-page link in proxy mode
        assert r.headers['content-type'].startswith('text/html')


def test_mode_override_and_default_readable(env, monkeypatch):
    _install(monkeypatch, _page(ARTICLE.encode()))
    with _client() as client:
        _login(client)
        readable = client.get('/p/blog.example/posts/hello/').text
        assert 'cd-purifier-reader' in readable
        full = client.get('/p/blog.example/posts/hello/?_mode=proxy').text
        assert 'cd-purifier-reader' not in full and '© blog' in full


def test_document_route_matches_bare_host_and_encoded_path(env, monkeypatch):
    seen = []

    async def fetch(url, settings, *, cap, accept):
        seen.append(url)
        return url, 'text/html', ARTICLE.encode()

    _install(monkeypatch, fetch)
    with _client() as client:
        _login(client)
        assert client.get('/p/blog.example').status_code == 200
        assert client.get('/p/blog.example/a%2Fb/c%20d').status_code == 200
        assert seen == ['https://blog.example', 'https://blog.example/a%2Fb/c%20d']


def test_idn_host_is_fetched_as_unicode_url(env, monkeypatch):
    seen = []

    async def fetch(url, settings, *, cap, accept):
        seen.append(url)
        return url, 'text/html', ARTICLE.encode()

    _install(monkeypatch, fetch)
    with _client() as client:
        _login(client)
        assert client.get('/p/%E4%BE%8B%E3%81%88.jp/x').status_code == 200
        assert seen == ['https://例え.jp/x']


def test_bad_target_is_400_and_upstream_failure_is_502_html(env, monkeypatch):
    async def boom(url, settings, *, cap, accept):
        raise httpx.ConnectError('down')

    _install(monkeypatch, boom)
    with _client() as client:
        _login(client)
        assert client.get('/p/localhost/x').status_code == 400
        r = client.get('/p/news.ycombinator.com/item?id=1')
        assert r.status_code == 502
        assert r.headers['content-type'].startswith('text/html')
        assert 'https://news.ycombinator.com/item?id=1' in r.text


def test_proxy_mode_parser_failure_is_502_html_with_original_link(env, monkeypatch):
    _install(monkeypatch, _page(b''))
    with _client() as client:
        _login(client)
        r = client.get('/p/news.ycombinator.com/item?id=1')
        assert r.status_code == 502
        assert r.headers['content-type'].startswith('text/html')
        assert 'https://news.ycombinator.com/item?id=1' in r.text


def test_asset_route_gates_types_and_sets_cache_headers(env, monkeypatch):
    def fetch_for(ctype, body):
        async def fetch(url, settings, *, cap, accept):
            if not accept(ctype):
                raise preview.PreviewError('unsupported')
            return url, ctype, body

        return fetch

    with _client() as client:
        assert client.get('/pa/cdn.example/a.png').status_code == 401
        _login(client)
        _install(monkeypatch, fetch_for('image/png', b'\x89PNG'))
        r = client.get('/pa/cdn.example/a.png')
        assert r.status_code == 200
        assert r.headers['content-type'] == 'image/png'
        assert r.headers['cache-control'] == 'private, max-age=86400'
        _install(monkeypatch, fetch_for('application/javascript', b'alert(1)'))
        assert client.get('/pa/cdn.example/hn.js').status_code == 415
        _install(monkeypatch, fetch_for('text/css', b'a{background:url(x.png)}'))
        r = client.get('/pa/cdn.example/root/news.css')
        assert r.text == 'a{background:url(/pa/cdn.example/root/x.png)}'


def test_asset_responses_are_sandboxed(env, monkeypatch):
    """Review 2026-09-07 #2: ``/pa`` passed ``image/svg+xml`` through verbatim with no
    CSP, so a shared ``/pa/evil.example/x.svg`` opened top-level ran its ``<script>``
    on condenser's origin with the cookies. Every asset now ships sandboxed."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>fetch("/api/subscriptions")</script></svg>'

    async def fetch(url, settings, *, cap, accept):
        return url, 'image/svg+xml', svg

    _install(monkeypatch, fetch)
    with _client() as client:
        _login(client)
        r = client.get('/pa/evil.example/x.svg')
        assert r.status_code == 200
        csp = r.headers['content-security-policy']
        assert 'sandbox' in csp and "script-src 'none'" in csp
        assert r.headers['x-content-type-options'] == 'nosniff'


def test_allow_js_sends_csp(env, monkeypatch):
    monkeypatch.setenv('CONDENSER_PURIFIER_ALLOW_JS', 'true')
    from condenser.config import get_settings

    get_settings.cache_clear()
    _install(monkeypatch, _page(PROXY_HTML.encode()))
    with _client() as client:
        _login(client)
        r = client.get('/p/news.ycombinator.com/item?id=1')
        assert r.status_code == 200
        csp = r.headers['content-security-policy']
        assert "connect-src 'none'" in csp and "frame-src 'none'" in csp and "form-action 'self'" in csp
        assert 'alert(1)' in r.text


def test_no_csp_header_by_default(env, monkeypatch):
    _install(monkeypatch, _page(PROXY_HTML.encode()))
    with _client() as client:
        _login(client)
        r = client.get('/p/news.ycombinator.com/item?id=1')
        assert 'content-security-policy' not in r.headers


def test_document_route_beats_spa_fallback(env, tmp_path, monkeypatch):
    static = tmp_path / 'dist'
    static.mkdir()
    (static / 'index.html').write_text('<html>SPA</html>')
    monkeypatch.setenv('CONDENSER_STATIC_DIR', str(static))
    _install(monkeypatch, _page(ARTICLE.encode()))
    with _client() as client:
        _login(client)
        r = client.get('/p/blog.example/posts/hello/')
        assert r.status_code == 200 and 'SPA' not in r.text and 'Hello World' in r.text
        assert (
            client.get('/pa/blog.example/x.png').status_code != 200
            or 'SPA' not in client.get('/pa/blog.example/x.png').text
        )


def test_responses_are_gzipped_when_asked(env, monkeypatch):
    _install(monkeypatch, _page(ARTICLE.encode()))
    with _client() as client:
        _login(client)
        r = client.get('/p/blog.example/posts/hello/', headers={'Accept-Encoding': 'gzip'})
        assert r.headers.get('content-encoding') == 'gzip'
        assert 'Hello World' in r.text  # transparently decoded


def test_binary_responses_are_not_gzipped(env, monkeypatch):
    """Review 2026-09-07 #8: the global GZipMiddleware compressed every proxied image /
    media body on the event loop (measured ~14ms/MB) for zero size gain. Already-
    compressed types pass through identity; CSS (text) is still compressed."""
    body = bytes(range(256)) * 40  # 10KB, well over minimum_size

    def fetch_for(ctype):
        async def fetch(url, settings, *, cap, accept):
            return url, ctype, body if ctype != 'text/css' else b'a{color:red}' * 200

        return fetch

    with _client() as client:
        _login(client)
        for ctype in ('image/png', 'image/svg+xml', 'font/woff2', 'application/font-woff2'):
            _install(monkeypatch, fetch_for(ctype))
            r = client.get(f'/pa/cdn.example/a.{ctype.split("/")[1]}', headers={'Accept-Encoding': 'gzip'})
            assert r.status_code == 200 and r.headers['content-type'] == ctype
            assert 'content-encoding' not in r.headers, ctype
            assert r.content == body
        _install(monkeypatch, fetch_for('text/css'))
        r = client.get('/pa/cdn.example/a.css', headers={'Accept-Encoding': 'gzip'})
        assert r.headers.get('content-encoding') == 'gzip'
