#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Pick a subset of an OPML file in the browser and download the result.

    uv run scripts/opml_picker.py ~/Downloads/PocketCasts.opml

The script parses the OPML, serves a one-page checkbox UI on localhost, opens a
browser at it, and turns the checked rows into a new OPML that the browser
downloads. The server keeps running, so several subsets can be generated from
one run; Ctrl-C stops it.

Two decisions worth knowing:

* Feed outlines keep their **original attributes** (``type`` / ``htmlUrl`` /
  anything a reader wrote), and the group nesting they were found under is
  rebuilt in the output — a group is emitted only when a feed of it survived.
  The point of the tool is to remove feeds, so nothing else may change.
* Stdlib only (``http.server``), so the script starts with no install step and
  no network access at all. It is a single-user local tool; that is the whole
  threat model, but titles are still escaped on the way into the HTML because
  an OPML is somebody else's file.
"""

from __future__ import annotations

import argparse
import html
import io
import sys
import threading
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class OpmlError(Exception):
    """The input is not an OPML file we can read."""


@dataclass
class Feed:
    id: str
    title: str
    xml_url: str
    group: tuple[str, ...]
    attrib: dict[str, str] = field(default_factory=dict)

    @property
    def group_label(self) -> str:
        return ' / '.join(self.group)


@dataclass
class OpmlDocument:
    title: str
    feeds: list[Feed]


# --- parsing ---------------------------------------------------------------


def parse_opml(text: str) -> OpmlDocument:
    try:
        _register_namespaces(text)
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise OpmlError(f'not valid XML: {exc}') from exc
    if root.tag != 'opml':
        raise OpmlError(f'root element is <{root.tag}>, expected <opml>')
    body = root.find('body')
    if body is None:
        raise OpmlError('no <body> element')

    feeds: list[Feed] = []
    _collect(body, (), feeds)
    if not feeds:
        raise OpmlError('no outline carries an xmlUrl — nothing to pick from')
    return OpmlDocument(title=_head_title(root), feeds=feeds)


def _collect(node: ET.Element, group: tuple[str, ...], feeds: list[Feed]) -> None:
    """Walk outlines depth-first; an outline with an xmlUrl is a feed, others are groups."""
    for outline in node.findall('outline'):
        url = outline.get('xmlUrl')
        if url:
            feeds.append(
                Feed(
                    id=f'f{len(feeds)}',
                    title=outline.get('text') or outline.get('title') or url,
                    xml_url=url,
                    group=group,
                    attrib=dict(outline.attrib),
                )
            )
        elif len(outline):
            name = outline.get('text') or outline.get('title') or ''
            _collect(outline, group + (name,), feeds)


def _register_namespaces(text: str) -> None:
    """Keep the source's prefixes on the output.

    ElementTree stores a namespaced attribute as ``{uri}name`` and, unless the
    prefix is registered, re-serializes it as ``ns0:name``. Miniflux exports
    per-feed settings as ``miniflux:crawler`` and friends; renaming the prefix is
    still valid XML, but the file stops looking like the one the reader wrote.
    Registration is process-global, which a single-file script can afford.
    """
    for _, (prefix, uri) in ET.iterparse(io.StringIO(text), events=('start-ns',)):
        ET.register_namespace(prefix, uri)


def _head_title(root: ET.Element) -> str:
    node = root.find('head/title')
    if node is not None and node.text:
        return node.text.strip()
    return 'Subscriptions'


# --- generating ------------------------------------------------------------


def build_opml(doc: OpmlDocument, feeds: list[Feed]) -> str:
    root = ET.Element('opml', {'version': '2.0'})
    head = ET.SubElement(root, 'head')
    ET.SubElement(head, 'title').text = doc.title
    body = ET.SubElement(root, 'body')

    # Group containers are created on first use, so a group whose feeds were all
    # unchecked never reaches the output.
    containers: dict[tuple[str, ...], ET.Element] = {(): body}
    for feed in feeds:
        ET.SubElement(_container(containers, feed.group), 'outline', feed.attrib)

    ET.indent(root, space='  ')
    return ET.tostring(root, encoding='unicode', xml_declaration=True) + '\n'


def _container(containers: dict[tuple[str, ...], ET.Element], group: tuple[str, ...]) -> ET.Element:
    if group not in containers:
        parent = _container(containers, group[:-1])
        containers[group] = ET.SubElement(parent, 'outline', {'text': group[-1], 'title': group[-1]})
    return containers[group]


# --- web UI ----------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OPML 选择器 — {file}</title>
<style>
  :root {{ color-scheme: light dark; --line: #8883; --muted: #8888; --accent: #3b82f6; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  header {{ position: sticky; top: 0; z-index: 2; padding: 12px 20px;
           border-bottom: 1px solid var(--line); backdrop-filter: blur(12px);
           background: color-mix(in srgb, Canvas 85%, transparent); }}
  .bar {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
  h1 {{ font-size: 15px; margin: 0; font-weight: 600; }}
  .file {{ color: var(--muted); font-weight: 400; margin-left: 8px; }}
  .spacer {{ flex: 1; }}
  input[type=search] {{ padding: 6px 10px; border: 1px solid var(--line); border-radius: 8px;
                        background: transparent; color: inherit; min-width: 180px; }}
  button {{ padding: 6px 12px; border: 1px solid var(--line); border-radius: 8px;
            background: transparent; color: inherit; cursor: pointer; font: inherit; }}
  button:hover {{ border-color: var(--accent); }}
  button.primary {{ background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }}
  #count {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
  .hint {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
  main {{ padding: 8px 20px 64px; max-width: 900px; }}
  h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted);
        margin: 22px 0 6px; font-weight: 600; }}
  h2 label {{ display: inline-flex; gap: 8px; align-items: center; cursor: pointer; }}
  .n {{ font-weight: 400; opacity: .7; }}
  .n::before {{ content: "("; }}
  .n::after {{ content: ")"; }}
  ul {{ list-style: none; margin: 0; padding: 0; }}
  li label {{ display: flex; gap: 10px; align-items: baseline; padding: 6px 8px;
              border-radius: 8px; cursor: pointer; }}
  li label:hover {{ background: color-mix(in srgb, CanvasText 6%, transparent); }}
  .t {{ font-weight: 500; }}
  /* No direction:rtl for the ellipsis trick — bidi reorders a trailing "/" to the
     front of the URL, which reads as a different address. */
  .u {{ color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis;
        white-space: nowrap; flex: 1; min-width: 0; }}
  .hidden {{ display: none; }}
</style>
</head>
<body>
<form method="post" action="/generate" id="form">
  <header>
    <div class="bar">
      <h1>OPML 选择器<span class="file">{file}</span></h1>
      <div class="spacer"></div>
      <input type="search" id="q" placeholder="过滤标题或地址…" autocomplete="off">
      <button type="button" id="all">全选</button>
      <button type="button" id="none">取消全选</button>
      <span id="count"></span>
      <button type="submit" class="primary">生成</button>
    </div>
    <div class="hint">共 {total} 个订阅源。全选 / 取消全选 只作用于当前过滤结果；生成后浏览器直接下载新的 OPML。</div>
  </header>
  <main>{groups}</main>
</form>
<script>
const rows = [...document.querySelectorAll('li')];
const boxes = [...document.querySelectorAll('input[name=feed]')];
const count = document.getElementById('count');
const visible = () => rows.filter(r => !r.classList.contains('hidden'))
                         .map(r => r.querySelector('input[name=feed]'));

// The group box carries data-gid, its feeds data-group — one attribute for both
// would make every group box count itself as an unchecked member of its group.
const members = gid => [...document.querySelectorAll(`input[name=feed][data-group="${{gid}}"]`)];

function sync() {{
  count.textContent = `已选 ${{boxes.filter(b => b.checked).length}} / ${{boxes.length}}`;
  document.querySelectorAll('.gbox').forEach(g => {{
    const kids = members(g.dataset.gid);
    const on = kids.filter(k => k.checked).length;
    g.checked = on === kids.length;
    g.indeterminate = on > 0 && on < kids.length;
  }});
}}

document.getElementById('all').onclick = () => {{ visible().forEach(b => b.checked = true); sync(); }};
document.getElementById('none').onclick = () => {{ visible().forEach(b => b.checked = false); sync(); }};
document.querySelectorAll('.gbox').forEach(g => g.onchange = () => {{
  members(g.dataset.gid).forEach(k => k.checked = g.checked);
  sync();
}});
boxes.forEach(b => b.onchange = sync);

const q = document.getElementById('q');
q.oninput = () => {{
  const needle = q.value.trim().toLowerCase();
  rows.forEach(r => r.classList.toggle('hidden', !!needle && !r.dataset.search.includes(needle)));
  document.querySelectorAll('section').forEach(s => s.classList.toggle(
    'hidden', ![...s.querySelectorAll('li')].some(r => !r.classList.contains('hidden'))));
}};
// Enter in the search box would submit the form and start a download.
q.onkeydown = e => {{ if (e.key === 'Enter') e.preventDefault(); }};

sync();
</script>
</body>
</html>
"""


