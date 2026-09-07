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

MODE_LABELS = {'proxy': '整页模式', 'readable': '阅读模式', 'puremd': '阅读模式 · pure.md'}


def toolbar_html(original_url: str, mode: str, full_page_url: str | None) -> str:
    """One line: original link (new tab) · mode name · optional "full page" link."""
    parts = [
        f'<a href="{escape(original_url, quote=True)}" target="_blank" rel="noopener noreferrer">原网页 ↗</a>',
        f'<span class="cd-mode">{escape(MODE_LABELS.get(mode, mode))}</span>',
    ]
    if full_page_url:
        parts.append(f'<a href="{escape(full_page_url, quote=True)}">整页 →</a>')
    return '<div class="cd-purifier-bar">' + ' '.join(parts) + '</div>'


def reader_page(*, title: str, body_html: str, toolbar, notice: str | None, site: str | None = None) -> str:
    """readable / puremd document: our own shell around an already-sanitized fragment."""
    notice_html = f'<div class="cd-purifier-notice">{escape(notice)}</div>' if notice else ''
    site_html = f'<div class="cd-site">{escape(site)}</div>' if site else ''
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(title)}</title>'
        f'<style>{TOOLBAR_CSS}{READER_CSS}</style></head><body>'
        f'{toolbar_html(toolbar.original_url, toolbar.mode, toolbar.full_page_url)}'
        f'<main class="cd-purifier-reader"><h1 class="cd-title">{escape(title)}</h1>{site_html}{notice_html}'
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
