"""LLM summaries for RSS entries (plan 2026-08-20 §3).

A feed entry arrives as somebody else's HTML: a full article, a teaser, or a
one-line link post. The card shows two or three Chinese sentences instead
(plan §0.4), so a hundred subscriptions can be triaged by reading rather than by
clicking through. Only the feed's own content is ever summarized — no article
fetching, no readability extraction (plan §0.1), which is what keeps this module
free of a paywall/anti-scraping failure surface.

This is the project's **second per-item billed component**, and it copies channel
C's four fences exactly: a switch, its own API key (setting the key *is* the act
of turning it on — no fallback to the embedding or attribute key, so deploying
this code cannot start spending), a hard per-round cap, and counts on
``/api/rss/status``.

Two rules are worth stating because they cost money to get wrong:

* **One request per entry, never a batched prompt.** The attribute extractor's
  lesson: a model that answers four times for five inputs misaligns every answer
  after the gap, and here that means a summary attached to the wrong article.
* **A failure is charged to whoever caused it.** A provider that never answered
  (5xx, timeout, refused connection) says nothing about the entry, so it burns no
  retry and stops the round — with the API down the remaining requests are just
  more failures. A provider that answered and rejected *this input* does count,
  three times, after which the card degrades to truncated source text forever.

``run_round`` hangs off the tail of a polling round rather than owning a loop:
RSS content only arrives with a round, so a second timer would have nothing of
its own to discover (``hn._fill_previews``' position, and the same reasoning).
"""

import html
import logging
import re
from typing import Callable, Optional

import httpx

from . import db, search
from .config import Settings

log = logging.getLogger('condenser.summary')

# Bumped when the prompt below changes what a summary *is* (length, language,
# register). It rides in `summary_model` so a stored summary says which prompt
# wrote it — provenance, not a comparability key; see model_tag.
PROMPT_VERSION = 'v1'

# After this many charged failures the entry is left alone for good. Some bodies
# fail every time (a content filter, an encoding the model chokes on), and
# retrying those every 30 minutes forever is a standing charge for nothing.
MAX_ATTEMPTS = 3

# Stored in `summary_model` for an entry whose text is under the length gate: the
# column records *what decided this entry's summary state*, and "the length rule
# did, no model needed" is a decision worth keeping. Without it a short body
# wrapped in a lot of markup would clear the cheap SQL pre-filter and re-enter a
# batch every round forever, since nothing about it ever changes.
SKIP_SHORT = 'skip:short'

REQUEST_TIMEOUT = 60.0
# Two or three Chinese sentences and nothing else. A model that wants to explain
# its answer is a model overspending on the half that is billed at the high rate.
MAX_OUTPUT_TOKENS = 400

_TAG_RE = re.compile(r'<[^>]+>')
# script/style *contents* are not prose: dropping only the tags would send a
# stylesheet to the model, paying for the tokens and getting a worse summary.
_NOISE_RE = re.compile(r'<(script|style)\b.*?</\1\s*>', re.IGNORECASE | re.DOTALL)
# A block left unclosed (a body truncated mid-<script>) would slip past the pair
# above, and _TAG_RE stripping only the opening tag leaves the whole script body
# posing as prose — inflating the text past the min_chars gate and getting billed
# as the article. Strip from any opener that survived to the end of the text.
_UNCLOSED_NOISE_RE = re.compile(r'<(?:script|style)\b.*\Z', re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r'\s+')
# A model asked for a summary often labels it first. The label is not the summary.
_PREFIX_RE = re.compile(r'^\s*(摘要|总结|概要|Summary)\s*[:：]\s*', re.IGNORECASE)


class SummaryError(RuntimeError):
    """This entry could not be summarized — charged to its retry budget."""


class ProviderUnavailable(RuntimeError):
    """The provider never answered. Not evidence about any entry: charged to nobody."""


Summarizer = Callable[[Optional[str], str], object]  # async (title, text) -> str


def available(settings: Settings) -> bool:
    return bool(
        settings.condenser_summary_enabled
        and settings.condenser_summary_api_key
        and settings.condenser_summary_base_url
    )


