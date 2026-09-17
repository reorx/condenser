"""Behavior tests for the Purifier's X handler (condenser/purifier_x.py + its wiring in
purifier.py / routers/purifier.py; plan kb/plans/2026-09-17-purifier-x-fxembed.md).

Fixtures under ``tests/fixtures/x_fxembed/`` are real FxEmbed ``/2/conversation``
responses (2026-09-17, author profile fields trimmed). No test touches the network:
the conversation fetch is injected through ``fetch_x``, and the one test of the real
fetch swaps in an ``httpx.MockTransport``.
"""

import copy
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from condenser import purifier, purifier_x
from condenser.app import create_app

OWN = 'https://condenser.example'
FIXTURES = Path(__file__).parent / 'fixtures' / 'x_fxembed'


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f'conversation_{name}.json').read_text())


def _settings(**overrides):
    from condenser.config import get_settings

    s = get_settings()
    for k, v in overrides.items():
        object.__setattr__(s, k, v)
    return s


def _fx(payload, http_status: int = 200, seen: list | None = None):
    """An injectable ``fetch_x`` answering with a canned (HTTP status, body)."""

    async def _impl(status_id, settings):
        if seen is not None:
            seen.append(status_id)
        return http_status, copy.deepcopy(payload)

    return _impl


async def _no_page(url, settings, *, cap, accept):
    raise AssertionError(f'an X status must not be fetched as a page: {url}')


async def _render(host: str, path: str, payload, *, query: str = '', settings=None, **kw):
    target = purifier.parse_target(host, path, query)
    fetch_x = _fx(payload, **kw.pop('fx', {}))
    kw.setdefault('fetch_page', _no_page)
    return await purifier.render_document(target, settings or _settings(), own_origin=OWN, fetch_x=fetch_x, **kw)


def _section(html: str, start_marker: str, end_marker: str | None = None) -> str:
    """From a marker to the next one, searched in the body (class names are in the CSS too)."""
    start = html.index(start_marker, html.index('<body>'))
    end = html.index(end_marker, start) if end_marker else len(html)
    return html[start:end]


def _body(html: str) -> str:
    return html[html.index('<body>') :]


@pytest.fixture(autouse=True)
def _fresh_cache():
    purifier.clear_cache()
    yield
    purifier.clear_cache()


# --- which URLs are X status links -------------------------------------------


def test_parse_status_url_accepts_every_status_shape_and_alias():
    for host in (
        'x.com', 'twitter.com', 'www.x.com', 'mobile.twitter.com', 'm.x.com', 'X.COM',
        'fixupx.com', 'fxtwitter.com', 'vxtwitter.com', 'twittpr.com', 'www.fxtwitter.com',
    ):  # fmt: skip
        assert purifier_x.parse_status_url(host, '/jack/status/20') == '20', host
    for path in (
        '/jack/status/20', '/i/status/20', '/i/web/status/20', '/jack/statuses/20', '/jack/status/20/',
        '/jack/status/20/photo/1', '/jack/status/20/video/2', '/jack/status/20/analytics',
    ):  # fmt: skip
        assert purifier_x.parse_status_url('x.com', path) == '20', path


def test_parse_status_url_refuses_everything_else():
    for host, path in (
        ('x.com', '/jack'),
        ('x.com', '/i/spaces/1YqKDqWqdPLJV'),
        ('x.com', '/search'),
        ('x.com', '/i/article/2095826308504731649'),
        ('x.com', '/jack/status/'),
        ('x.com', '/jack/status/abc'),
        ('x.com', '/jack/status/20/likes'),
        ('x.com', '/a_handle_far_too_long/status/20'),
        ('x.com', ''),
        ('notx.com', '/jack/status/20'),
        ('x.com.evil.example', '/jack/status/20'),
        ('news.ycombinator.com', '/jack/status/20'),
    ):
        assert purifier_x.parse_status_url(host, path) is None, (host, path)


