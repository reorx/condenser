"""Channel A — the author prior: how this account has fared with you before.

The v2 plan listed this channel first (it is the cheapest by far) and then
deferred it: of the first 29 downvotes exactly **one** carried the `author` chip,
so there looked to be nothing to learn. That reading confused the *chip* with the
*signal*. The chip says "I dislike this person"; the prior only needs you to have
disliked their posts, whatever reason you gave each time.

What settled it was the Interactive Brokers measurement (2026-07-29). @IBKR was
the most-downvoted account in the archive — 14 tweets, every one an ad, 6 downed,
all chipped `promo` — and every text channel had a hole exactly where it mattered:
B abstained on 6 of 14 as out-of-domain (a broker ad is nowhere near anything the
reader labels) and never reached its own threshold at judging time; C abstained
wherever the extractor had not yet read the tweet; D abstained on 4 of 14. The
author was present in all 14.

So the channel's claim is narrow and worth stating plainly: **it does not read the
tweet.** It cannot tell a good post from a bad one by the same author, and it is
blind to an account you have never judged. In exchange it never abstains on an
account you have, whatever the subject, the phrasing, or the attributes — and it
costs no API call, no table and no index.

Counts are Beta-smoothed rather than thresholded (the plan's own sketch: "Beta
平滑"). The rule this replaces — `>= 2 downs and no positives -> negative`, 92.9%
precision over 14 leave-one-out calls with no saved tweet condemned — has a cliff
at its centre: a single upvote acquits an account outright, and its second
downvote convicts one. Smoothing keeps the ordering and removes both cliffs, so an
account downed six times and an account downed twice are not the same claim, and
one good post moves an account without absolving it.
"""

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .channels import ChannelScore
from .config import Settings

# Same weights as every other channel: a save costs the reader an intent, a thumb
# a reflex. Kept in the weight rather than the value so the score stays in [-1, +1].
LABEL_WEIGHT = {'up': 1.0, 'save': 2.0, 'down': 1.0}

# Beta/Laplace smoothing on the per-author counts — an author seen once must not be
# certain of themselves. Same role, name and value as `attributes.FLAG_ALPHA`.
ALPHA = 1.0

# Confidence saturates as labels accumulate: n/(n+k). Deliberately **lower than
# channel C's 5.0**, because the two count different things: a style flag appears
# on a hundred tweets, while an author appears as often as you have judged them,
# and in the real label set that is 2-6 times for everyone but @IBKR. At k=5 an
# account you downed six times would still be scored at half strength, which is
# the channel abstaining in all but name.
CONFIDENCE_SMOOTH = 2.0

# A negative needs two independent downs behind it, mirroring the kNN's
# `min_down_neighbors` and channel C's rule: one mis-tap must not condemn an author.
MIN_DOWN_FOR_NEGATIVE = 2


@dataclass
class LabeledAuthor:
    """One training sample: who wrote the tweet, and what the reader said about it."""

    handle: Optional[str]
    verdict: str  # 'up' | 'save' | 'down'


@dataclass
class AuthorModel:
    """How each account has fared with this reader, keyed by normalized handle."""

    up: dict[str, float] = field(default_factory=dict)
    down: dict[str, float] = field(default_factory=dict)

    def observations(self, handle: str) -> float:
        return self.up.get(handle, 0.0) + self.down.get(handle, 0.0)


def normalize(handle: Optional[str]) -> Optional[str]:
    """One account, one key. X renders a handle however the account typed it and
    bird passes that through, so `@IBKR`, `IBKR` and `ibkr` must share one prior."""
    if not handle:
        return None
    return handle.strip().lstrip('@').lower() or None


def fit(samples: Iterable[LabeledAuthor]) -> AuthorModel:
    """Tally each account's labels. No chips are routed here, unlike channel C.

    A down's chip says which *attribute* earned it, and by the time the reader has
    downed the same account repeatedly the chips have usually named several
    different ones (@IBKR's six are all `promo`, but @afuseai's four are not). What
    the prior reads is the pattern the chips have in common: you keep saying no to
    this person. Filtering on `author` chips alone would throw away 55 of the 56
    downvotes that built the signal in the first place.
    """
    model = AuthorModel()
    for sample in samples:
        handle = normalize(sample.handle)
        if handle is None:
            continue
        side = model.down if sample.verdict == 'down' else model.up
        side[handle] = side.get(handle, 0.0) + LABEL_WEIGHT.get(sample.verdict, 1.0)
    return model


def score(model: AuthorModel, handle: Optional[str], settings: Settings) -> Optional[ChannelScore]:
    """This channel's opinion on a tweet, from its author's record alone.

    Abstains — `None`, never 0.0 — on an author with too little history, which is
    the honest answer for the account you are seeing for the first time and the
    reason this channel needs the text channels beside it.
    """
    key = normalize(handle)
    if key is None:
        return None
    observations = model.observations(key)
    if observations < settings.condenser_verdict_a_min_observations:
        return None

    down, up = model.down.get(key, 0.0), model.up.get(key, 0.0)
    rate = 1.0 - 2.0 * (down + ALPHA) / (down + up + 2 * ALPHA)
    evidence = observations / (observations + CONFIDENCE_SMOOTH)
    return ChannelScore(
        score=rate * evidence,
        confidence=evidence,
        corroborated=down >= MIN_DOWN_FOR_NEGATIVE,
        # the most readable evidence any channel produces: "you have downed @IBKR
        # six times" needs no distance metric or token list to interpret
        meta={'handle': key, 'up': round(up, 2), 'down': round(down, 2)},
    )
