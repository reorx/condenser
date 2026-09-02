"""LLM summaries for Hacker News stories (plan 2026-09-02 §3, Phase B).

The HN card shows a title, a domain and a score; whether the story is worth
opening is decided by clicking through — twice, since the article and the
discussion are two tabs. This writes 2-3 Chinese sentences about the article
and 1-2 about what the thread makes of it, so the decision is made on the
timeline (plan §0: "before opening"; the Vibe Reader link mode is "after").

The project's **third per-item billed component**, fenced like the second
(``summary.py``): a switch of its own, a per-round cap of its own, counts on
``/api/hn/status`` — and **the RSS pipeline's API key**, deliberately (plan §3.4):
same purpose, same provider, and a second key would be one more place to
configure the same thing. The transport is shared too (``summary.complete``),
because that is where a failure is assigned to whoever caused it, and two
pipelines charging the same outage differently would be a bug nobody could see.

What differs from RSS is the **material**. A feed entry carries its body; an HN
story carries nothing, so each one costs two fetches before the billed call:

* the **article** — ``preview._fetch_capped`` (the UA and timeout the preview
  prefetch already uses against these very URLs) → readability → ``plain_text``.
  A self-post uses its own ``text``. When the fetch or the extraction fails the
  prompt says so and carries the preview description instead, and the story's
  retry budget is untouched: a paywall is not the model's fault (plan §0.7 — a
  deliberate fork from RSS §0.1's "never fetch", because the preview prefetch
  already fetches these pages, so the failure surface is not new);
* the **discussion** — one Algolia request returns the whole tree. Top-level
  comments in Algolia's order, each with at most two levels of replies, cut at a
  character budget. Algolia failing skips the story *for this round*: nothing is
  decided and nothing is charged, the next round tries again.

A story is summarized **once**, after the discussion has formed (enough
comments, or enough hours on the front page). No refresh when the thread grows
— v1 keeps that door closed on purpose (plan §3.3).

``run_round`` hangs off the tail of ``HNManager.poll_once``, after admission: a
story admitted this round is a candidate this round, and HN content only moves
with a round, so a loop of its own would have nothing to discover.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

import httpx
from readability import Document

from . import db, preview, search, summary
from .config import Settings
from .summary import ProviderUnavailable, SummaryError
from .text import plain_text

log = logging.getLogger('condenser.hn_summary')

ALGOLIA_ITEM_URL = 'https://hn.algolia.com/api/v1/items/{id}'

# Independent of ``summary.PROMPT_VERSION``: the two prompts change for their own
# reasons, and a bump here must not relabel the RSS provenance (plan §3.4).
PROMPT_VERSION = 'v1'

# The RSS number, on purpose: same failure kinds, same provider.
MAX_ATTEMPTS = summary.MAX_ATTEMPTS

# Stored in ``summary_model`` for a story that had nothing to read: no article,
# no preview description, no comments, no self text. The ``summary.SKIP_SHORT``
# arrangement — a decision, so the story stops re-entering the batch every round
# (it would otherwise: nothing about it changes, and the age gate never closes).
SKIP_EMPTY = 'skip:empty'

# How many reply levels under a top-level comment reach the prompt (plan §3.2).
REPLY_DEPTH = 2

# Appended where the article or the discussion was cut.
CUT_MARK = '…'

# What the prompt says in the article's place when there was no article. The
# model is *told* rather than left to guess from an empty section, because the
# system prompt asks it to mark the first paragraph as an inference in that case.
NO_ARTICLE = '（未能获取文章内容）'
NO_DISCUSSION = '（暂无评论）'

JsonFetcher = Callable[[str], Awaitable[object]]  # async (url) -> parsed JSON
ArticleFetcher = Callable[[str], Awaitable[Optional[str]]]  # async (url) -> article text | None
Summarizer = Callable[[Optional[str], str], Awaitable[str]]  # async (title, material) -> summary


def available(settings: Settings) -> bool:
    """On iff the HN switch is on *and* the shared summary provider is configured."""
    return bool(settings.condenser_hn_summary_enabled and summary.available(settings))


def model_tag(settings: Settings) -> str:
    """Provenance, not a re-do contract — ``summary.model_tag``'s semantics, its own version."""
    return f'{settings.condenser_summary_model}@{PROMPT_VERSION}'


# --- the article --------------------------------------------------------------


def extract_article(html: str) -> Optional[str]:
    """A page's HTML -> the prose of its main content, or None if there is none.

    readability picks the content block (navigation, footer and sidebars fall
    away by link density), ``plain_text`` then strips what is left the way the
    RSS pipeline strips a feed body — ``_drop_noise`` first, on a fragment
    readability already reduced, never a regex over the whole page (its docstring
    says why). The interface is one function of ``html -> str | None`` so a
    better extractor (trafilatura, say) is a swap, not a redesign (plan §3.2).
    """
    if not html or not html.strip():
        return None
    body = Document(html).summary(html_partial=True)
    return plain_text(body) or None


