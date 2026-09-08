"""The Purifier — the iOS reading proxy (plan kb/plans/2026-09-07-purifier.md).

``/p/<host>/<path>?<query>`` fetches the target page server-side and hands back a
page that depends on nothing but condenser: scripts stripped, every resource and
link rewritten into ``/pa`` (assets) or ``/p`` (documents). Three renderings:

- ``proxy``: the whole page, sanitized and rewritten. For sites whose structure
  *is* the content (an HN thread's comment tree) — ``MODE_RULES`` picks it.
- ``readable`` (default): readability-lxml's article + the same rewriting, in our
  own template. Images kept, zero quota, no third party.
- ``puremd``: never chosen, only fallen back to — when the upstream refuses
  (403 / 429 / 5xx, non-HTML, transport failure) or the extracted article is too
  short, pure.md's Markdown is rendered instead. It loses images and costs quota,
  which is why it is the fallback and not the default.

This module holds everything that is not HTTP-routing: URL helpers, mode
resolution, the fetch (with its one https→http retry), the lxml sanitizer, CSS /
srcset rewriting, readability extraction, the pure.md client + Markdown render,
the TTL cache and the two orchestrators. ``purifier_html.py`` has the templates;
``routers/purifier.py`` the endpoints, cookies and the error-page boundary.

Two rules the sanitizer keeps: HTML is walked with lxml, **never** regexed
(``text.py`` records why — an unclosed ``<script>`` makes the obvious regex
quadratic), and JS is always dropped unless ``condenser_purifier_allow_js`` says
otherwise, because a /p page runs on condenser's origin and would hand a script
the 30-day reader cookie.
"""

import asyncio
import codecs
import ipaddress
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Optional
from urllib.parse import urljoin, urlsplit

import httpx
import lxml.html
from lxml import etree
from markdown_it import MarkdownIt
from readability import Document

from . import preview, purifier_html
from .config import Settings

Mode = Literal['proxy', 'readable', 'puremd']

# Which hosts render whole-page rather than article-only. A code constant by
# decision (plan §0.7); env overrides can come when a second entry needs one.
MODE_RULES: dict[str, Mode] = {'news.ycombinator.com': 'proxy'}
SELECTABLE_MODES = ('proxy', 'readable')
# Links to these stay as they are inside a rewritten page — they open in the X /
# Telegram app, never in the proxy. Mirrors the iOS side's exclusion list.
EXCLUDED_REWRITE_HOSTS = frozenset({'x.com', 'twitter.com', 't.me'})
_HOST_PREFIXES = ('www.', 'mobile.', 'm.')
CONTROL_PARAMS = ('_pt', '_mode')

# Fetch seam: same shape as preview._fetch_capped, so tests inject one fake for both.
FetchPage = Callable[..., Awaitable[tuple[str, str, bytes]]]
FetchPuremd = Callable[[str, Settings], Awaitable[str]]


class PurifierError(Exception):
    """Base of every expected failure; the router maps subclasses to small HTML pages."""


class BadTargetError(PurifierError):
    """The requested host is one we refuse to fetch (400)."""