def model_tag(settings: Settings) -> str:
    """Which model + prompt wrote a stored summary.

    Deliberately **provenance, not a re-do contract** — the plan (§1.2) called for
    ``embedding.model_tag`` semantics, where a model change re-reads the archive.
    That contract exists because vectors from two models are not comparable and
    attribute flags from two taxonomies mean different things; a summary is neither.
    It is a finished artifact that nothing downstream compares, so re-writing one
    would spend money to replace text that is not wrong. Changing the model changes
    what the *next* summaries are written by, and the column says which is which.
    """
    return f'{settings.condenser_summary_model}@{PROMPT_VERSION}'


# --- text ---------------------------------------------------------------------


def plain_text(value: Optional[str]) -> str:
    """A feed body's HTML -> the prose a reader would see.

    Not ``search._strip_html``: that one feeds a tokenizer, which does not care
    about script contents or whitespace shape. This one feeds a language model,
    where both are paid for by the token.
    """
    if not value:
        return ''
    text = _NOISE_RE.sub(' ', value)
    text = _UNCLOSED_NOISE_RE.sub(' ', text)
    text = _TAG_RE.sub(' ', text)
    return _WS_RE.sub(' ', html.unescape(text)).strip()


def system_prompt() -> str:
    """Chinese, 2-3 sentences, and nothing around them.

    The language is fixed rather than following the article: this is a Chinese
    reader's timeline, and the summary's job is to let them skip an English
    long-read without opening it.
    """
    return (
        '你是一个 RSS 阅读器的摘要助手。读者要在时间线上快速判断这篇文章值不值得点开。\n'
        '用中文写 2-3 句话，说明这篇文章讲了什么、给出了什么结论或结果。\n'
        '无论原文是什么语言，一律用中文回答。\n'
        '只输出摘要正文：不要标题、不要「摘要：」这类前缀、不要 Markdown、不要评价文章好坏、'
        '不要写「这篇文章」以外的元话语。'
    )


def user_prompt(title: Optional[str], text: str) -> str:
    """Title first: a body often never restates what the article is called."""
    return f'标题：{title or "(无标题)"}\n\n正文：\n{text}'


def clean_answer(payload: Optional[str]) -> str:
    """The model's reply -> a storable summary, or ``SummaryError``.

    An empty answer must not be stored: it would mark the entry summarized forever
    and leave the card with a blank body, which is worse than never having tried.
    """
    text = (payload or '').strip()
    if text.startswith('```'):
        body = text.split('\n', 1)[1] if '\n' in text else ''
        text = body.rsplit('```', 1)[0].strip()
    text = _PREFIX_RE.sub('', text).strip()
    if not text:
        raise SummaryError('provider returned an empty summary')
    return text


# --- the billed call ----------------------------------------------------------