async def fetch_article(url: str, settings: Settings) -> Optional[str]:
    """Fetch a story's URL and extract its article. None when the page is not HTML.

    Through ``preview._fetch_capped`` — the preview prefetch's UA, timeout and
    redirect policy, with this pipeline's own byte cap — so a site that serves
    the preview fetch serves this one, and one that blocks it blocks both. A
    non-HTML answer (a PDF, a JSON API, an image) is an ordinary HN link, not an
    error: it just has no article. Network failures propagate; the round decides
    what they mean (a degrade, see ``_article``).
    """
    try:
        _final, ctype, raw = await preview._fetch_capped(
            url, settings, cap=settings.condenser_hn_summary_max_bytes, accept=lambda c: 'html' in c.lower()
        )
    except preview.PreviewError:
        return None
    html = raw.decode(preview._charset(raw, ctype), errors='replace')
    return extract_article(html)


def _default_article_fetcher(settings: Settings) -> ArticleFetcher:
    # A module-level factory rather than a closure inside run_round, whose
    # ``fetch_article`` *parameter* shadows the function above (summary.py's
    # ``summarize`` lesson, found on a live run).
    async def fetch(url: str) -> Optional[str]:
        return await fetch_article(url, settings)

    return fetch


# --- the discussion -----------------------------------------------------------


def discussion_text(tree: dict, max_chars: int) -> Optional[str]:
    """Algolia's ``items/{id}`` tree -> a flat, indented transcript, or None.

    Top-level comments in the order Algolia returns them (its ranking, which is
    HN's), each followed by up to ``REPLY_DEPTH`` levels of replies indented under
    it, so the model can see what a reply is a reply to. A deleted comment (null
    text) contributes no line but its replies still do. Cut at ``max_chars`` with
    the mark appended; the walk stops as soon as the budget is spent, so a
    900-comment thread costs a few kilobytes of work, not a megabyte of string.
    """
    lines: list[str] = []
    used = 0

    def walk(node: dict, depth: int) -> bool:
        nonlocal used
        if depth > REPLY_DEPTH:
            return True
        body = plain_text(node.get('text'))
        if body:
            line = f'{"  " * depth}- {node.get("author") or "匿名"}: {body}'
            lines.append(line)
            used += len(line) + 1
            if used > max_chars:
                return False
        for child in node.get('children') or []:
            if not walk(child, depth + 1):
                return False
        return True

    for top in tree.get('children') or []:
        if not walk(top, 0):
            break
    if not lines:
        return None
    text = '\n'.join(lines)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + CUT_MARK
    return text


# --- the prompt ---------------------------------------------------------------


def system_prompt() -> str:
    """Chinese; the article first, the thread's reaction second; nothing around them.

    The no-article case is spelled out because it is common (paywalls, PDFs, a
    site that blocks fetchers) and the honest answer there is an inference from
    the title and the discussion, said to be one — not a confident paragraph
    about a page nobody read.
    """
    return (
        '你是一个 Hacker News 阅读器的摘要助手。读者要在时间线上快速判断这条 HN 条目值不值得点开。\n'
        '输入是文章内容（可能缺失，缺失时会给出链接页面的描述）和 HN 上的讨论。\n'
        '用中文写：先用 2-3 句话说明文章讲了什么、给出了什么结论或结果；'
        '再用 1-2 句话说明 HN 讨论的主流反应或争议点。\n'
        '如果没有文章内容，第一部分改为根据标题、描述和讨论推断文章讲了什么，并明确说明这是推断。\n'
        '如果没有讨论，省略第二部分。\n'
        '无论原文是什么语言，一律用中文回答。\n'
        '只输出摘要正文：不要标题、不要「摘要：」这类前缀、不要 Markdown、不要分点、不要评价文章好坏、'
        '不要写「这篇文章」「讨论中」以外的元话语。'
    )


def material(article: Optional[str], description: Optional[str], discussion: Optional[str]) -> str:
    """The user prompt's body: the two sections, each present or explicitly absent."""
    if article:
        article_part = article
    else:
        article_part = NO_ARTICLE
        if description:
            article_part += f'\n链接页面的描述：{description}'
    return f'文章内容：\n{article_part}\n\nHN 讨论：\n{discussion or NO_DISCUSSION}'


def user_prompt(title: Optional[str], body: str) -> str:
    return f'标题：{title or "(无标题)"}\n\n{body}'


# --- the pipeline -------------------------------------------------------------


