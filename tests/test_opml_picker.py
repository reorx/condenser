"""Behavior tests for scripts/opml_picker.py — the standalone OPML subset picker.

The script is a PEP 723 uv script, not part of the condenser package, so it is
loaded by path. Nothing here touches the database or the network: the HTTP cases
bind a real server to port 0 on localhost and talk to it with urllib.
"""

import importlib.util
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'opml_picker.py'


def _load():
    spec = importlib.util.spec_from_file_location('opml_picker', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves annotations through sys.modules[cls.__module__].
    sys.modules['opml_picker'] = module
    spec.loader.exec_module(module)
    return module


picker = _load()


FLAT = """<?xml version="1.0" encoding="utf-8"?>
<opml version="1.0">
  <head><title>My Feeds</title></head>
  <body>
    <outline xmlUrl="https://a.example/rss" type="rss" text="A" htmlUrl="https://a.example/"/>
    <outline xmlUrl="https://b.example/rss" type="rss" text="B"/>
  </body>
</opml>
"""

GROUPED = """<?xml version="1.0" encoding="utf-8"?>
<opml version="1.0">
  <head><title>Pocket Casts Feeds</title></head>
  <body>
    <outline text="feeds">
      <outline xmlUrl="https://a.example/rss" type="rss" text="A"/>
      <outline xmlUrl="https://b.example/rss" type="rss" text="B"/>
    </outline>
    <outline text="tech">
      <outline text="python">
        <outline xmlUrl="https://c.example/rss" type="rss" text="C"/>
      </outline>
    </outline>
    <outline xmlUrl="https://d.example/rss" type="rss" text="D"/>
  </body>
</opml>
"""


def feeds_of(opml_text):
    """(group path, title, xmlUrl) triples of every feed outline, document order."""
    root = ET.fromstring(opml_text)
    out = []

    def walk(node, path):
        for child in node.findall('outline'):
            url = child.get('xmlUrl')
            if url:
                out.append((path, child.get('text'), url))
            else:
                walk(child, path + (child.get('text'),))

    walk(root.find('body'), ())
    return out


# --- parsing ---------------------------------------------------------------


def test_parse_flat_opml_reads_title_and_feeds():
    doc = picker.parse_opml(FLAT)
    assert doc.title == 'My Feeds'
    assert [f.title for f in doc.feeds] == ['A', 'B']
    assert [f.xml_url for f in doc.feeds] == ['https://a.example/rss', 'https://b.example/rss']
    assert [f.group for f in doc.feeds] == [(), ()]


def test_parse_keeps_original_attributes_for_round_trip():
    doc = picker.parse_opml(FLAT)
    assert doc.feeds[0].attrib['htmlUrl'] == 'https://a.example/'
    assert doc.feeds[0].attrib['type'] == 'rss'


def test_parse_assigns_stable_unique_ids():
    doc = picker.parse_opml(GROUPED)
    ids = [f.id for f in doc.feeds]
    assert len(set(ids)) == len(ids)
    assert picker.parse_opml(GROUPED).feeds[2].id == doc.feeds[2].id


def test_parse_records_nested_group_paths():
    doc = picker.parse_opml(GROUPED)
    assert [f.group for f in doc.feeds] == [('feeds',), ('feeds',), ('tech', 'python'), ()]


def test_parse_rejects_non_opml_input():
    with pytest.raises(picker.OpmlError):
        picker.parse_opml('<html><body>nope</body></html>')


def test_parse_rejects_malformed_xml():
    with pytest.raises(picker.OpmlError):
        picker.parse_opml('<opml><body>')


def test_parse_falls_back_to_url_when_a_feed_has_no_text():
    doc = picker.parse_opml(
        '<opml><head/><body><outline xmlUrl="https://x.example/rss"/></body></opml>'
    )
    assert doc.feeds[0].title == 'https://x.example/rss'


# --- generating ------------------------------------------------------------


def test_build_keeps_only_the_selected_feeds():
    doc = picker.parse_opml(GROUPED)
    out = picker.build_opml(doc, [doc.feeds[0], doc.feeds[3]])
    assert [t[2] for t in feeds_of(out)] == ['https://a.example/rss', 'https://d.example/rss']


def test_build_preserves_the_group_nesting_of_selected_feeds():
    doc = picker.parse_opml(GROUPED)
    out = picker.build_opml(doc, [doc.feeds[2], doc.feeds[3]])
    assert feeds_of(out) == [
        (('tech', 'python'), 'C', 'https://c.example/rss'),
        ((), 'D', 'https://d.example/rss'),
    ]


def test_build_drops_groups_that_lost_every_feed():
    doc = picker.parse_opml(GROUPED)
    out = picker.build_opml(doc, [doc.feeds[0]])
    assert [o.get('text') for o in ET.fromstring(out).find('body')] == ['feeds']


def test_build_carries_over_head_title_and_feed_attributes():
    doc = picker.parse_opml(FLAT)
    out = picker.build_opml(doc, doc.feeds)
    root = ET.fromstring(out)
    assert root.get('version') == '2.0'
    assert root.find('head/title').text == 'My Feeds'
    first = root.find('body/outline')
    assert first.get('htmlUrl') == 'https://a.example/'
    assert first.get('type') == 'rss'


def test_build_preserves_namespaced_attributes_and_their_prefix():
    # Miniflux exports per-feed settings in its own namespace; a round trip that
    # renamed the prefix or dropped the attribute would lose reader settings.
    doc = picker.parse_opml(
        '<opml version="2.0" xmlns:miniflux="https://miniflux.app/opml">'
        '<head><title>Miniflux</title></head><body>'
        '<outline text="A" xmlUrl="https://a.example/rss" miniflux:crawler="true"/>'
        '</body></opml>'
    )
    out = picker.build_opml(doc, doc.feeds)
    assert 'xmlns:miniflux="https://miniflux.app/opml"' in out
    assert 'miniflux:crawler="true"' in out


def test_build_output_is_parseable_by_the_picker_itself():
    doc = picker.parse_opml(GROUPED)
    again = picker.parse_opml(picker.build_opml(doc, doc.feeds))
    assert [f.xml_url for f in again.feeds] == [f.xml_url for f in doc.feeds]


# --- the web UI ------------------------------------------------------------


@pytest.fixture
def server():
    doc = picker.parse_opml(GROUPED)
    httpd = picker.make_server(doc, 'PocketCasts.opml', host='127.0.0.1', port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{httpd.server_address[1]}'
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def get(base, path='/'):
    with urllib.request.urlopen(base + path) as resp:
        return resp.status, resp.headers, resp.read().decode('utf-8')


def post(base, path, fields):
    data = urllib.parse.urlencode(fields, doseq=True).encode('utf-8')
    req = urllib.request.Request(base + path, data=data)
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.headers, resp.read().decode('utf-8')


def test_index_lists_every_feed_with_its_group(server):
    status, headers, body = get(server)
    assert status == 200
    assert 'text/html' in headers['Content-Type']
    for title in ('A', 'B', 'C', 'D'):
        assert f'>{title}<' in body
    assert 'tech / python' in body
    assert 'PocketCasts.opml' in body


def test_index_escapes_feed_titles(server):
    doc = picker.parse_opml(
        '<opml><head/><body><outline text="&lt;script&gt;x&lt;/script&gt;"'
        ' xmlUrl="https://x.example/rss"/></body></opml>'
    )
    httpd = picker.make_server(doc, 'evil.opml', host='127.0.0.1', port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        _, _, body = get(f'http://127.0.0.1:{httpd.server_address[1]}')
        assert '<script>x</script>' not in body
        assert '&lt;script&gt;' in body
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_generate_downloads_an_opml_of_the_checked_feeds(server):
    doc = picker.parse_opml(GROUPED)
    ids = [doc.feeds[0].id, doc.feeds[2].id]
    status, headers, body = post(server, '/generate', {'feed': ids})
    assert status == 200
    assert 'attachment' in headers['Content-Disposition']
    assert '.opml' in headers['Content-Disposition']
    assert [t[2] for t in feeds_of(body)] == ['https://a.example/rss', 'https://c.example/rss']


def test_generate_with_nothing_checked_explains_instead_of_downloading(server):
    data = urllib.parse.urlencode({}).encode('utf-8')
    req = urllib.request.Request(server + '/generate', data=data)
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400
    assert 'Content-Disposition' not in exc.value.headers


def test_generate_ignores_unknown_ids(server):
    doc = picker.parse_opml(GROUPED)
    _, _, body = post(server, '/generate', {'feed': [doc.feeds[1].id, 'nope', '9999']})
    assert [t[2] for t in feeds_of(body)] == ['https://b.example/rss']


def test_unknown_path_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(server + '/whatever')
    assert exc.value.code == 404


def test_output_filename_is_derived_from_the_source_file(server):
    doc = picker.parse_opml(GROUPED)
    _, headers, _ = post(server, '/generate', {'feed': [doc.feeds[0].id]})
    assert 'PocketCasts-selected.opml' in headers['Content-Disposition']
