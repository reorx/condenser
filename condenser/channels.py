"""The vocabulary every verdict channel speaks (plan v2: 判定 v2 的通道与组合器).

A *channel* is one way of having an opinion about a tweet. The shipped one is the
topic kNN in ``verdict.py`` (channel B); ``ngram.py`` is channel D. They see the
same tweet and answer independently, and the combiner below is the only place
their answers meet.

Two rules make the whole arrangement work, and both come out of the 2026-07-27
backtest that killed the single-channel negative side:

* **Abstaining is not scoring zero.** A channel with nothing to say returns
  ``None``. Folding silence in as a 0.0 vote would let a channel that never fires
  drag every other channel's opinion toward neutral, which is exactly how a
  weak channel becomes indistinguishable from a strong one.
* **Every channel is independently switchable and independently backtestable.**
  That is what let the topic kNN's negative half be switched off without taking
  its positive half with it, and it is the property the ensemble is built for.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChannelScore:
    """One channel's opinion on one tweet.

    ``score`` is in [-1, +1] with the same sign convention everywhere: positive
    means "you would like this". ``confidence`` says how much of a vote it gets in
    the mix — it expresses *how much evidence there was*, not how extreme the
    score is, so a channel that is loudly wrong on thin evidence cannot outvote a
    channel that is quietly right on thick evidence.

    ``corroborated`` is the asymmetry gate travelling with the evidence: a
    negative verdict costs the tweet, so a channel says here whether its evidence
    is more than a single accident (kNN: two down neighbours; n-gram: two negative
    tokens). A channel with no such notion leaves it True — no objection.
    """

    score: float
    confidence: float = 1.0
    corroborated: bool = True
    meta: dict = field(default_factory=dict)


def combine(scores: dict[str, Optional[ChannelScore]], weights: dict[str, float]) -> Optional[ChannelScore]:
    """Weighted mean over the channels that actually spoke, or None if none did.

    Confidence multiplies the configured weight rather than the score, so a
    half-confident channel is half a vote instead of a full vote for a halved
    opinion — the difference matters when one channel abstains and the remaining
    one is thin: the result then reflects that thinness in ``confidence`` instead
    of quietly presenting itself as a full-strength answer.
    """
    live = [(weights.get(key, 0.0), value) for key, value in scores.items() if value is not None]
    live = [(weight, value) for weight, value in live if weight > 0]
    mass = sum(weight * value.confidence for weight, value in live)
    if not mass:
        return None
    return ChannelScore(
        score=sum(weight * value.confidence * value.score for weight, value in live) / mass,
        # the mix inherits its parts' confidence, so a lone thin channel stays thin
        confidence=mass / sum(weight for weight, _ in live),
        corroborated=all(value.corroborated for _, value in live),
        meta={'channels': {key: value.meta for key, value in scores.items() if value is not None}},
    )