async def summarize_entry(
    title: Optional[str],
    text: str,
    settings: Settings,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Summarize one article. ``client`` is the test seam (``httpx.MockTransport``).

    Named apart from the ``summarize`` *parameter* the pipeline takes, which is the
    injected stand-in for this function: inside ``run_round`` that parameter shadows
    the module namespace, so a closure calling ``summarize`` got the injection slot
    (``None`` in production) rather than this. Found on a live run, because every
    test injects.

    No in-request retry: the next polling round is the retry, and holding a slot
    open through a backoff only delays the rest of the batch. What matters here is
    which of the two exceptions comes out — see the module docstring.
    """
    if not available(settings):
        raise ProviderUnavailable('no summary API key configured')
    if client is not None:
        return await _post(client, title, text, settings)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as own:
        return await _post(own, title, text, settings)


async def _post(client: httpx.AsyncClient, title: Optional[str], text: str, settings: Settings) -> str:
    try:
        resp = await client.post(
            f'{settings.condenser_summary_base_url.rstrip("/")}/chat/completions',
            headers={'Authorization': f'Bearer {settings.condenser_summary_api_key}'},
            json={
                'model': settings.condenser_summary_model,
                'messages': [
                    {'role': 'system', 'content': system_prompt()},
                    {'role': 'user', 'content': user_prompt(title, text)},
                ],
                'temperature': 0.2,
                'max_tokens': MAX_OUTPUT_TOKENS,
                # Summarizing is not a reasoning task, and the thinking half is
                # billed as output and **not** bounded by max_tokens — measured at
                # 1274 reasoning tokens against 99 tokens of answer. See the config
                # note; the flag exists because the field is DashScope's.
                **({'enable_thinking': False} if settings.condenser_summary_disable_thinking else {}),
            },
        )
    except httpx.HTTPError as e:  # timeout, connection refused, DNS — never reached them
        raise ProviderUnavailable(f'{e.__class__.__name__}: {e}') from e
    if resp.status_code >= 500 or resp.status_code in (401, 403, 408, 429):
        # Not about this article: the key is wrong, the quota is spent, or the
        # gateway is unwell. All of them apply equally to every queued entry.
        raise ProviderUnavailable(f'provider returned {resp.status_code}')
    if resp.status_code >= 400:
        # 400 / 413 / 422: the provider read what we sent and refused *it*.
        raise SummaryError(f'provider rejected the request: {resp.status_code}')
    data = resp.json()
    # DEBUG rather than INFO: it is one line per entry, and the round already logs
    # its own totals. Turn it on when you want to know what a batch actually costs.
    log.debug('rss summary usage: %s', data.get('usage'))
    choices = data.get('choices')
    if not choices:
        raise SummaryError('provider returned no choices')
    return clean_answer(choices[0].get('message', {}).get('content'))


# --- the pipeline -------------------------------------------------------------


async def run_round(settings: Settings, summarize: Optional[Summarizer] = None) -> dict:
    """Summarize up to one batch of unread entries. Returns the round's counts.

    ``summarize`` is the injected (test) summariser; without one the round opens a
    single HTTP client and reuses it for every entry, so a batch is one connection
    rather than twenty.
    """
    stats = {'summarized': 0, 'skipped_short': 0, 'failed': 0, 'provider_error': None}
    if not available(settings) or settings.condenser_summary_batch <= 0:
        return stats
    if summarize is not None:
        return await _drain(settings, summarize, stats)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:

        async def call(title: Optional[str], text: str) -> str:
            # through the public function, not straight to _post: it is the one the
            # transport-level tests exercise, and a production path that skipped it
            # would be a path nothing tests
            return await summarize_entry(title, text, settings, client=client)

        return await _drain(settings, call, stats)


async def _drain(settings: Settings, call: Summarizer, stats: dict) -> dict:
    """One batch, one entry at a time.

    Serial on purpose. The batch cap already bounds the round, concurrency would
    buy about a minute of wall clock on a 30-minute cycle, and it would cost the
    one rule that makes an outage cheap: stop at the first unanswered request.
    """
    batch = settings.condenser_summary_batch
    minimum = settings.condenser_summary_min_chars
    summarized: list[int] = []
    for row in db.rss_entries_needing_summary(limit=batch, max_attempts=MAX_ATTEMPTS, min_content_chars=minimum):
        text = plain_text(row['content'])
        if len(text) <= minimum:
            db.set_rss_summary_decision(row['id'], SKIP_SHORT)
            stats['skipped_short'] += 1
            continue
        try:
            answer = await call(row['title'], text[: settings.condenser_summary_max_input_chars])
        except ProviderUnavailable as e:
            log.warning('rss summary: provider unavailable, ending the round (%s)', e)
            stats['provider_error'] = str(e)
            break
        except SummaryError as e:
            log.info('rss summary: entry %s failed (%s)', row['id'], e)
            db.bump_rss_summary_attempts(row['id'])
            stats['failed'] += 1
            continue
        db.set_rss_summary(row['id'], answer, model_tag(settings))
        summarized.append(row['id'])
        stats['summarized'] += 1
    # The summary is part of the entry's search document (it is what the card
    # shows), and the document was written at ingest time without one.
    search.index_rss_entries(summarized)
    if stats['summarized'] or stats['failed']:
        log.info('rss summary round: %s', stats)
    return stats


def counts(settings: Settings) -> dict:
    """The summary block of ``/api/rss/status`` — fence 4 (plan §3).

    ``pending`` is reported even with the feature off, because that is the number
    the switch would act on: "nothing is summarized" and "nothing needs
    summarizing" are indistinguishable from the timeline.
    """
    numbers = db.rss_summary_counts(max_attempts=MAX_ATTEMPTS, min_content_chars=settings.condenser_summary_min_chars)
    return {
        'enabled': available(settings),
        'model': model_tag(settings) if available(settings) else None,
        **numbers,
    }