def test_rewrite_url_sends_x_status_links_through_the_proxy_and_nothing_else_of_x():
    rw = lambda href, kind='p': purifier.rewrite_url(href, 'https://blog.example/', OWN, kind)  # noqa: E731
    assert rw('https://x.com/jack/status/20?s=20&t=abc') == '/p/x.com/jack/status/20?s=20&t=abc'
    assert rw('https://twitter.com/i/web/status/20') == '/p/twitter.com/i/web/status/20'
    assert rw('https://mobile.twitter.com/jack/status/20/photo/1') == '/p/mobile.twitter.com/jack/status/20/photo/1'
    # the rest of X still leaves as it came — a working deep link today, an error page if proxied
    for kept in (
        'https://x.com/jack', 'https://x.com/i/spaces/1YqKDqWqdPLJV', 'https://x.com/search?q=a',
        'https://x.com/i/article/2095826308504731649', 'https://t.me/chan/1',
    ):  # fmt: skip
        assert rw(kept) == kept
    # a status URL is a document, never an asset
    assert rw('https://x.com/jack/status/20', 'pa') == 'https://x.com/jack/status/20'
    # FixTweet mirrors were never excluded, and still are not
    assert rw('https://fixupx.com/jack/status/20') == '/p/fixupx.com/jack/status/20'


# --- the fetch ------------------------------------------------------------------