def render_page(doc: OpmlDocument, source_name: str) -> str:
    return PAGE.format(
        file=html.escape(source_name),
        total=len(doc.feeds),
        groups=_render_groups(doc.feeds),
    )


def _render_groups(feeds: list[Feed]) -> str:
    order: dict[tuple[str, ...], list[Feed]] = {}
    for feed in feeds:
        order.setdefault(feed.group, []).append(feed)

    chunks = []
    for index, (group, members) in enumerate(order.items()):
        label = html.escape(' / '.join(group)) if group else '未分组'
        rows = '\n'.join(_render_row(f, index) for f in members)
        chunks.append(
            f'<section>\n<h2><label><input type="checkbox" class="gbox" data-gid="g{index}">'
            f'{label}<span class="n">{len(members)}</span></label></h2>\n'
            f'<ul>\n{rows}\n</ul>\n</section>'
        )
    return '\n'.join(chunks)


def _render_row(feed: Feed, group_index: int) -> str:
    title, url = html.escape(feed.title), html.escape(feed.xml_url)
    # The group name joins the haystack so filtering by folder works too.
    search = html.escape(f'{feed.title} {feed.xml_url} {feed.group_label}'.lower(), quote=True)
    return (
        f'<li data-search="{search}"><label>'
        f'<input type="checkbox" name="feed" value="{feed.id}" data-group="g{group_index}">'
        f'<span class="t">{title}</span><span class="u">{url}</span>'
        f'</label></li>'
    )


