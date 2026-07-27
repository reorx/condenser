"""Channel D: naive Bayes over the words of the tweets you labeled.

The topic embedding (channel B) answers "what is this about". This channel
answers "how does it talk", which is what 24 of the first 29 downvotes were
actually complaining about — promo voice, engagement bait, AI slop. Style is
largely *lexical*: ``save this 🔖``, ``a thread 🧵``, ``1/``, ``you must know``.
A bag of words can learn those outright; a 256-dimension topic vector averages
them into whatever the tweet happened to be about.

Two properties earn it the first slot after B, ahead of the LLM channel:

* **zero marginal cost** — no API, no table, no migration. The counts are rebuilt
  from ``x_tweets.text`` each round, in milliseconds at a few hundred labels;
* **it can name its evidence** — the tokens that moved the score are the reason
  string, in words the reader recognizes, which no embedding neighbour list is.

Deliberately no segmenter dependency (jieba and friends): Chinese falls back to
character bigrams, the standard cheap stand-in, for the same reason sqlite-vec
beat Chroma in Phase 4 — one file, no new moving parts.
"""

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .channels import ChannelScore
from .config import Settings

# Laplace smoothing on the document counts. Fixed rather than configurable: at 1.0
# a token seen in every down and no up tops out at a finite weight instead of an
# infinite one, which is the only thing this constant is here to prevent.
ALPHA = 1.0

_URL = re.compile(r'https?://\S+|\bt\.co/\S+')
_MENTION = re.compile(r'@\w+')  # author identity is channel A's job, not the words'
_LATIN = re.compile(r"[a-z0-9][a-z0-9'’]*")
# CJK ideographs + kana + hangul, as runs; segmented into character bigrams below
_CJK = re.compile(r'[㐀-鿿぀-ヿ가-힯]+')
# Emoji and the pictographic dingbats/arrows around them, one token per character
_EMOJI = re.compile(r'[\U0001f000-\U0001faff←-⇿⌀-➿⬀-⯿]')

# Small and explicit, per the plan. These are the words that appear in everything
# and would otherwise dominate the document frequencies; anything domain-flavoured
# ("must", "know", "save") is left in, because that is precisely the vocabulary the
# style flags live in.
STOPWORDS = frozenset(
    'a an and are as at be but by for from has have i if in is it its of on or '
    's t that the this to was were will with you your my me we our'.split()
)


# The evidence window the neutral point is estimated through. Fixed rather than
# tied to the scoring knobs: the offset should describe the corpus, not move every
# time a gate is tuned.
OFFSET_MIN_DF = 2
CALIBRATION_TOP = 8


@dataclass
class NgramModel:
    """Document frequencies per class. Presence, not count: a tweet that repeats a
    word three times is one reader judgement, not three.

    ``offset`` is where "no opinion" actually sits. It is not zero: downvoted
    tweets carry about twice the words of upvoted ones (threads and listicles take
    room), so nearly every word in the corpus appears in more downs than ups and
    the whole vocabulary leans negative. Subtracting the typical word's lean makes
    zero mean zero again — which the combiner requires, since it averages this
    channel's score with channels that never had the problem.
    """

    up: Counter = field(default_factory=Counter)
    down: Counter = field(default_factory=Counter)
    up_docs: int = 0
    down_docs: int = 0
    offset: float = 0.0

    @property
    def trained(self) -> bool:
        return bool(self.up_docs and self.down_docs)


def tokenize(text: str) -> list[str]:
    """Lowercased unigrams + bigrams, with emoji and CJK character bigrams.

    URLs and @mentions go first: a link is not a style and an author is channel
    A's business. Hashtags keep their word (``#giveaway`` is as lexical as a
    signal gets) and lose the ``#``, so they pool with the plain word.

    Bigrams are built from the **unfiltered** sequence and only then are stopwords
    dropped from the unigrams — otherwise "save this" (the signature) would be
    destroyed to remove "this" (the noise).
    """
    lowered = _MENTION.sub(' ', _URL.sub(' ', text.lower())).replace('#', '')
    latin = _LATIN.findall(lowered)
    tokens = [word for word in latin if word not in STOPWORDS]
    tokens += [f'{first} {second}' for first, second in zip(latin, latin[1:])]
    tokens += _EMOJI.findall(lowered)
    for run in _CJK.findall(lowered):
        tokens += [run] if len(run) == 1 else [run[i : i + 2] for i in range(len(run) - 1)]
    return tokens


def fit(docs: Iterable[tuple[str, bool]]) -> NgramModel:
    """Count documents per class. ``docs`` is (text, is_positive) — an up or a save
    against a down, the same two sides the kNN trains on."""
    model = NgramModel()
    corpus = list(docs)
    for text, positive in corpus:
        counter = model.up if positive else model.down
        if positive:
            model.up_docs += 1
        else:
            model.down_docs += 1
        for token in set(tokenize(text)):
            counter[token] += 1
    model.offset = _neutral_point(model, corpus)
    return model