async def test_fetch_conversation_asks_the_configured_base_with_the_project_user_agent(env, monkeypatch):
    """Cloudflare in front of api.fxtwitter.com challenges a ``python-httpx/*`` UA with a
    403 HTML page (measured 2026-09-17); the project's own UA passes."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={'code': 200, 'status': {'id': '20'}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    s = _settings()
    assert await purifier_x.fetch_conversation('20', s) == (200, {'code': 200, 'status': {'id': '20'}})
    assert str(seen[0].url) == 'https://api.fxtwitter.com/2/conversation/20'
    assert seen[0].headers['user-agent'] == s.condenser_preview_user_agent
    assert 'python-httpx' not in seen[0].headers['user-agent']

    # a self-hosted base is one env line, trailing slash or not
    await purifier_x.fetch_conversation('21', _settings(condenser_purifier_x_api_base='https://fx.self.example/'))
    assert str(seen[1].url) == 'https://fx.self.example/2/conversation/21'


async def test_fetch_conversation_reports_a_non_json_answer_as_no_body(env, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, html='<!DOCTYPE html><title>Just a moment...</title>')

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    assert await purifier_x.fetch_conversation('20', _settings()) == (403, None)


# --- dispatch -------------------------------------------------------------------


async def test_x_status_renders_from_fxembed_and_never_fetches_the_page(env):
    seen: list[str] = []
    result = await _render('x.com', '/derbederdusler/status/1770888775830262034', _load('reply'), fx={'seen': seen})
    assert seen == ['1770888775830262034']
    assert result.mode == 'x'
    assert 'cd-x-focus' in result.html


async def test_aliases_normalize_to_the_x_handler_and_share_one_cache_entry(env):
    seen: list[str] = []
    fetch_x = _fx(_load('reply'), seen=seen)
    s = _settings()
    for host, path in (
        ('fixupx.com', '/derbederdusler/status/1770888775830262034'),
        ('twitter.com', '/i/web/status/1770888775830262034'),
        ('x.com', '/derbederdusler/status/1770888775830262034/photo/1'),
    ):
        target = purifier.parse_target(host, path, 's=20')
        result = await purifier.render_document(target, s, own_origin=OWN, fetch_page=_no_page, fetch_x=fetch_x)
        assert result.mode == 'x'
    assert seen == ['1770888775830262034']


async def test_mode_override_does_not_reach_an_x_status(env):
    """The X handler is a data source, not a fourth mode: it claims the target before
    ``_mode`` is looked at (there is no x.com page to show whole)."""
    result = await _render('x.com', '/jack/status/1770888775830262034', _load('reply'), query='_mode=proxy')
    assert result.mode == 'x'


async def test_a_redirect_that_lands_on_an_x_status_is_handed_to_the_x_handler(env):
    """t.co / bit.ly: the page fetch ends on x.com's empty shell; the X handler renders
    what the link meant instead of readability scraping the shell (plan §1.5)."""
    seen: list[str] = []

    async def fetch_page(url, settings, *, cap, accept):
        return (
            'https://x.com/derbederdusler/status/1770888775830262034/photo/1',
            'text/html',
            b'<html><body></body></html>',
        )

    async def puremd(url, settings):
        raise AssertionError('an X status must not fall back to pure.md')

    target = purifier.parse_target('t.co', '/ONypPaqZBF', '')
    result = await purifier.render_document(
        target,
        _settings(condenser_puremd_api_key='k'),
        own_origin=OWN,
        fetch_page=fetch_page,
        fetch_puremd=puremd,
        fetch_x=_fx(_load('reply'), seen=seen),
    )
    assert seen == ['1770888775830262034']
    assert result.mode == 'x'


async def test_handler_off_leaves_render_document_on_the_ordinary_path(env):
    calls = []

    body = '<html><head><title>T</title></head><body><article>' + '<p>A paragraph of ordinary prose. </p>' * 40
    body += '</article></body></html>'

    async def fetch_page(url, settings, *, cap, accept):
        calls.append(url)
        return 'https://x.com/jack/status/20', 'text/html', body.encode()

    async def must_not_run(status_id, settings):
        raise AssertionError('handler is off')

    target = purifier.parse_target('t.co', '/abc', '')
    s = _settings(condenser_purifier_x_api_base='', condenser_puremd_api_key='')
    result = await purifier.render_document(target, s, own_origin=OWN, fetch_page=fetch_page, fetch_x=must_not_run)
    assert result.mode == 'readable' and calls == ['https://t.co/abc']
    assert purifier.passthrough_url(purifier.parse_target('x.com', '/jack/status/20', 's=1'), s) == (
        'https://x.com/jack/status/20?s=1'
    )
    assert purifier.passthrough_url(purifier.parse_target('x.com', '/jack', ''), s) is None
    on = _settings(condenser_purifier_x_api_base='https://api.fxtwitter.com')
    assert purifier.passthrough_url(purifier.parse_target('x.com', '/jack/status/20', ''), on) is None


# --- failures ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ('http_status', 'payload', 'needle'),
    [
        (404, {'code': 404, 'status': None, 'thread': None, 'replies': None}, '删除'),
        # the verdict lives in the body: FxEmbed can say 401 under an HTTP 200
        (200, {'code': 401, 'message': 'PRIVATE_TWEET'}, '受保护'),
        (403, None, '403'),  # Cloudflare's challenge page, not JSON at all
        (503, {'code': 500, 'message': 'API_FAIL'}, '500'),
    ],
)
async def test_fxembed_failures_become_upstream_errors(env, http_status, payload, needle):
    with pytest.raises(purifier.UpstreamFetchError) as info:
        await _render('x.com', '/jack/status/20', payload, fx={'http_status': http_status})
    assert needle in str(info.value)


async def test_unparseable_fxembed_body_is_an_upstream_error(env):
    async def garbled(status_id, settings):
        return json.loads('{not json')

    target = purifier.parse_target('x.com', '/jack/status/20', '')
    with pytest.raises(purifier.UpstreamFetchError):
        await purifier.render_document(target, _settings(), own_origin=OWN, fetch_page=_no_page, fetch_x=garbled)


async def test_failures_are_not_cached(env):
    target = purifier.parse_target('x.com', '/jack/status/1770888775830262034', '')
    s = _settings()
    with pytest.raises(purifier.UpstreamFetchError):
        await purifier.render_document(target, s, own_origin=OWN, fetch_x=_fx({'code': 404}, 404))
    result = await purifier.render_document(target, s, own_origin=OWN, fetch_x=_fx(_load('reply')))
    assert result.mode == 'x'


# --- the page -----------------------------------------------------------------------


async def test_page_shell_title_toolbar_and_no_full_page_link(env):
    html = (await _render('x.com', '/derbederdusler/status/1770888775830262034', _load('reply'))).html
    assert '<title>𝕯𝖊𝖗𝖇𝖊𝖉𝖊𝖗 @derbederdusler</title>' in html
    assert 'href="https://x.com/derbederdusler/status/1770888775830262034"' in html  # 原网页
    assert '推文' in _section(html, 'cd-purifier-bar', '</div>')
    assert '_mode=proxy' not in html and '整页 →' not in html
    assert '<script' not in html


async def test_ancestor_chain_renders_above_the_focus_in_order(env):
    html = _body((await _render('x.com', '/derbederdusler/status/1770888775830262034', _load('reply'))).html)
    ancestor = html.index('just setting up my twttr')
    focus = html.index('cd-x-focus')
    replies = html.index('cd-x-replies')
    assert ancestor < focus < replies
    assert html.count('cd-x-ancestor') == 1


async def test_display_text_range_drops_leading_mentions_and_the_media_link(env):
    html = (await _render('x.com', '/derbederdusler/status/1770888775830262034', _load('reply'))).html
    replies = _section(html, 'cd-x-replies')
    assert 'it should be the other way' in replies
    assert '@derbederdusler @jack it should' not in replies
    # the focus is "@jack" + a photo: after the cut there is no text left, only the photo
    focus = _section(html, 'cd-x-focus', '</article>')
    assert 'cd-x-text' not in focus and 't.co/' not in html


async def test_facets_link_urls_and_survive_stale_indices(env):
    """A note tweet: a url facet after an emoji (indices count code points, not UTF-16
    units), and a media facet whose indices point into the legacy truncated text."""
    html = (await _render('x.com', '/jonnygravity/status/2076460501123653774', _load('note_video'))).html
    focus = _section(html, 'cd-x-focus', '</article>')
    assert '<a href="/p/getatrium.dev">getatrium.dev</a>' in focus
    assert 'Change density' in focus and 'Group by project or status' in focus  # the stale facet ate nothing
    assert 't.co/' not in focus


async def test_photos_are_downsized_and_proxied_and_x_is_never_contacted_by_the_browser(env):
    html = (await _render('x.com', '/novoreorx/status/2079732304914862528', _load('quote'))).html
    assert '/pa/pbs.twimg.com/media/HNyxgDya8AAO0kC.jpg?name=medium' in html
    assert 'name=orig' not in html
    assert 'src="https://pbs.twimg.com' not in html and 'src="http' not in html
    assert '/pa/pbs.twimg.com/profile_images/' in html  # avatars too


async def test_quote_renders_nested_and_links_to_its_own_discussion(env):
    html = (await _render('x.com', '/novoreorx/status/2079732304914862528', _load('quote'))).html
    quote = _section(html, 'cd-x-quote')
    assert '我做了一个自部署的阅读器' in quote
    data = _load('quote')
    q = data['status']['quote']
    assert f'href="/p/x.com/{q["author"]["screen_name"]}/status/{q["id"]}"' in quote


async def test_deleted_quote_is_a_tombstone_not_a_crash(env):
    data = _load('quote')
    data['status']['quote'] = {
        'type': 'tombstone',
        'provider': 'twitter',
        'reason': 'deleted',
        'message': 'This post was deleted by the post author.',
    }
    html = (await _render('x.com', '/novoreorx/status/2079732304914862528', data)).html
    assert 'cd-x-tombstone' in html and '已被删除' in html


async def test_video_is_a_proxied_poster_linking_to_a_playable_file(env):
    html = (await _render('x.com', '/jonnygravity/status/2076460501123653774', _load('note_video'))).html
    video = _section(html, 'cd-x-video', '</a>')
    assert '/pa/pbs.twimg.com/amplify_video_thumb/2076458678874517504/img/oppe11pgTtF29FZX.jpg?name=medium' in video
    # the 720p mp4 (2.2 Mbps), not the 10 Mbps original: a phone plays it without X's login wall
    assert 'href="https://video.twimg.com/amplify_video/2076458678874517504/vid/avc1/1052x720/' in video
    assert '▶' in video and '1:59' in video


async def test_article_card_shows_title_preview_and_cover(env):
    html = (await _render('x.com', '/xiaoerzhan/status/2099707280845332534', _load('article'))).html
    card = _section(html, 'cd-x-article')
    assert '如何不出境、不开香港公司，给自己的产品接上全球收款' in card
    assert '我做了个 Mac 工具 Omia' in card
    assert '/pa/pbs.twimg.com/media/HRXe6lhW4AADNow.jpg?name=medium' in card
    assert 'href="https://x.com/i/article/2095826308504731649"' in card
    # the tweet's own link to the article is the card now, not a second line of text
    focus_text = _section(html, 'cd-x-focus', 'cd-x-article')
    assert 'x.com/i/article' not in focus_text


async def test_replies_are_cut_to_the_top_n_threads(env):
    html = (
        await _render(
            'x.com',
            '/derbederdusler/status/1770888775830262034',
            _load('reply'),
            settings=_settings(condenser_purifier_x_replies=3),
        )
    ).html
    replies = _section(html, 'cd-x-replies')
    assert 'it should be the other way' in replies  # 1st
    assert 'liberal tears are the best' in replies  # 2nd
    assert 'Amazing Xeet' in replies  # 3rd
    assert 'Ngl i would switch the logos' not in replies  # 4th
    more = _section(html, 'cd-x-more', '</p>')
    assert 'href="https://x.com/derbederdusler/status/1770888775830262034"' in more  # absolute: not back to us


async def test_nested_replies_hang_under_their_parent_even_out_of_order(env):
    """``replies`` is X's conversation-module layout, not a flat list, and not always in
    tree order: here a reply arrives last though its parent sits mid-page."""
    html = (await _render('x.com', '/xiaoerzhan/status/2099707280845332534', _load('article'))).html
    replies = _section(html, 'cd-x-replies')
    chain = ['老老实实开个香港公司吧', '有机会再去香港开户', 'paypal.cn', '这个好像要注册个公司', '我有自己的香港公司']
    positions = [replies.index(text) for text in chain]
    assert positions == sorted(positions)
    start = replies.index('老老实实开个香港公司吧')
    module = replies[start : replies.index('cd-x-module', start)]
    assert all(text in module for text in chain[1:])


async def test_author_replies_survive_the_cut_and_are_marked(env):
    html = (
        await _render(
            'x.com',
            '/xiaoerzhan/status/2099707280845332534',
            _load('article'),
            settings=_settings(condenser_purifier_x_replies=2),
        )
    ).html
    replies = _section(html, 'cd-x-replies')
    assert '我正卡在出海收款这里' in replies and '好文，mark' in replies  # the top 2
    assert '恭喜跑通收款闭环' not in replies  # 3rd, no author in its thread
    assert '你就是要看清楚地址' in replies  # the author, under the 5th thread
    assert '有机会再去香港开户' in replies  # the author, under the 10th
    assert replies.count('cd-x-badge') == 3


async def test_self_thread_continuation_follows_the_focus_not_the_replies(env):
    html = _body((await _render('x.com', '/JustZht/status/2082691966135845151', _load('self_thread'))).html)
    continuation = html.index('cd-x-continuation')
    assert html.index('cd-x-focus') < continuation < html.index('cd-x-replies')
    assert html.count('href="/p/haotianzheng.com/?t=202607291001"') == 1
    assert '我艹我才知道你是CMU的' in _section(html, 'cd-x-replies')


async def test_sensitive_reply_keeps_its_text_but_hides_its_media_behind_a_tap(env):
    data = _load('article')
    for reply in data['replies']:
        if reply['id'] == '2100401911929393242':
            reply['possibly_sensitive'] = True
    html = (
        await _render(
            'x.com',
            '/xiaoerzhan/status/2099707280845332534',
            data,
            settings=_settings(condenser_purifier_x_replies=50),
        )
    ).html
    assert '你这主页是自己做的吗' in html
    gate = _section(html, '<details class="cd-x-sensitive">', '</details>')
    assert '<img' in gate and '<script' not in gate
    assert html.count('<details class="cd-x-sensitive">') == 1


async def test_text_from_the_api_is_escaped_and_script_urls_are_not_linked(env):
    data = _load('reply')
    status = data['status']
    status['raw_text'] = {
        'text': '<script>alert(1)</script> see https://t.co/evil',
        'display_text_range': [0, 47],
        'facets': [
            {
                'type': 'url',
                'indices': [30, 47],
                'original': 'https://t.co/evil',
                'replacement': 'javascript:alert(1)',
                'display': 'evil.example',
            }
        ],
    }
    status['author']['name'] = '<img src=x onerror=alert(1)>'
    html = (await _render('x.com', '/derbederdusler/status/1770888775830262034', data)).html
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert 'javascript:' not in html
    assert '<img src=x onerror' not in html


# --- router -----------------------------------------------------------------------


def _install(monkeypatch, fetch_x=None, fetch_page=None):
    from condenser.routers import purifier as router

    if fetch_x is not None:
        monkeypatch.setattr(router, '_fetch_x', fetch_x)
    monkeypatch.setattr(router, '_fetch_page', fetch_page or _no_page)


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def test_route_serves_the_x_page(env, monkeypatch):
    _install(monkeypatch, _fx(_load('reply')))
    with TestClient(create_app()) as client:
        _login(client)
        r = client.get('/p/x.com/derbederdusler/status/1770888775830262034?s=20')
        assert r.status_code == 200
        assert r.headers['content-type'].startswith('text/html')
        assert 'cd-x-focus' in r.text


def test_route_failure_is_a_502_page_with_the_original_link_and_no_full_page_offer(env, monkeypatch):
    _install(monkeypatch, _fx({'code': 404, 'status': None}, 404))
    with TestClient(create_app()) as client:
        _login(client)
        r = client.get('/p/x.com/jack/status/20')
        assert r.status_code == 502
        assert 'https://x.com/jack/status/20' in r.text
        assert '整页模式' not in r.text


def test_route_timeout_is_a_502_page(env, monkeypatch):
    async def slow(status_id, settings):
        raise httpx.ReadTimeout('slow')

    _install(monkeypatch, slow)
    with TestClient(create_app()) as client:
        _login(client)
        r = client.get('/p/x.com/jack/status/20')
        assert r.status_code == 502 and 'https://x.com/jack/status/20' in r.text


def test_switched_off_the_route_sends_the_reader_to_the_original_link(env, monkeypatch):
    """``CONDENSER_PURIFIER_X_API_BASE=`` turns the handler off. The rewrite rule stays a
    fact about URL shapes, so a status link can still arrive here (from a page, or from
    the iOS app); readable mode would only scrape x.com's empty shell, so it is sent on."""
    monkeypatch.setenv('CONDENSER_PURIFIER_X_API_BASE', '')
    from condenser.config import get_settings

    get_settings.cache_clear()
    _install(monkeypatch)
    with TestClient(create_app()) as client:
        _login(client)
        r = client.get('/p/x.com/jack/status/20?s=20', follow_redirects=False)
        assert r.status_code == 302
        assert r.headers['location'] == 'https://x.com/jack/status/20?s=20'