NOTHING_PICKED = (
    '<!doctype html><meta charset="utf-8">'
    '<body style="font:15px sans-serif;padding:40px">'
    '<p>没有选中任何订阅源，所以没有可生成的 OPML。</p>'
    '<p><a href="/">返回</a></p>'
)


def make_server(doc: OpmlDocument, source_name: str, host: str = '127.0.0.1', port: int = 0):
    by_id = {f.id: f for f in doc.feeds}
    out_name = f'{Path(source_name).stem}-selected.opml'

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            if urllib.parse.urlparse(self.path).path != '/':
                self._send(404, 'text/plain; charset=utf-8', b'not found')
                return
            self._send(200, 'text/html; charset=utf-8', render_page(doc, source_name).encode('utf-8'))

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != '/generate':
                self._send(404, 'text/plain; charset=utf-8', b'not found')
                return
            length = int(self.headers.get('Content-Length') or 0)
            fields = urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8'))
            picked = [by_id[i] for i in fields.get('feed', []) if i in by_id]
            if not picked:
                self._send(400, 'text/html; charset=utf-8', NOTHING_PICKED.encode('utf-8'))
                return
            payload = build_opml(doc, picked).encode('utf-8')
            self._send(
                200,
                'text/x-opml; charset=utf-8',
                payload,
                extra={'Content-Disposition': _attachment(out_name)},
            )
            print(f'  generated {out_name} with {len(picked)} feeds', file=sys.stderr)

        def _send(self, status, content_type, payload, extra=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt, *args):  # keep the console to what the user cares about
            pass

    return ThreadingHTTPServer((host, port), Handler)


def _attachment(name: str) -> str:
    """ASCII fallback plus RFC 5987, so a non-ASCII source filename still downloads."""
    ascii_name = name.encode('ascii', 'replace').decode('ascii').replace('"', '')
    quoted = urllib.parse.quote(name, safe='')
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


# --- entry point -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Pick a subset of an OPML file in the browser.')
    parser.add_argument('opml', type=Path, help='path to the source OPML file')
    parser.add_argument('--port', type=int, default=0, help='port to listen on (default: a free one)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--no-browser', action='store_true', help='do not open a browser')
    args = parser.parse_args(argv)

    try:
        doc = parse_opml(args.opml.read_text(encoding='utf-8'))
    except OSError as exc:
        print(f'cannot read {args.opml}: {exc}', file=sys.stderr)
        return 1
    except OpmlError as exc:
        print(f'{args.opml} is not usable OPML: {exc}', file=sys.stderr)
        return 1

    httpd = make_server(doc, args.opml.name, host=args.host, port=args.port)
    url = f'http://{args.host}:{httpd.server_address[1]}/'
    print(f'{args.opml.name}: {len(doc.feeds)} feeds — {url}', file=sys.stderr)
    print('Ctrl-C to stop.', file=sys.stderr)
    if not args.no_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nbye', file=sys.stderr)
    finally:
        httpd.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