class UpstreamFetchError(PurifierError):
    """The upstream answered with an error or could not be reached (502)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class NotHTMLError(PurifierError):
    """A document request landed on something that is not HTML."""


class UnsupportedAssetError(PurifierError):
    """An asset request landed on a type /pa does not pass through (415)."""


class PuremdError(PurifierError):
    """pure.md refused or failed."""


class PuremdUnavailable(PurifierError):
    """No pure.md key configured — the fallback is switched off."""


# --- URL helpers ------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """The upstream page a /p or /pa request names: host (lowercase, port kept),
    raw path and raw query with our control params removed."""

    host: str
    path: str
    query: str
    ticket: Optional[str] = None
    mode_override: Optional[str] = None

    @property
    def url(self) -> str:
        return self.url_with('https')

    def url_with(self, scheme: str) -> str:
        return f'{scheme}://{self.host}{self.path}' + (f'?{self.query}' if self.query else '')

    def own_path(self, kind: str = 'p', extra_query: str = '') -> str:
        """The condenser-side path for this target (root-relative)."""
        query = '&'.join(q for q in (self.query, extra_query) if q)
        return f'/{kind}/{self.host}{self.path}' + (f'?{query}' if query else '')


def split_raw_path(raw_path: str, prefix: str) -> tuple[str, str]:
    """``/p/<host>/<path>`` as received on the wire → (host, path), both undecoded.

    Starlette's route parameters are already percent-decoded, which would turn a
    ``%2F`` in the path into a separator; ``request.scope['raw_path']`` is the
    original bytes, so the split happens here instead.
    """
    rest = raw_path[len(prefix) :] if raw_path.startswith(prefix) else raw_path.lstrip('/')
    host, sep, path = rest.partition('/')
    return host, (sep + path) if sep else ''


def _control_param_re(name: str) -> re.Pattern:
    return re.compile(rf'(?:^|&){re.escape(name)}=([^&]*)')


_CONTROL_RES = {name: _control_param_re(name) for name in CONTROL_PARAMS}


def strip_params(query: str, names: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    """Remove ``names`` from a raw query string, returning the rest **byte-for-byte**
    (no parse_qsl round trip: the site's own params keep their order and encoding)
    plus the values found."""
    found: dict[str, str] = {}
    for name in names:
        pattern = _CONTROL_RES.get(name) or _control_param_re(name)
        for match in pattern.finditer(query):
            found[name] = match.group(1)
        query = pattern.sub('', query)
    return query.lstrip('&'), found


def _hostname(host: str) -> str:
    """``host[:port]`` / ``[v6]:port`` → the bare hostname."""
    if host.startswith('['):
        return host[1 : host.find(']')] if ']' in host else host
    return host.rsplit(':', 1)[0] if host.count(':') == 1 else host


def _is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


_NUMERIC_LABEL_RE = re.compile(r'^(?:0x[0-9a-f]*|[0-9]+)$')


def _is_numeric_name(name: str) -> bool:
    """``127.1`` / ``0x7f.1`` / ``0177.0.0.1``: not IP literals to ``ipaddress``, but the
    socket layer resolves them to 127.0.0.1 (review 2026-09-07 #3). A name whose every
    label is decimal or hex is an address in disguise, never a DNS name."""
    return all(_NUMERIC_LABEL_RE.match(label) for label in name.split('.'))


def host_allowed(host: str, own_hosts: set[str] = frozenset()) -> bool:
    """The guard from plan §1: no bare names, IPs (in any spelling), localhost or
    ourselves. A DNS name that *resolves* to a private address still passes — fuller
    SSRF protection stays out, as in ``preview.py`` (single user, authenticated)."""
    raw_name = _hostname(host)
    name = raw_name.rstrip('.')
    if not name or '.' not in name or name == 'localhost' or name.endswith('.localhost'):
        return False
    if _is_ip(name) or _is_numeric_name(name):
        return False
    if host in own_hosts or name in own_hosts:
        return False
    port = host[len(raw_name) :].lstrip(':') if not host.startswith('[') else host[host.find(']') + 1 :].lstrip(':')
    return not port or port.isdigit()


def parse_target(host: str, raw_path: str, raw_query: str, *, own_hosts: set[str] = frozenset()) -> Target:
    """Route material → ``Target``. Validates the host, strips our control params."""
    host = host.rsplit('@', 1)[-1].lower()
    if not host_allowed(host, own_hosts):
        raise BadTargetError(f'refusing host {host!r}')
    if raw_path and not raw_path.startswith('/'):
        raw_path = '/' + raw_path
    query, controls = strip_params(raw_query or '', CONTROL_PARAMS)
    mode = controls.get('_mode')
    return Target(
        host=host,
        path=raw_path,
        query=query,
        ticket=controls.get('_pt') or None,
        mode_override=mode if mode in SELECTABLE_MODES else None,
    )


def _bare_host(netloc: str) -> str:
    name = _hostname(netloc.rsplit('@', 1)[-1].lower())
    for prefix in _HOST_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def rewrite_url(href: str, base_url: str, own_origin: str, kind: Literal['p', 'pa']) -> str:
    """One decision every attribute shares.

    Empty / fragment / non-http(s) → untouched. Excluded hosts (X, Telegram),
    condenser itself (already ``/p`` / ``/pa`` / ``/api`` — never wrapped twice) and
    hosts we would refuse anyway → the absolute URL, unwrapped. Everything else →
    root-relative ``/{kind}/host/path?q#f``.
    """
    raw = href.strip()
    if not raw or raw.startswith('#'):
        return href
    absolute = urljoin(base_url, raw)
    parts = urlsplit(absolute)
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        return href
    netloc = parts.netloc.rsplit('@', 1)[-1].lower()
    own = urlsplit(own_origin)
    if netloc == own.netloc.lower() or _bare_host(netloc) in EXCLUDED_REWRITE_HOSTS or not host_allowed(netloc):
        return absolute
    out = f'/{kind}/{netloc}{parts.path}'
    if parts.query:
        out += f'?{parts.query}'
    if parts.fragment:
        out += f'#{parts.fragment}'
    return out


_BASE_RE = re.compile(r'<base\b[^>]*?\bhref\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', re.I)


def resolve_base(raw_html: str, final_url: str) -> str:
    """The URL relative links resolve against: ``<base href>`` if the page has one, else
    the URL the fetch ended on. Looked up in the head only; a ``<base>`` after the
    first 64KB is not one browsers honor either."""
    match = _BASE_RE.search(raw_html[:65536])
    if not match:
        return final_url
    href = next(g for g in match.groups() if g is not None)
    return urljoin(final_url, href.strip())


def resolve_mode(host: str, override: Optional[str]) -> Mode:
    """Explicit ``_mode`` (proxy / readable only) > ``MODE_RULES`` > readable."""
    if override in SELECTABLE_MODES:
        return override  # type: ignore[return-value]
    return MODE_RULES.get(_hostname(host.lower()), 'readable')


# --- CSS / srcset -----------------------------------------------------------

_CSS_URL_RE = re.compile(r'url\(\s*(?P<q>["\']?)(?P<u>[^"\')]*)(?P=q)\s*\)', re.I)
_CSS_IMPORT_RE = re.compile(r'@import\s+(?P<q>["\'])(?P<u>[^"\']*)(?P=q)', re.I)
# Exact-match attribute selectors on the attributes we rewrite in the HTML.
# Prefix / suffix / substring forms (^= $= *=) are deliberately not touched.
_CSS_ATTR_RE = re.compile(r'\[(?P<a>src|href|poster)\s*=\s*(?P<q>["\']?)(?P<u>[^"\'\]]+)(?P=q)\s*\]', re.I)
_CSS_ATTR_KIND = {'src': 'pa', 'poster': 'pa', 'href': 'p'}


def rewrite_css(css: str, base_url: str, own_origin: str) -> str:
    """``url()`` and string-form ``@import`` → ``/pa``; ``data:`` passes through (rewrite_url
    leaves non-http schemes alone). Quote style is preserved.

    Attribute selectors follow the same rule: HN's mobile stylesheet shrinks its
    indent spacers with ``img[src='s.gif'][width='40'] { width: 12px }``, and once
    the HTML's ``src`` reads ``/pa/…/s.gif`` those selectors match nothing — a
    thread came out 558px wide on a 390px phone (2026-09-07). The selector value is
    resolved against the same base as the attribute, so the two stay equal.
    """

    def _url(m: re.Match) -> str:
        q = m.group('q')
        return f'url({q}{rewrite_url(m.group("u"), base_url, own_origin, "pa")}{q})'

    def _import(m: re.Match) -> str:
        q = m.group('q')
        return f'@import {q}{rewrite_url(m.group("u"), base_url, own_origin, "pa")}{q}'

    def _attr(m: re.Match) -> str:
        attr, q = m.group('a'), m.group('q')
        kind = _CSS_ATTR_KIND[attr.lower()]
        return f'[{attr}={q}{rewrite_url(m.group("u"), base_url, own_origin, kind)}{q}]'

    return _CSS_ATTR_RE.sub(_attr, _CSS_IMPORT_RE.sub(_import, _CSS_URL_RE.sub(_url, css)))


def rewrite_srcset(value: str, base_url: str, own_origin: str) -> str:
    """Each candidate's URL rewritten, its descriptor (``1x`` / ``640w``) kept."""
    out = []
    for candidate in value.split(','):
        candidate = candidate.strip()
        if not candidate:
            continue
        url, _, descriptor = candidate.partition(' ')
        rewritten = rewrite_url(url, base_url, own_origin, 'pa')
        out.append(f'{rewritten} {descriptor.strip()}'.strip())
    return ', '.join(out)


# --- the sanitizer ----------------------------------------------------------


@dataclass(frozen=True)
class Toolbar:
    original_url: str
    mode: Mode
    full_page_url: Optional[str]


_DROP_TAGS = frozenset({'iframe', 'base'})
# Unwrapped rather than removed: their children are fallback content a browser
# without the plugin would show anyway — and libxml2 does not know <embed> is
# void, so it nests the rest of the page inside one (measured: the whole body).
_UNWRAP_TAGS = frozenset({'object', 'embed', 'applet', 'noscript'})
_DROP_LINK_RELS = frozenset({'preload', 'prefetch', 'preconnect', 'dns-prefetch', 'modulepreload', 'prerender'})
_DROP_META_EQUIV = frozenset({'refresh', 'content-security-policy'})
_ASSET_LINK_RELS = frozenset(
    {'stylesheet', 'icon', 'shortcut icon', 'apple-touch-icon', 'apple-touch-icon-precomposed'}
)
# Media the asset proxy would refuse: absolutized rather than left broken.
_MEDIA_SRC_TAGS = frozenset({'video', 'audio', 'track'})
_LAZY_SRC_ATTRS = ('data-src', 'data-lazy-src', 'data-original')


def _clean_tree(root, base_url: str, own_origin: str, *, allow_js: bool) -> None:
    """The one lxml walk shared by proxy mode and readable fragments."""
    doomed = []
    unwrap = []
    for el in root.iter():
        if not isinstance(el.tag, str):  # comments / processing instructions
            if el.tag is etree.Comment or el.tag is etree.ProcessingInstruction:
                doomed.append(el)
            continue
        tag = el.tag.lower()
        if tag == 'script' and not allow_js:
            doomed.append(el)
            continue
        if tag in _DROP_TAGS:
            doomed.append(el)
            continue
        if tag in _UNWRAP_TAGS:
            unwrap.append(el)
            continue
        if tag == 'meta' and (el.get('http-equiv') or '').strip().lower() in _DROP_META_EQUIV:
            doomed.append(el)
            continue
        if tag == 'link' and _link_rels(el) & _DROP_LINK_RELS:
            doomed.append(el)
            continue
        _clean_attributes(el, tag, base_url, own_origin)
    for el in doomed:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    # Unwrapped *after* the walk (their children were already cleaned). <noscript>
    # is here too: scripts never run on a /p page, so its fallback content is the
    # content — that is how a lazy-loading site's real <img> comes back.
    for el in unwrap:
        if el.getparent() is not None:
            el.drop_tag()


def _link_rels(el) -> set[str]:
    return {r for r in (el.get('rel') or '').lower().split()}


# Attributes a browser treats as a URL. Every one of them is checked for a script
# scheme *before* any rewriting: ``rewrite_url`` returns non-http(s) values as they
# are (``mailto:``, ``data:`` images), which is exactly how ``javascript:`` in
# ``action`` / ``formaction`` / SVG's ``xlink:href`` walked through the sanitizer
# untouched (review 2026-09-07 #1). lxml keeps ``xlink:href`` as a literal attribute
# name, so the check goes by the local name after the colon.
_URL_ATTRS = frozenset({'href', 'src', 'action', 'formaction', 'poster', 'background', 'cite', 'longdesc', 'data'})
_SCRIPT_SCHEMES = ('javascript:', 'vbscript:')
# Navigation targets (as opposed to image sources) must not be data: URLs either —
# a data:text/html document is a script container.
_NAVIGATION_ATTRS = frozenset({'href', 'action', 'formaction'})
_ATTR_NOISE_RE = re.compile(r'[\x00-\x20\x7f]')


def _local_attr(name: str) -> str:
    """``xlink:href`` → ``href``; the namespace prefix is not what a browser acts on."""
    return name.lower().rpartition(':')[2]


def _is_script_url(value: str, *, navigation: bool) -> bool:
    """Browsers strip ASCII whitespace / control characters inside the scheme, so
    ``java\\tscript:`` is ``javascript:``; compare after doing the same."""
    scheme = _ATTR_NOISE_RE.sub('', value).lower()
    if scheme.startswith(_SCRIPT_SCHEMES):
        return True
    return navigation and scheme.startswith('data:')


def _clean_attributes(el, tag: str, base_url: str, own_origin: str) -> None:
    for name, value in list(el.attrib.items()):
        lname = name.lower()
        local = _local_attr(name)
        if lname.startswith('on') or lname in ('integrity', 'ping', 'nonce'):
            del el.attrib[name]
        elif local in _URL_ATTRS and _is_script_url(value, navigation=local in _NAVIGATION_ATTRS):
            del el.attrib[name]
    if tag == 'img':
        _promote_lazy(el)
    for name, value in list(el.attrib.items()):
        lname = name.lower()
        local = _local_attr(name)
        if lname == 'style':
            el.set(name, rewrite_css(value, base_url, own_origin))
        elif lname == 'srcset':
            el.set(name, rewrite_srcset(value, base_url, own_origin))
        elif local == 'href':
            _rewrite_href(el, tag, name, value, base_url, own_origin)
        elif lname == 'src':
            if tag in _MEDIA_SRC_TAGS or tag == 'script':
                el.set(name, urljoin(base_url, value.strip()))
            elif tag == 'source' and _in_media(el):
                el.set(name, urljoin(base_url, value.strip()))
            else:
                el.set(name, rewrite_url(value, base_url, own_origin, 'pa'))
        elif lname == 'poster':
            el.set(name, rewrite_url(value, base_url, own_origin, 'pa'))
        elif lname in ('action', 'formaction'):
            el.set(name, rewrite_url(value, base_url, own_origin, 'p'))
    if tag == 'style' and el.text:
        el.text = rewrite_css(el.text, base_url, own_origin)


def _rewrite_href(el, tag: str, name: str, value: str, base_url: str, own_origin: str) -> None:
    if tag == 'image':  # SVG <image xlink:href>: an asset, not a document
        el.set(name, rewrite_url(value, base_url, own_origin, 'pa'))
        return
    if tag == 'link':
        rels = _link_rels(el)
        if rels & _ASSET_LINK_RELS:
            el.set(name, rewrite_url(value, base_url, own_origin, 'pa'))
        else:
            el.set(name, urljoin(base_url, value.strip()))
        return
    el.set(name, rewrite_url(value, base_url, own_origin, 'p'))


def _in_media(el) -> bool:
    parent = el.getparent()
    return parent is not None and isinstance(parent.tag, str) and parent.tag.lower() in _MEDIA_SRC_TAGS


def _promote_lazy(el) -> None:
    """A lazy-loaded image's real URL lives in ``data-src`` and JS was going to move
    it; we drop JS, so we do the move. Only when ``src`` is absent or a placeholder."""
    src = (el.get('src') or '').strip()
    if src and not src.startswith('data:'):
        return
    for attr in _LAZY_SRC_ATTRS:
        real = (el.get(attr) or '').strip()
        if real:
            el.set('src', real)
            break
    else:
        return
    if not el.get('srcset') and el.get('data-srcset'):
        el.set('srcset', el.get('data-srcset'))


def sanitize_and_rewrite_proxy(
    html: str, base_url: str, own_origin: str, *, allow_js: bool = False, toolbar: Optional[Toolbar] = None
) -> str:
    """Whole-page mode: strip, rewrite, add viewport + toolbar, serialize."""
    root = lxml.html.document_fromstring(html)
    _clean_tree(root, base_url, own_origin, allow_js=allow_js)
    head = root.find('head')
    if head is None:
        head = lxml.html.Element('head')
        root.insert(0, head)
    if not any(m.get('name', '').lower() == 'viewport' for m in head.iter('meta')):
        viewport = lxml.html.Element('meta', name='viewport', content='width=device-width, initial-scale=1')
        head.insert(0, viewport)
    style = lxml.html.Element('style')
    style.text = purifier_html.TOOLBAR_CSS
    head.insert(0, style)
    if toolbar is not None:
        body = root.find('body')
        if body is None:
            body = lxml.html.Element('body')
            root.append(body)
        bar = lxml.html.fragment_fromstring(
            purifier_html.toolbar_html(toolbar.original_url, toolbar.mode, toolbar.full_page_url)
        )
        bar.tail = body.text
        body.text = None
        body.insert(0, bar)
    return lxml.html.tostring(root, encoding='unicode', doctype='<!DOCTYPE html>')


def sanitize_and_rewrite_fragment(body_html: str, base_url: str, own_origin: str) -> str:
    """The same walk over a fragment (readability's output, pure.md's Markdown render)."""
    root = lxml.html.fragment_fromstring(body_html, create_parent='div')
    _clean_tree(root, base_url, own_origin, allow_js=False)
    return (root.text or '') + ''.join(lxml.html.tostring(child, encoding='unicode') for child in root)


# --- readable ---------------------------------------------------------------


def _text_chars(html: str) -> int:
    root = lxml.html.fragment_fromstring(html, create_parent='div')
    return len(re.sub(r'\s+', ' ', root.text_content()).strip())


def extract_readable(html: str, base_url: str, own_origin: str) -> Optional[tuple[str, str, int]]:
    """readability's article → (title, sanitized+rewritten body, prose char count).

    readability leaves relative URLs relative, so the fragment goes through the same
    rewrite against the same base as proxy mode would use. None when nothing parses.
    """
    if not html.strip():
        return None
    try:
        doc = Document(html)
        body = doc.summary(html_partial=True)
        title = doc.short_title()
    except Exception:  # noqa: BLE001 - readability raises its own Unparseable plus lxml's
        return None
    if not body.strip():
        return None
    cleaned = sanitize_and_rewrite_fragment(body, base_url, own_origin)
    return title or '', cleaned, _text_chars(cleaned)


# --- pure.md ----------------------------------------------------------------

PUREMD_ENDPOINT = 'https://pure.md/'
_IMAGE_PLACEHOLDER_RE = re.compile(r'!\[([^\]]*)\]\(IMAGE\)')


def parse_puremd(raw: str) -> tuple[Optional[str], Optional[str], str]:
    """pure.md's ``text/plain``: a YAML frontmatter of three flat keys, then Markdown.
    Hand-parsed — three ``key: value`` lines are not worth a yaml dependency."""
    if not raw.startswith('---'):
        return None, None, raw
    end = raw.find('\n---', 3)
    if end < 0:
        return None, None, raw
    fields: dict[str, str] = {}
    for line in raw[3:end].splitlines():
        key, sep, value = line.partition(':')
        if sep:
            fields[key.strip().lower()] = _unquote(value.strip())
    body = raw[end + 4 :].lstrip('\n')
    return fields.get('title') or None, fields.get('description') or None, body


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        return value[1:-1]
    return value


_markdown = MarkdownIt('commonmark').enable('table').enable('strikethrough')


def render_puremd_html(markdown: str) -> str:
    """Markdown → HTML. The ``![alt](IMAGE)`` placeholders become their alt text
    *before* rendering (pure.md drops image URLs; an ``<img src="IMAGE">`` would be
    a broken box)."""
    return _markdown.render(_IMAGE_PLACEHOLDER_RE.sub(r'\1', markdown))


async def fetch_puremd(url: str, settings: Settings) -> str:
    """``GET https://pure.md/<url>`` with the API token. 429 is not retried."""
    headers = {
        'x-puremd-api-token': settings.condenser_puremd_api_key,
        'User-Agent': settings.condenser_preview_user_agent,
    }
    async with httpx.AsyncClient(
        headers=headers, timeout=max(settings.condenser_preview_fetch_timeout, 20.0)
    ) as client:
        resp = await client.get(PUREMD_ENDPOINT + url)
    if resp.status_code != 200:
        raise PuremdError(f'pure.md HTTP {resp.status_code}')
    return resp.text


# --- fetch ------------------------------------------------------------------


async def fetch_page(
    url: str, settings: Settings, *, cap: int, accept: Callable[[str], bool]
) -> tuple[str, str, bytes]:
    """``preview._fetch_capped`` with the scheme rule from plan §1: https first, and
    only a **transport-level** failure (connect error / connect timeout) earns one
    http retry. An HTTP status error or a read timeout is the site's real answer."""
    try:
        return await _fetch_once(url, settings, cap=cap, accept=accept)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        if not url.startswith('https://'):
            raise UpstreamFetchError(preview._error_message(exc)) from exc
        try:
            return await _fetch_once('http://' + url[len('https://') :], settings, cap=cap, accept=accept)
        except (httpx.ConnectError, httpx.ConnectTimeout) as retry_exc:
            raise UpstreamFetchError(preview._error_message(retry_exc)) from retry_exc


async def _fetch_once(
    url: str, settings: Settings, *, cap: int, accept: Callable[[str], bool]
) -> tuple[str, str, bytes]:
    try:
        return await preview._fetch_capped(url, settings, cap=cap, accept=accept)
    except httpx.HTTPStatusError as exc:
        raise UpstreamFetchError(f'HTTP {exc.response.status_code}', status=exc.response.status_code) from exc
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise
    except httpx.HTTPError as exc:
        raise UpstreamFetchError(preview._error_message(exc)) from exc


_META_CHARSET_RE = re.compile(rb'<meta[^>]+charset\s*=\s*["\']?\s*([A-Za-z0-9_\-:.]+)', re.I)


def detect_charset(raw: bytes, content_type: str) -> str:
    """Header charset > ``<meta charset>`` / ``http-equiv`` in the first 2KB > utf-8.
    One step more than ``preview._charset``: CJK sites often declare it only in the
    document."""
    for part in content_type.split(';')[1:]:
        key, _, value = part.strip().partition('=')
        if key.strip().lower() == 'charset' and _known_codec(value.strip().strip('"\'')):
            return value.strip().strip('"\'').lower()
    match = _META_CHARSET_RE.search(raw[:2048])
    if match:
        name = match.group(1).decode('ascii', 'replace')
        if _known_codec(name):
            return name.lower()
    return 'utf-8'


def _known_codec(name: str) -> bool:
    if not name:
        return False
    try:
        codecs.lookup(name)
    except LookupError:
        return False
    return True


def _is_html(content_type: str) -> bool:
    mime = content_type.split(';')[0].strip().lower()
    return not mime or 'html' in mime or mime == 'text/plain'


_ASSET_MIMES = frozenset(
    {
        'text/css',
        'application/font-woff',
        'application/font-woff2',
        'application/x-font-woff',
        'application/x-font-ttf',
        'application/x-font-otf',
        'application/font-sfnt',
        'application/vnd.ms-fontobject',
    }
)


def asset_type_allowed(content_type: str) -> bool:
    mime = content_type.split(';')[0].strip().lower()
    return mime.startswith('image/') or mime.startswith('font/') or mime in _ASSET_MIMES


# The orchestrators take `fetch_page=` / `fetch_puremd=` parameters named after the
# functions they replace (plan §4.3), so the defaults are bound under other names.
_DEFAULT_FETCH_PAGE = fetch_page
_DEFAULT_FETCH_PUREMD = fetch_puremd


# --- cache ------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentResult:
    html: str
    mode: Mode


@dataclass(frozen=True)
class AssetResult:
    body: bytes
    content_type: str


_cache: dict[tuple[str, str], tuple[float, DocumentResult]] = {}
_clock = time.monotonic


def clear_cache() -> None:
    _cache.clear()


def _cache_get(key: tuple[str, str]) -> Optional[DocumentResult]:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires, result = entry
    if expires <= _clock():
        del _cache[key]
        return None
    return result


def _cache_put(key: tuple[str, str], result: DocumentResult, ttl: int) -> None:
    if ttl <= 0:
        return
    if len(_cache) >= 256:  # a bound, not an eviction policy: this is one reader's session
        oldest = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest]
    _cache[key] = (_clock() + ttl, result)


# --- orchestration ----------------------------------------------------------


@dataclass
class _Fetched:
    final_url: str
    html: str
    base_url: str


async def _fetch_document(target: Target, settings: Settings, fetch: FetchPage) -> _Fetched:
    try:
        final_url, ctype, raw = await fetch(
            target.url, settings, cap=settings.condenser_purifier_max_bytes, accept=_is_html
        )
    except preview.PreviewError as exc:
        raise NotHTMLError(str(exc)) from exc
    if not _is_html(ctype):
        raise NotHTMLError(f'not html: {ctype}')
    html = raw.decode(detect_charset(raw, ctype), errors='replace')
    return _Fetched(final_url=final_url, html=html, base_url=resolve_base(html, final_url))


async def render_document(
    target: Target,
    settings: Settings,
    *,
    own_origin: str,
    mode_override: Optional[str] = None,
    fetch_page: Optional[FetchPage] = None,
    fetch_puremd: Optional[FetchPuremd] = None,
) -> DocumentResult:
    """A /p request → the page to serve. Cached per (upstream URL, mode).

    proxy mode lets fetch errors propagate (the router renders them); readable mode
    is this module's one broad-catch boundary — whatever fails on the way to an
    article becomes the reason to try pure.md.
    """
    mode = resolve_mode(target.host, mode_override or target.mode_override)
    key = (target.url, mode)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    fetch = fetch_page or _DEFAULT_FETCH_PAGE
    if mode == 'proxy':
        result = await _render_proxy(target, settings, own_origin, fetch)
    else:
        result = await _render_readable(target, settings, own_origin, fetch, fetch_puremd or _DEFAULT_FETCH_PUREMD)
    _cache_put(key, result, settings.condenser_purifier_cache_ttl)
    return result


async def _render_proxy(target: Target, settings: Settings, own_origin: str, fetch: FetchPage) -> DocumentResult:
    fetched = await _fetch_document(target, settings, fetch)
    toolbar = Toolbar(original_url=fetched.final_url, mode='proxy', full_page_url=None)
    html = await asyncio.to_thread(
        sanitize_and_rewrite_proxy,
        fetched.html,
        fetched.base_url,
        own_origin,
        allow_js=settings.condenser_purifier_allow_js,
        toolbar=toolbar,
    )
    return DocumentResult(html=html, mode='proxy')


async def _render_readable(
    target: Target, settings: Settings, own_origin: str, fetch: FetchPage, puremd: FetchPuremd
) -> DocumentResult:
    full_page_url = target.own_path('p', '_mode=proxy')
    original_url = target.url
    extracted: Optional[tuple[str, str, int]] = None
    reason = ''
    try:
        fetched = await _fetch_document(target, settings, fetch)
        original_url = fetched.final_url
        extracted = await asyncio.to_thread(extract_readable, fetched.html, fetched.base_url, own_origin)
        if extracted is None:
            reason = 'no article found'
    except Exception as exc:  # noqa: BLE001 - the boundary: any failure here is why we fall back
        reason = str(exc) or type(exc).__name__

    long_enough = extracted is not None and extracted[2] >= settings.condenser_purifier_min_readable_chars
    toolbar = Toolbar(original_url=original_url, mode='readable', full_page_url=full_page_url)
    if long_enough:
        title, body, _chars = extracted
        return DocumentResult(
            html=purifier_html.reader_page(
                title=title or target.host, body_html=body, toolbar=toolbar, notice=None, site=target.host
            ),
            mode='readable',
        )

    if settings.condenser_puremd_api_key:
        try:
            return await _render_puremd(target, settings, own_origin, puremd, toolbar)
        except Exception as exc:  # noqa: BLE001 - same boundary: the fallback failing is one more reason
            reason = f'{reason}; pure.md: {exc}' if reason else f'pure.md: {exc}'

    if extracted is not None:
        title, body, _chars = extracted
        notice = (
            '正文可能不完整：自动抽取到的内容很少'
            + ('，pure.md 兜底也失败了' if settings.condenser_puremd_api_key else '')
            + '。可以试试整页模式。'
        )
        return DocumentResult(
            html=purifier_html.reader_page(
                title=title or target.host, body_html=body, toolbar=toolbar, notice=notice, site=target.host
            ),
            mode='readable',
        )
    raise UpstreamFetchError(reason or 'could not render')


async def _render_puremd(
    target: Target, settings: Settings, own_origin: str, puremd: FetchPuremd, toolbar: Toolbar
) -> DocumentResult:
    raw = await puremd(target.url, settings)
    title, _description, markdown = parse_puremd(raw)
    body = sanitize_and_rewrite_fragment(render_puremd_html(markdown), target.url, own_origin)
    bar = Toolbar(original_url=toolbar.original_url, mode='puremd', full_page_url=toolbar.full_page_url)
    return DocumentResult(
        html=purifier_html.reader_page(
            title=title or target.host, body_html=body, toolbar=bar, notice=None, site=target.host
        ),
        mode='puremd',
    )


async def render_asset(
    target: Target, settings: Settings, *, own_origin: str, fetch_page: Optional[FetchPage] = None
) -> AssetResult:
    """A /pa request → bytes to pass through. Deliberately not a fourth document mode:
    CSS is rewritten (against the stylesheet's **own** final URL, not the page's) but
    never parsed as HTML, and image bytes are touched by nothing."""
    fetch = fetch_page or _DEFAULT_FETCH_PAGE
    try:
        final_url, ctype, raw = await fetch(
            target.url, settings, cap=settings.condenser_preview_image_max_bytes, accept=asset_type_allowed
        )
    except preview.PreviewError as exc:
        raise UnsupportedAssetError(str(exc)) from exc
    if not asset_type_allowed(ctype):
        raise UnsupportedAssetError(f'unsupported asset type: {ctype}')
    mime = ctype.split(';')[0].strip().lower()
    if mime == 'text/css':
        css = raw.decode(detect_charset(raw, ctype), errors='replace')
        return AssetResult(rewrite_css(css, final_url, own_origin).encode('utf-8'), 'text/css; charset=utf-8')
    return AssetResult(raw, mime)
