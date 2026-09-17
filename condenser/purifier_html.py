"""The Purifier's templates: the reader page, the toolbar, and the small error pages.

Kept apart from ``purifier.py`` so the logic module reads without being cut up by
CSS. Everything here is inline — no external stylesheet, font or script — because
the whole point of a /p page is that it loads on a bad connection with one request
(plan 2026-09-07 §3).
"""

from html import escape

# The toolbar sits at the top of every mode. SFSafariViewController's address bar
# shows only condenser's domain, so without this line the reader has no way back
# to the original page.
TOOLBAR_CSS = """
.cd-purifier-bar{font:14px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
padding:8px 12px;border-bottom:1px solid #d0d0d0;background:#f6f6f6;color:#444;
display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.cd-purifier-bar a{color:#1a5fb4;text-decoration:none}
.cd-purifier-bar .cd-mode{color:#777}
.cd-purifier-notice{margin:12px 0;padding:8px 12px;border-radius:6px;background:#fff4d6;color:#6b4e00;font-size:14px}
@media (prefers-color-scheme: dark){
.cd-purifier-bar{background:#1c1c1e;border-color:#3a3a3c;color:#c7c7cc}
.cd-purifier-bar a{color:#6cb4ff}
.cd-purifier-notice{background:#3a2f0b;color:#ffd97d}}
"""

READER_CSS = """
:root{color-scheme:light dark}
body{margin:0;background:#fff;color:#1c1c1e;font:17px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
-webkit-text-size-adjust:100%}
main.cd-purifier-reader{max-width:42rem;margin:0 auto;padding:16px 18px 48px;word-wrap:break-word;overflow-wrap:break-word}
main.cd-purifier-reader h1.cd-title{font-size:1.6em;line-height:1.25;margin:0.4em 0 0.2em}
main.cd-purifier-reader .cd-site{color:#777;font-size:0.85em;margin-bottom:1.2em}
main.cd-purifier-reader img,main.cd-purifier-reader video{max-width:100%;height:auto}
main.cd-purifier-reader pre{overflow-x:auto;padding:10px;background:#f2f2f7;border-radius:6px;font-size:0.85em}
main.cd-purifier-reader code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
main.cd-purifier-reader blockquote{margin:1em 0;padding-left:1em;border-left:3px solid #d0d0d0;color:#555}
main.cd-purifier-reader table{border-collapse:collapse;max-width:100%;display:block;overflow-x:auto}
main.cd-purifier-reader td,main.cd-purifier-reader th{border:1px solid #d0d0d0;padding:4px 8px}
main.cd-purifier-reader a{color:#1a5fb4}
main.cd-purifier-reader figure{margin:1em 0}
@media (prefers-color-scheme: dark){
body{background:#000;color:#e5e5ea}
main.cd-purifier-reader pre{background:#1c1c1e}
main.cd-purifier-reader blockquote{border-color:#48484a;color:#aeaeb2}
main.cd-purifier-reader td,main.cd-purifier-reader th{border-color:#48484a}
main.cd-purifier-reader a{color:#6cb4ff}
main.cd-purifier-reader .cd-site{color:#8e8e93}}
"""