async def run_round(
    settings: Settings,
    *,
    fetch_json: JsonFetcher,
    fetch_article: Optional[ArticleFetcher] = None,
    summarize: Optional[Summarizer] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Summarize up to one batch of admitted, unread stories. Returns the round's counts.

    ``fetch_json`` is ``HNManager``'s (the Algolia request rides the seam the
    Firebase requests already use); ``fetch_article`` and ``summarize`` are the
    test injections, ``None`` meaning the real fetch and the real (billed) call.
    Without an injected summariser the round opens one HTTP client for the batch.
    """
    stats = {'summarized': 0, 'failed': 0, 'skipped': 0, 'skipped_empty': 0, 'provider_error': None}
    if not available(settings) or settings.condenser_hn_summary_batch <= 0:
        return stats
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    article_of = fetch_article or _default_article_fetcher(settings)
    if summarize is not None:
        return await _drain(settings, fetch_json, article_of, summarize, stats, now)
    async with httpx.AsyncClient(timeout=summary.REQUEST_TIMEOUT) as client:

        async def call(title: Optional[str], body: str) -> str:
            return await summary.complete(system_prompt(), user_prompt(title, body), settings, client=client)

        return await _drain(settings, fetch_json, article_of, call, stats, now)


def _candidates(settings: Settings, now: datetime) -> list[dict]:
    return db.hn_stories_needing_summary(
        limit=settings.condenser_hn_summary_batch,
        max_attempts=MAX_ATTEMPTS,
        min_comments=settings.condenser_hn_summary_min_comments,
        seen_before=now - timedelta(hours=settings.condenser_hn_summary_min_age_hours),
    )


async def _drain(
    settings: Settings,
    fetch_json: JsonFetcher,
    article_of: ArticleFetcher,
    call: Summarizer,
    stats: dict,
    now: datetime,
) -> dict:
    """One batch, one story at a time — serial, for ``summary._drain``'s reason:
    the one rule that makes an outage cheap is stopping at the first unanswered
    request, and that rule needs the requests in a row."""
    summarized: list[int] = []
    for row in _candidates(settings, now):
        try:
            tree = await fetch_json(ALGOLIA_ITEM_URL.format(id=row['id']))
        except Exception as e:  # noqa: BLE001 — orchestration boundary: Algolia down says nothing about the story
            log.warning('hn summary: discussion fetch failed for %s, skipping this round (%s)', row['id'], e)
            stats['skipped'] += 1
            continue
        discussion = discussion_text(tree or {}, settings.condenser_hn_summary_max_discussion_chars)
        article = await _article(row, article_of, settings)
        description = _description(row.get('preview'))
        if not (article or description or discussion):
            db.set_hn_summary_decision(row['id'], SKIP_EMPTY)
            stats['skipped_empty'] += 1
            continue
        try:
            answer = await call(row['title'], material(article, description, discussion))
        except ProviderUnavailable as e:
            log.warning('hn summary: provider unavailable, ending the round (%s)', e)
            stats['provider_error'] = str(e)
            break
        except SummaryError as e:
            log.info('hn summary: story %s failed (%s)', row['id'], e)
            db.bump_hn_summary_attempts(row['id'])
            stats['failed'] += 1
            continue
        db.set_hn_summary(row['id'], answer, model_tag(settings))
        summarized.append(row['id'])
        stats['summarized'] += 1
    # The summary is part of the story's search document now, and the document
    # was written at ingest, long before the discussion existed.
    search.index_hn_stories(summarized)
    if stats['summarized'] or stats['failed']:
        log.info('hn summary round: %s', stats)
    return stats


async def _article(row: dict, article_of: ArticleFetcher, settings: Settings) -> Optional[str]:
    """The story's text for the prompt: a self-post's own body, or the fetched article.

    The one place a fetch failure is caught, and it is caught as a *degrade*: the
    prompt goes out without an article (``material`` says so), the retry budget is
    not touched, because whatever went wrong here the model never saw the story.
    """
    limit = settings.condenser_hn_summary_max_article_chars
    if not row.get('url'):
        return _cut(plain_text(row.get('text')), limit)
    try:
        text = await article_of(row['url'])
    except Exception as e:  # noqa: BLE001 — orchestration boundary (plan §0.7): a paywall is not an error
        log.info('hn summary: article fetch failed for %s (%s: %s)', row['id'], e.__class__.__name__, e)
        return None
    return _cut(text, limit)


def _cut(text: Optional[str], limit: int) -> Optional[str]:
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + CUT_MARK


def _description(preview_json: Optional[str]) -> Optional[str]:
    """The prefetched preview's description — the fallback for a page we cannot read."""
    if not preview_json:
        return None
    try:
        data = json.loads(preview_json)
    except (TypeError, ValueError):
        return None
    return (data.get('description') or None) if isinstance(data, dict) else None


def counts(settings: Settings, now: Optional[datetime] = None) -> dict:
    """The summary block of ``/api/hn/status`` — ``summary.counts``' shape.

    ``now`` is the manager's clock (the age gate reads it); ``pending`` is
    reported with the feature off, because it is the number the switch would act on.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    numbers = db.hn_summary_counts(
        max_attempts=MAX_ATTEMPTS,
        min_comments=settings.condenser_hn_summary_min_comments,
        seen_before=now - timedelta(hours=settings.condenser_hn_summary_min_age_hours),
    )
    return {
        'enabled': available(settings),
        'model': model_tag(settings) if available(settings) else None,
        **numbers,
    }
