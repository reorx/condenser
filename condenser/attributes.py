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
from dataclasses import dataclass, field
from typing import Iterable, Optional

import httpx

from .channels import ChannelScore
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


# --- channel C: scoring the attributes ----------------------------------------
#
# Extraction above is what a tweet *is*; this is what the reader has made of tweets
# like it. The split is the point: the model reports, the counts judge, and the
# counts improve with every label without another API call.

# Which style flag a down-reason chip actually accuses. The chips are the reader's
# own words for *why*, and routing them is the entire reason they exist: a down
# whose reason is 'promo' says the promo attribute earned it — the emoji that
# happened to be in the same tweet are not implicated. `topic` and `author` are
# real reasons that this channel cannot represent; they belong to the embedding kNN
# and the author prior. They map to nothing on purpose, and are named here rather
# than left out so that a new chip cannot be added without deciding where it goes
# (a test pins this against db.FEEDBACK_REASONS).
REASON_FLAGS: dict[str, tuple[str, ...]] = {
    'promo': ('promo_cta', 'crypto_shill', 'dropshipping', 'giveaway'),
    'ai_slop': ('ai_slop',),
    # humblebrag rides along here rather than under promo: success theatre sells
    # attention, not a product, which is the line the chip itself draws
    # (see the engagement_farming note in AGENTS.md).
    'engagement_farming': ('engagement_bait', 'thread_bait', 'poll_bait', 'listicle', 'outrage', 'humblebrag'),
    'topic': (),  # channel B's business
    'author': (),  # channel A's business
}

# Smoothing on the per-flag counts (Beta/Laplace): a flag seen once must not be
# certain of itself. Same role ALPHA plays in ngram.py, same value, same reason.
FLAG_ALPHA = 1.0
# Confidence saturates as observations accumulate: n/(n+k). No hard threshold to
# tune — a flag seen 5 times is half a vote, seen 20 times nearly a whole one.
CONFIDENCE_SMOOTH = 5.0
# A negative needs two independent downvotes behind the deciding flag, mirroring the
# kNN's ``min_down_neighbors``: one mis-tap must not condemn an attribute.
MIN_DOWN_FOR_NEGATIVE = 2

LABEL_WEIGHT = {'up': 1.0, 'save': 2.0, 'down': 1.0}


@dataclass
class LabeledFlags:
    """One training sample: a labeled tweet's flags, the reader's verdict, the chip."""

    flags: list[str]
    verdict: str  # 'up' | 'save' | 'down'
    reason: Optional[str] = None


@dataclass
class FlagModel:
    """How each attribute has fared with this reader. Counts are fractional because
    an unexplained downvote is shared out across the flags it might have meant."""

    up: dict[str, float] = field(default_factory=dict)
    down: dict[str, float] = field(default_factory=dict)

    def observations(self, flag: str) -> float:
        return self.up.get(flag, 0.0) + self.down.get(flag, 0.0)


def fit_flags(samples: Iterable[LabeledFlags]) -> FlagModel:
    """Count each attribute's ups and downs, routing downs through their chip.

    The two sides are counted differently, and the asymmetry is the design: an
    upvote has no chip and cannot have one, so every flag on a liked tweet is
    credited in full. A downvote *does* carry the reader's own account of what was
    wrong, so it is charged only to the flags that account names — and to all of
    them, in shares, when it does not.
    """
    model = FlagModel()
    for sample in samples:
        flags = [flag for flag in sample.flags if flag in STYLE_FLAGS]
        if not flags:
            continue
        weight = LABEL_WEIGHT.get(sample.verdict, 1.0)
        if sample.verdict != 'down':
            for flag in flags:
                model.up[flag] = model.up.get(flag, 0.0) + weight
            continue
        for flag, share in _charged(flags, sample.reason).items():
            model.down[flag] = model.down.get(flag, 0.0) + weight * share
    return model


def _charged(flags: list[str], reason: Optional[str]) -> dict[str, float]:
    """Which flags a downvote is charged to, and in what shares.

    Three cases, and the middle one was bought with real data. Measured on 59
    production labels under the first, simpler rule ("a chip that matches nothing
    charges nobody"), ``humblebrag`` scored **+0.600 while sitting on seven
    downvoted tweets**: upvotes are credited to every flag in full — an upvote has
    no chip and cannot have one — so any flag the chips never reach could only ever
    accumulate positive evidence. The fix is to fall back rather than discard: the
    reader did dislike *something*, and if the chip they chose does not match how
    the extractor described the tweet, that is a disagreement about the
    description, not a reason to drop the label.
    """
    if reason is None:
        # bag-level: the label is real but unattributed, so it convicts nothing on
        # its own — every candidate takes a share
        return {flag: 1.0 / len(flags) for flag in flags}
    if not REASON_FLAGS.get(reason):
        # 'topic' / 'author': the reader said the problem was *not* the style, so
        # spreading it over the style flags would be the entanglement defect again
        return {}
    accused = [flag for flag in flags if flag in REASON_FLAGS[reason]]
    if not accused:
        return {flag: 1.0 / len(flags) for flag in flags}
    return {flag: 1.0 for flag in accused}


def score_flags(model: FlagModel, flags: list[str], settings: Settings) -> Optional[ChannelScore]:
    """This channel's opinion on a tweet, from its attributes alone.

    One clearly bad attribute carries the tweet — a post with an unmistakable
    marketing line *is* marketing, however much innocuous material surrounds it,
    and averaging dilutes exactly the signal the channel exists to catch. With no
    negative evidence the strongest positive speaks instead; with no sufficiently
    observed flag at all the channel abstains, which at ~60 labels is the usual and
    correct answer.

    Each flag's rate is **shrunk toward zero by how much evidence stands behind
    it**, so that a rare flag cannot outshout a well-established one: measured on
    59 production labels, `thread_bait` sat at -0.600 off three sightings while
    `promo_cta` sat at -0.405 off eighteen, and on a tweet carrying both it was the
    three sightings that decided. Shrinkage puts the observed flag back in front.

    It is *not* a fix for the unreliable tail, which was measured and has a
    different cause: the five most negative scores in the whole label set are
    upvoted promo tweets, because holding one out removes one of `promo_cta`'s
    only five upvotes and makes the flag look worse exactly on the fold where it
    is wrong. That is leave-one-out variance on a dominant flag, and no scoring
    rule reaches it — only more labels do.
    """
    scored = [
        (flag, _flag_score(model, flag) * _evidence(model, flag))
        for flag in dict.fromkeys(flags)
        if model.observations(flag) >= settings.condenser_verdict_c_min_observations
    ]
    if not scored:
        return None
    driver, value = min(scored, key=lambda item: item[1])
    if value > 0:
        driver, value = max(scored, key=lambda item: item[1])
    return ChannelScore(
        score=value,
        confidence=_evidence(model, driver),
        corroborated=model.down.get(driver, 0.0) >= MIN_DOWN_FOR_NEGATIVE,
        meta={'driver': driver, 'flags': [[flag, round(item, 3)] for flag, item in scored]},
    )


def _flag_score(model: FlagModel, flag: str) -> float:
    """[-1, +1]: how this attribute has fared, smoothed. No data -> 0.0."""
    down, up = model.down.get(flag, 0.0), model.up.get(flag, 0.0)
    return 1.0 - 2.0 * (down + FLAG_ALPHA) / (down + up + 2 * FLAG_ALPHA)


def _evidence(model: FlagModel, flag: str) -> float:
    """How much of a claim this flag has earned: n/(n+k), in [0, 1)."""
    observations = model.observations(flag)
    return observations / (observations + CONFIDENCE_SMOOTH)


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