# The X page reuses the reader shell with its own rules on top (purifier_x.py builds
# the markup). Everything is scoped under .cd-x; the reader's img rule is overridden
# for avatars and grid cells only.
X_CSS = """
.cd-x-tweet{padding:12px 0}
.cd-x-thread .cd-x-tweet+.cd-x-tweet{border-top:1px solid #e5e5ea}
.cd-x-thread .cd-x-ancestor+.cd-x-tweet{border-top:none}
.cd-x-ancestor{position:relative}
.cd-x-ancestor::after{content:'';position:absolute;left:15px;top:48px;bottom:-12px;width:2px;background:#d1d1d6}
.cd-x-ancestor,.cd-x-reply{font-size:0.94em}
.cd-x-head{display:flex;align-items:center;gap:8px;min-width:0;font-size:0.9em}
main.cd-purifier-reader img.cd-x-avatar,span.cd-x-avatar{width:32px;height:32px;border-radius:50%;flex:none;background:#e5e5ea;object-fit:cover}
.cd-x-name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.cd-x-handle{color:#8e8e93;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.cd-x-badge{flex:none;font-size:0.75em;padding:1px 6px;border-radius:4px;background:#e8f1fd;color:#1a5fb4}
.cd-x-text{white-space:pre-wrap;margin:6px 0 0 40px}
.cd-x-text a{text-decoration:none}
.cd-x-media,.cd-x-sensitive,.cd-x-article,.cd-x-quote,.cd-x-meta{margin-left:40px}
.cd-x-focus>*,.cd-x-continuation>*{margin-left:0}
.cd-x-media{margin-top:8px}
.cd-x-media a{display:block}
.cd-x-photos img{display:block;border-radius:10px}
.cd-x-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px}
main.cd-purifier-reader .cd-x-grid img{width:100%;height:100%;aspect-ratio:1;object-fit:cover}
.cd-x-video{position:relative;display:block;border-radius:10px;overflow:hidden;background:#1c1c1e;min-height:3rem;text-decoration:none}
.cd-x-video img{display:block;width:100%}
.cd-x-play{position:absolute;left:10px;bottom:10px;padding:3px 10px;border-radius:999px;background:rgba(0,0,0,.72);color:#fff;font-size:0.85em}
.cd-x-external{font-size:0.9em}
.cd-x-sensitive{margin-top:8px}
.cd-x-sensitive>summary{cursor:pointer;padding:10px;border-radius:10px;background:#f2f2f7;color:#6b6b70;font-size:0.9em}
.cd-x-article{margin-top:8px;border:1px solid #e5e5ea;border-radius:12px;overflow:hidden}
.cd-x-article img{display:block;width:100%}
.cd-x-article-title{font-weight:700;font-size:1.05em;margin:10px 12px 0}
.cd-x-article p{margin:6px 12px;color:#555;font-size:0.92em}
.cd-x-article>a{display:block;margin:0 12px 10px;font-size:0.9em;text-decoration:none}
.cd-x-quote{margin-top:8px;padding:8px 10px;border:1px solid #e5e5ea;border-radius:12px;font-size:0.92em}
.cd-x-quote .cd-x-text,.cd-x-quote .cd-x-media,.cd-x-quote .cd-x-sensitive,.cd-x-quote .cd-x-meta{margin-left:0}
.cd-x-tombstone{color:#8e8e93}
.cd-x-meta{margin-top:6px;color:#8e8e93;font-size:0.8em}
main.cd-purifier-reader .cd-x-meta a{color:inherit;text-decoration:none}
.cd-x-section{font-size:1em;margin:20px 0 0;padding-top:14px;border-top:6px solid #f2f2f7}
.cd-x-module{border-top:1px solid #e5e5ea}
.cd-x-nested{margin-left:16px;padding-left:12px;border-left:2px solid #e5e5ea}
.cd-x-nested .cd-x-tweet{padding:8px 0}
.cd-x-more{margin:16px 0 0;color:#8e8e93;font-size:0.9em;text-align:center}
@media (prefers-color-scheme: dark){
.cd-x-thread .cd-x-tweet+.cd-x-tweet,.cd-x-module,.cd-x-article,.cd-x-quote{border-color:#38383a}
.cd-x-nested{border-color:#38383a}
.cd-x-ancestor::after{background:#48484a}
.cd-x-section{border-color:#1c1c1e}
main.cd-purifier-reader img.cd-x-avatar,span.cd-x-avatar{background:#2c2c2e}
.cd-x-badge{background:#0f2a4a;color:#6cb4ff}
.cd-x-sensitive>summary{background:#1c1c1e;color:#aeaeb2}
.cd-x-article p{color:#aeaeb2}}
"""

MODE_LABELS = {'proxy': '整页模式', 'readable': '阅读模式', 'puremd': '阅读模式 · pure.md', 'x': '推文'}


def toolbar_html(original_url: str, mode: str, full_page_url: str | None) -> str:
    """One line: original link (new tab) · mode name · optional "full page" link."""
    parts = [
        f'<a href="{escape(original_url, quote=True)}" target="_blank" rel="noopener noreferrer">原网页 ↗</a>',
        f'<span class="cd-mode">{escape(MODE_LABELS.get(mode, mode))}</span>',
    ]
    if full_page_url:
        parts.append(f'<a href="{escape(full_page_url, quote=True)}">整页 →</a>')
    return '<div class="cd-purifier-bar">' + ' '.join(parts) + '</div>'


def reader_page(
    *,
    title: str,
    body_html: str,
    toolbar,
    notice: str | None,
    site: str | None = None,
    heading: bool = True,
    extra_css: str = '',
) -> str:
    """readable / puremd / X document: our own shell around a fragment that is already
    safe (sanitized, or built escaped). ``heading=False`` drops the title + site lines
    for a body that carries its own (an X page starts with the author's name)."""
    notice_html = f'<div class="cd-purifier-notice">{escape(notice)}</div>' if notice else ''
    site_html = f'<div class="cd-site">{escape(site)}</div>' if site and heading else ''
    heading_html = f'<h1 class="cd-title">{escape(title)}</h1>' if heading else ''
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(title)}</title>'
        f'<style>{TOOLBAR_CSS}{READER_CSS}{extra_css}</style></head><body>'
        f'{toolbar_html(toolbar.original_url, toolbar.mode, toolbar.full_page_url)}'
        f'<main class="cd-purifier-reader">{heading_html}{site_html}{notice_html}'
        f'{body_html}</main></body></html>'
    )


def _small_page(title: str, message: str, links: list[tuple[str, str]]) -> str:
    items = ''.join(f'<p><a href="{escape(href, quote=True)}">{escape(label)}</a></p>' for label, href in links)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(title)}</title><style>{READER_CSS}</style></head><body>'
        f'<main class="cd-purifier-reader"><h1 class="cd-title">{escape(title)}</h1>'
        f'<p>{escape(message)}</p>{items}</main></body></html>'
    )


def unauthorized_page(original_url: str) -> str:
    return _small_page(
        '需要登录',
        '这个阅读代理只对已登录的 Condenser 设备开放。请在 app 里重新打开这条链接，或先登录网页版。',
        [('打开原网页 ↗', original_url)],
    )


def error_page(title: str, message: str, original_url: str, full_page_url: str | None = None) -> str:
    links = [('打开原网页 ↗', original_url)]
    if full_page_url:
        links.append(('试试整页模式 →', full_page_url))
    return _small_page(title, message, links)