def _neutral_point(model: 'NgramModel', corpus: list[tuple[str, bool]]) -> float:
    """Halfway between what the two classes score — the corpus's own middle.

    Measured on the corpus rather than derived from the vocabulary, because the
    obvious vocabulary estimator (the median word's lean) measures how *exclusive*
    each side's words are, not where neutral is: the wordier class contributes most
    of the shared vocabulary, so the median word leans its way and subtracting it
    erases the very signal the channel is for.

    Each document is scored with **itself taken out of the counts**. Scoring them
    in-sample was tried first and left the neutral point too high, because the
    self-vote is worth more to one side than the other: downvoted tweets share a
    vocabulary, so removing one changes little, while upvoted tweets are each about
    something else and take their only witness with them. Leaving one out costs a
    pass over the corpus and removes the asymmetry.
    """
    if not model.trained:
        return 0.0
    sides: dict[bool, list[float]] = {True: [], False: []}
    for text, positive in corpus:
        raw = _held_out_score(model, text, positive)
        if raw is not None:
            sides[positive].append(raw)
    if not (sides[True] and sides[False]):
        return 0.0
    return (statistics.fmean(sides[True]) + statistics.fmean(sides[False])) / 2


def _held_out_score(model: NgramModel, text: str, positive: bool) -> Optional[float]:
    """This document's raw score against the corpus minus itself.

    The counts are decremented and put back rather than copied: a copy per document
    is a copy of the whole vocabulary per document, and this runs on every round.
    """
    tokens = set(tokenize(text))
    counter = model.up if positive else model.down
    for token in tokens:
        counter[token] -= 1
    model.up_docs -= positive
    model.down_docs -= not positive
    try:
        return _raw_score(model, text)
    finally:
        for token in tokens:
            counter[token] += 1
        model.up_docs += positive
        model.down_docs += not positive


def _raw_score(model: NgramModel, text: str) -> Optional[float]:
    """A document's uncentered score, at the default evidence window (calibration only)."""
    weights = sorted(
        (
            _weight(model, token)
            for token in set(tokenize(text))
            if model.up[token] + model.down[token] >= OFFSET_MIN_DF
        ),
        key=abs,
        reverse=True,
    )
    return statistics.fmean(weights[:CALIBRATION_TOP]) if weights else None


def _weight(model: NgramModel, token: str) -> float:
    """Uncentered log-odds for one token: how much more this word says 'up' than 'down'."""
    up = math.log((model.up[token] + ALPHA) / (model.up_docs + 2 * ALPHA))
    down = math.log((model.down[token] + ALPHA) / (model.down_docs + 2 * ALPHA))
    return up - down


def contributions(model: NgramModel, text: str, settings: Settings) -> list[tuple[str, float]]:
    """Per-token log-odds, most influential first. Positive = reads like an upvote.

    Uncentered on purpose: the corpus offset is a property of the corpus, not of a
    word, and folding it in here would change *which* tokens rank as the strongest
    evidence — measured, that swap alone dropped the channel below its own base
    rate. Ranking comes from the raw log-odds; the offset is applied once, to the
    finished score, where it can only shift and never reorder.

    A token below ``min_df`` total documents is skipped rather than smoothed: at a
    few hundred labels a once-seen word is an anecdote, and it is exactly the kind
    of accident that makes a small-corpus bag-of-words model look brilliant in a
    backtest and useless in production.
    """
    if not model.trained:
        return []
    min_df = settings.condenser_verdict_d_min_df
    weights = [
        (token, _weight(model, token))
        for token in sorted(set(tokenize(text)))
        if model.up[token] + model.down[token] >= min_df
    ]
    return sorted(weights, key=lambda item: abs(item[1]), reverse=True)


def score(model: NgramModel, text: str, settings: Settings) -> Optional[ChannelScore]:
    """This channel's opinion, or None when it does not recognize enough of the tweet.

    Two rules, both bought with the first real backtest (see the pinning test in
    tests/test_x_verdict_channels.py):

    * **only strong evidence votes.** A word both sides use says nothing, and
      enough of them pile into a confident verdict assembled out of noise.
    * **the strong evidence is averaged, not summed.** A sum grows with the number
      of words, and downvoted tweets are simply longer — threads, listicles and
      promos take more room (measured: 30.8 informative tokens against upvotes'
      15.3). Summing therefore scored *length*, and every long tweet saturated at
      -1 whatever it said. Averaging asks how one-sided the tweet is instead of
      how much of it there was.
    """
    weights = [
        (token, weight)
        for token, weight in contributions(model, text, settings)
        if abs(weight) >= settings.condenser_verdict_d_min_weight
    ]
    if len(weights) < settings.condenser_verdict_d_min_hits:
        return None
    top = weights[: settings.condenser_verdict_d_top_tokens]
    centered = statistics.fmean(weight for _, weight in top) - model.offset
    return ChannelScore(
        # tanh, not a clip: loud evidence stays loud and ordered, and the [-1, +1]
        # contract the combiner relies on holds without a discontinuity at the edge
        score=math.tanh(centered / settings.condenser_verdict_d_scale),
        # thin evidence is a thin vote: the mean of two strong words reads exactly
        # as confidently as the mean of eight, and only this says which it was
        confidence=min(1.0, len(top) / settings.condenser_verdict_d_top_tokens),
        # negatives need two independent words for the same reason the kNN needs two
        # down neighbours: one accidental token must not condemn a tweet. Measured
        # against the corpus, not against zero: in a corpus where the typical word
        # already leans down, "below average" is what makes a word count against.
        corroborated=sum(1 for _, weight in top if weight < model.offset) >= 2,
        meta={'tokens': [[token, round(weight, 3)] for token, weight in top]},
    )
