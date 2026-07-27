"""Attribute extraction: what a tweet is about, and how it talks (plan v2 step 2).

Channel C's fuel. The LLM here is a **feature extractor, not a judge**: it only
reports attributes, and the scoring stays where it can be explained and improves
with every label (step 3). That split is the whole reason to spend money on a
model at all — a per-round "is this good?" call would be unreproducible, would
learn nothing from the reader's history, and would cost the same.

The style flags are a **closed taxonomy**, held here as a constant. An open
vocabulary drifts every time the provider updates a model, and a flag nothing can
score is a flag that costs money for nothing. ``model_tag`` records
``model@taxonomy``, the identity an attribute is comparable within — the same
contract ``embedding.model_tag`` uses, and for the same reason: change either half
and the old rows are not migrated, they are re-read.

Topics stay open (short English slugs). The topic dimension is already covered by
the embedding channel; here they are for the evidence trail and for whatever the
combiner eventually makes of them.

With no API key configured the module reports ``available() is False`` and the
whole path stays inert — nothing is described, nothing is charged.
"""

import asyncio
import json
import logging
from typing import Optional

import httpx

from .config import Settings

log = logging.getLogger('condenser.attributes')

# Bumped when the flags below change meaning, membership or wording. Old rows then
# fall out of `model_tag` and are re-extracted rather than reinterpreted.
TAXONOMY_VERSION = 'v1'

# Grown from the reader's own down-reason chips (topic / promo / ai_slop / author /
# engagement_farming), split finer where the chip lumps distinct patterns together:
# a 🧵-thread hook and a "save this 🔖" bookmark bait are both engagement_farming to
# the reader, but they are different words on the page, and channel C only earns its
# keep if it can tell attributes apart that one embedding cannot.
STYLE_FLAGS = (
    'promo_cta',  # selling something, with a call to action
    'engagement_bait',  # hook + FOMO + "save this 🔖", payoff parked in the replies
    'thread_bait',  # "a thread 🧵 1/N" written to farm follows
    'ai_slop',  # template prose: parallel bullets, hollow summary, emoji subheads
    'listicle',  # "5 things you must know about…"
    'emoji_spam',
    'humblebrag',  # success theatre, revenue screenshots
    'outrage',  # rage bait, deliberately inflammatory framing
    'poll_bait',
    'giveaway',
    'crypto_shill',
    'dropshipping',
)

# One tweet cannot be about fifteen things; a longer list is the model padding.
MAX_TOPICS = 6
MAX_FLAGS = 6

RETRY_DELAYS = (1.0, 2.0)
REQUEST_TIMEOUT = 30.0
# Enough for the JSON answer and nothing else — this is the half that is billed at
# the higher rate, and a model that wants to explain itself is a model overspending.
MAX_OUTPUT_TOKENS = 200


class ExtractionError(RuntimeError):
    """The provider could not be reached or returned an unusable payload."""


def available(settings: Settings) -> bool:
    return bool(
        settings.condenser_attr_enabled and settings.condenser_attr_api_key and settings.condenser_attr_base_url
    )


def model_tag(settings: Settings) -> str:
    """The identity an attribute row is comparable within: model + taxonomy version."""
    return f'{settings.condenser_attr_model}@{TAXONOMY_VERSION}'


def system_prompt() -> str:
    """The taxonomy, spelled out. The model can only answer with flags it was shown."""
    flags = '\n'.join(f'- {flag}' for flag in STYLE_FLAGS)
    return (
        'You label social media posts for a personal reading filter. '
        'Report attributes only; never judge whether the post is good or bad.\n\n'
        'Answer with JSON: {"topics": [...], "style_flags": [...]}\n\n'
        f'"topics": up to {MAX_TOPICS} short lowercase English slugs for the subject matter '
        '(e.g. "llm", "rust", "startup-funding"). Use English even when the post is not.\n\n'
        f'"style_flags": zero or more of the following, and nothing else. Most posts have none — '
        'an empty list is the normal answer, so only flag what is clearly present:\n'
        f'{flags}\n'
    )


def parse_answer(payload: str) -> Optional[dict]:
    """The model's JSON -> a stored row, or None when there is nothing usable.

    Every kind of malformed answer degrades to the same two outcomes — drop the
    field or drop the answer — because the caller's only sane response to a
    provider having a bad day is to leave the tweet undescribed and try later.
    """
    try:
        return clean(json.loads(_strip_fence(payload)))
    except (TypeError, ValueError):
        return None


def clean(answer) -> Optional[dict]:
    """Anything shaped like an answer -> the subset that may be stored.

    Applied again at the write boundary, not only after parsing: the taxonomy is
    closed, and the guarantee that the table only holds flags something can score
    should not depend on which code path produced the dict.
    """
    if not isinstance(answer, dict):
        return None
    return {
        'topics': [item.strip().lower() for item in _strings(answer.get('topics'))[:MAX_TOPICS] if item.strip()],
        'style_flags': [item for item in _strings(answer.get('style_flags')) if item in STYLE_FLAGS][:MAX_FLAGS],
    }


def _strip_fence(payload: str) -> str:
    """Unwrap ```json fences — cheap models emit them even when told not to."""
    text = (payload or '').strip()
    if not text.startswith('```'):
        return text
    body = text.split('\n', 1)[1] if '\n' in text else ''
    return body.rsplit('```', 1)[0].strip()


def _strings(value) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


async def extract_attributes(texts: list[str], settings: Settings) -> list[Optional[dict]]:
    """Describe each text, preserving input order. One request per tweet.

    Deliberately not one request for many tweets: a batched prompt saves a little
    per-call overhead and buys a whole class of silent misalignment bugs, where the
    model returns four answers for five posts and every attribute after the gap
    belongs to the wrong tweet. Concurrency covers the latency instead.
    """
    if not texts:
        return []
    if not available(settings):
        raise ExtractionError('no attribute API key configured')
    limit = asyncio.Semaphore(max(1, settings.condenser_attr_concurrency))
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:

        async def one(text: str) -> Optional[dict]:
            async with limit:
                return await _describe(client, text, settings)

        return list(await asyncio.gather(*(one(text) for text in texts)))


async def _describe(client: httpx.AsyncClient, text: str, settings: Settings) -> Optional[dict]:
    for attempt, delay in enumerate((*RETRY_DELAYS, None)):
        try:
            return parse_answer(await _post(client, text, settings))
        except (httpx.HTTPError, ExtractionError) as e:
            if delay is None:
                log.warning('attribute request failed after %s retries: %s', attempt, e)
                return None
            await asyncio.sleep(delay)
    raise AssertionError('unreachable')


async def _post(client: httpx.AsyncClient, text: str, settings: Settings) -> str:
    resp = await client.post(
        f'{settings.condenser_attr_base_url.rstrip("/")}/chat/completions',
        headers={'Authorization': f'Bearer {settings.condenser_attr_api_key}'},
        json={
            'model': settings.condenser_attr_model,
            'messages': [
                {'role': 'system', 'content': system_prompt()},
                {'role': 'user', 'content': text},
            ],
            'response_format': {'type': 'json_object'},
            'temperature': 0,
            'max_tokens': MAX_OUTPUT_TOKENS,
        },
    )
    resp.raise_for_status()
    choices = resp.json().get('choices')
    if not choices:
        raise ExtractionError('provider returned no choices')
    return choices[0].get('message', {}).get('content') or ''
