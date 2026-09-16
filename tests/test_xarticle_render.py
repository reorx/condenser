"""Behavior tests for the X Article renderer: stored detail -> the detail pane's HTML.

xbird hands us the article body as Markdown (``content``) plus the image metadata
Markdown cannot carry (``media[]`` sizes and captions, a ``coverMedia`` the body
does not mention). The server renders it once, into HTML both clients already know
how to show — web through ``sanitizeHtml``, iOS through ``articleBlocks`` — so what
these tests pin is the shape those two pipelines depend on: a lone image is a
``<figure>`` with the size the client reserves space from, the caption is a
``<figcaption>`` (iOS turns it into the text block after the image), the cover
leads, and nothing the author typed can become markup.

Plan: kb/plans/2026-09-16-x-article-full-content.md §4.1
"""

import json
from pathlib import Path

from condenser import xarticle

SAMPLE = json.loads((Path(__file__).parent / 'fixtures' / 'x' / 'article_detail.json').read_text())

IMG_A = 'https://pbs.twimg.com/media/A.jpg'
IMG_B = 'https://pbs.twimg.com/media/B.png'
COVER = 'https://pbs.twimg.com/media/COVER.jpg'


def detail(content=None, **extra):
    return {'content': content, **extra}


# --- markdown structure ---------------------------------------------------------


def test_headings_lists_quotes_and_code_blocks_render_as_their_elements():
    html = xarticle.render_html(
        detail('## 小标题\n\n正文一段。\n\n- 一\n- 二\n\n1. 甲\n2. 乙\n\n> 引用\n\n```\ncode <b>\n```')
    )
    assert '<h2>小标题</h2>' in html
    assert '<p>正文一段。</p>' in html
    assert '<ul>' in html and '<li>一</li>' in html
    assert '<ol>' in html and '<li>甲</li>' in html
    assert '<blockquote>' in html
    # code keeps its text, escaped
    assert '<pre><code>code &lt;b&gt;\n</code></pre>' in html


def test_links_keep_their_target():
    html = xarticle.render_html(detail('读 [文档](https://docs.example.com/zh)。'))
    assert '<a href="https://docs.example.com/zh">文档</a>' in html


# --- images -------------------------------------------------------------------


def test_a_lone_image_becomes_a_figure_with_its_size_and_caption():
    html = xarticle.render_html(
        detail(
            f'前文\n\n![浅色排版很好看]({IMG_A})\n\n后文',
            media=[{'mediaId': '1', 'url': IMG_A, 'width': 2986, 'height': 1648, 'caption': '浅色排版很好看'}],
        )
    )
    assert (
        f'<figure><img src="{IMG_A}" width="2986" height="1648" alt="浅色排版很好看" />'
        '<figcaption>浅色排版很好看</figcaption></figure>'
    ) in html
    # a figure is not wrapped in a paragraph (<p><figure> is invalid nesting)
    assert '<p><figure>' not in html


def test_an_image_without_a_caption_has_no_figcaption():
    html = xarticle.render_html(
        detail(f'![]({IMG_B})', media=[{'mediaId': '2', 'url': IMG_B, 'width': 1080, 'height': 1440}])
    )
    assert f'<figure><img src="{IMG_B}" width="1080" height="1440" alt="" /></figure>' in html
    assert '<figcaption>' not in html


def test_an_image_missing_from_media_renders_without_a_size():
    """No guessing: a client that finds no size falls back to its own placeholder."""
    html = xarticle.render_html(detail(f'![图]({IMG_A})', media=[]))
    assert f'<figure><img src="{IMG_A}" alt="图" /><figcaption>图</figcaption></figure>' in html
    assert 'width=' not in html


def test_an_image_inside_a_sentence_stays_inline():
    html = xarticle.render_html(
        detail(f'文字 ![icon]({IMG_A}) 文字', media=[{'mediaId': '1', 'url': IMG_A, 'width': 20, 'height': 20}])
    )
    assert f'<p>文字 <img src="{IMG_A}" width="20" height="20" alt="icon" /> 文字</p>' in html
    assert '<figure>' not in html


def test_image_urls_are_left_pointing_at_x():
    """The server does not proxy: iOS routes every block image through
    /api/preview/image itself, and web rewrites the HTML — proxying here would
    make iOS a proxy of a proxy."""
    html = xarticle.render_html(detail(f'![]({IMG_A})'))
    assert f'src="{IMG_A}"' in html


def test_the_cover_leads_the_body():
    html = xarticle.render_html(
        detail('第一段。', coverMedia={'mediaId': '9', 'url': COVER, 'width': 1600, 'height': 900})
    )
    assert html.startswith(f'<figure><img src="{COVER}" width="1600" height="900" alt="" /></figure>')
    assert html.index('<figure>') < html.index('<p>第一段。</p>')


def test_a_cover_alone_is_not_an_article():
    assert xarticle.render_html(detail(None, coverMedia={'mediaId': '9', 'url': COVER})) is None


# --- safety -------------------------------------------------------------------


def test_raw_html_in_the_markdown_is_escaped_not_passed_through():
    """X's MARKDOWN entity can carry anything; an author's ``<script>`` is text."""
    html = xarticle.render_html(detail('hi <script>alert(1)</script>\n\n<img src=x onerror=alert(1)>'))
    assert '<script>' not in html and '<img src=x' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html


def test_a_javascript_link_is_not_made_clickable():
    html = xarticle.render_html(detail('[click](javascript:alert(1))'))
    assert 'href="javascript:' not in html


def test_captions_are_escaped_in_both_places():
    html = xarticle.render_html(detail(f'![a "b" <c>]({IMG_A})'))
    assert 'alt="a &quot;b&quot; &lt;c&gt;"' in html
    assert '<figcaption>a &quot;b&quot; &lt;c&gt;</figcaption>' in html


# --- degraded input -------------------------------------------------------------


def test_nothing_to_render_is_none():
    assert xarticle.render_html(None) is None
    assert xarticle.render_html({}) is None
    assert xarticle.render_html(detail('   \n ')) is None


def test_plain_text_is_the_fallback_when_there_is_no_markdown():
    html = xarticle.render_html({'plainText': '第一段 <b>\n第二段'})
    assert html == '<p>第一段 &lt;b&gt;</p>\n<p>第二段</p>\n'


# --- the real sample ------------------------------------------------------------


def test_the_real_article_renders_every_part():
    article = SAMPLE['article']
    html = xarticle.render_html(article)

    assert html.count('<h2>') == 7
    assert html.count('<pre>') == 2  # four ``` fences
    # cover + three body images, each with its size
    assert html.count('<figure>') == 4
    assert 'width="2986" height="1648"' in html
    assert '<figcaption>能打开3D文件</figcaption>' in html
    assert html.startswith('<figure><img src="https://pbs.twimg.com/media/HRXe6lhW4AADNow.jpg"')
    # the title is the pane's heading, not the body's
    assert article['title'] not in html
