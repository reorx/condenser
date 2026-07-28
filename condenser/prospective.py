"""Prospective (online) measurement of the verdict — the monitoring half of §9.

Plan: kb/plans/2026-07-27-x-verdict-style-channels.md (§9 as revised 2026-07-28).

The leave-one-out backtest picks an operating point and scores it on the same
labels it picked from; that is selection bias, and no amount of folding removes
it. This module measures the other kind of evidence, the kind that cannot be
tuned against: tweets the judge committed to **before** the reader said anything.

The sample needs no timestamp. ``db.x_pending_verdict_rows`` never judges an
already-labeled tweet, so a For You row holding both a verdict and a label was
necessarily judged first — every pair here is out-of-sample by construction.

Two things it reports that the backtest structurally cannot:

* **the as-shipped verdict** — what the reader was actually shown, per channel
  that voted for it, so §9's kill switch has something to point at;
* **the shadow replay** — the archived score classified at thresholds nobody was
  running. Since the score is stored even when a channel's negative side is off,
  "what would admitting this have cost?" is answerable from production data
  before anything is admitted.

Two biases to carry while reading it, neither of them fixable here: a badge may
influence whether a tweet gets read and labeled at all (badge-only and no
re-ranking keeps it small, not zero), and ``corroborated`` was computed over
every close neighbour while only the nearest five are archived — so a shadow
negative count is an upper bound.
"""

import json
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import db
from .channels import NEGATIVE, POSITIVE
from .config import Settings, get_settings

# What a correct judge would have said about each label.
LABEL_EXPECTED = {'up': POSITIVE, 'save': POSITIVE, 'down': NEGATIVE}

# Meta ``reason`` values that mean "no channel spoke" rather than "the score was
# 0.0" — the abstention/neutral distinction, carried into the archive.
ABSTAIN_REASONS = ('out_of_domain', 'no_text')


@dataclass
class Pair:
    """One judged-then-labeled For You row."""

    tweet_id: int
    verdict: str
    label: str  # 'up' | 'down' | 'save'
    reason: Optional[str] = None  # the down chip
    handle: Optional[str] = None
    text: Optional[str] = None
    algo: Optional[str] = None
    scores: dict[str, float] = field(default_factory=dict)  # channel -> archived score
    votes: dict[str, str] = field(default_factory=dict)  # channel -> archived vote
    evidence: dict[str, dict] = field(default_factory=dict)  # channel -> its archived block
    down_neighbours: int = 0  # downs among the archived nearest five (channel B)

    @property
    def expected(self) -> str:
        return LABEL_EXPECTED[self.label]

    @property
    def correct(self) -> bool:
        return self.verdict == self.expected


@dataclass
class Side:
    """One side of one judge: what it claimed and how that turned out."""

    calls: int = 0
    hits: int = 0
    misses: list[int] = field(default_factory=list)
    saved_misses: list[int] = field(default_factory=list)

    @property
    def precision(self) -> Optional[float]:
        return self.hits / self.calls if self.calls else None

    def record(self, pair: Pair, side: str) -> None:
        self.calls += 1
        if pair.expected == side:
            self.hits += 1
            return
        self.misses.append(pair.tweet_id)
        if pair.label == 'save':
            # §9's one non-percentage condition: a saved item is the reader's
            # strongest positive, and calling it "not for you" is the expensive
            # mistake that retires a channel's negative side outright.
            self.saved_misses.append(pair.tweet_id)


@dataclass
class ChannelStats:
    positive: Side = field(default_factory=Side)
    negative: Side = field(default_factory=Side)


@dataclass
class Summary:
    total: int = 0
    matrix: dict[tuple[str, str], int] = field(default_factory=dict)  # (verdict, label) -> n
    positive: Side = field(default_factory=Side)
    negative: Side = field(default_factory=Side)
    neutral_labels: dict[str, int] = field(default_factory=dict)
    base_rate: Optional[float] = None  # share of positive labels — read every precision against it
    by_channel: dict[str, ChannelStats] = field(default_factory=dict)


@dataclass
class Shadow:
    """What one channel would have said at thresholds it was never run with."""

    channel: str
    positive_score: float
    negative_score: float
    scored: int = 0  # pairs where this channel left a score at all
    positive: Side = field(default_factory=Side)
    negative: Side = field(default_factory=Side)
    # How many shadow negatives the archived evidence can actually corroborate.
    # None where the archive does not carry it (only channel B's neighbours do).
    corroborated_negatives: Optional[int] = None


# --- building the sample ---------------------------------------------------------


def pairs() -> list[Pair]:
    return build(db.x_prospective_rows())


def build(rows: Iterable[dict]) -> list[Pair]:
    """Rows -> pairs, resolving the label exactly as the training set does.

    A save outranks a thumb (it is the stronger positive) and a tweet both saved
    and downvoted is contradictory, so it is dropped rather than tie-broken — the
    same rule as ``db.x_labeled_samples``, because a monitor that scored a
    different reader than the one the model trained on would measure nothing.
    """
    out = []
    for row in rows:
        label = _label(row)
        if label is None:
            continue
        meta = _meta(row.get('verdict_meta'))
        scores, votes, evidence = _channels(meta, row['verdict'])
        out.append(
            Pair(
                tweet_id=row['tweet_id'],
                verdict=row['verdict'],
                label=label,
                reason=row.get('reason'),
                handle=row.get('author_handle'),
                text=row.get('text'),
                algo=meta.get('algo'),
                scores=scores,
                votes=votes,
                evidence=evidence,
                down_neighbours=sum(1 for n in meta.get('neighbors') or [] if n.get('label') == 'down'),
            )
        )
    return out


def _label(row: dict) -> Optional[str]:
    feedback, saved = row.get('feedback'), row.get('saved_at') is not None
    if feedback == 'down':
        return None if saved else 'down'
    return 'save' if saved else feedback


def _meta(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _channels(meta: dict, verdict: str) -> tuple[dict[str, float], dict[str, str], dict[str, dict]]:
    """The per-channel evidence, across both archive shapes.

    An ensemble round writes a ``channels`` block naming every channel that spoke.
    A single-channel round predates it and carries channel B's score at the top
    level — unless B abstained, in which case the archive says so with a ``reason``
    and there is no score to read (0.0 there means "nothing", not "neutral").
    """
    block = meta.get('channels')
    if isinstance(block, dict):
        scores = {key: value['score'] for key, value in block.items() if isinstance(value, dict) and 'score' in value}
        votes = {
            key: value['verdict'] for key, value in block.items() if isinstance(value, dict) and value.get('verdict')
        }
        return scores, votes, {key: value for key, value in block.items() if isinstance(value, dict)}
    if meta.get('reason') in ABSTAIN_REASONS or 'score' not in meta:
        return {}, {}, {}
    return {'b': meta['score']}, {'b': verdict}, {'b': {'score': meta['score'], 'neighbors': meta.get('neighbors', [])}}


# --- the as-shipped report -------------------------------------------------------


def summarize(sample: list[Pair]) -> Summary:
    """What the reader was actually shown, and how it turned out.

    ``by_channel`` counts a channel's own claim even when the vote resolved
    against it (a conflict lands neutral): admission is per channel, so a channel
    is measured on what it said, not on what the combiner did with it.
    """
    summary = Summary(total=len(sample))
    positives = 0
    for pair in sample:
        summary.matrix[(pair.verdict, pair.label)] = summary.matrix.get((pair.verdict, pair.label), 0) + 1
        positives += pair.expected == POSITIVE
        if pair.verdict == POSITIVE:
            summary.positive.record(pair, POSITIVE)
        elif pair.verdict == NEGATIVE:
            summary.negative.record(pair, NEGATIVE)
        else:
            summary.neutral_labels[pair.label] = summary.neutral_labels.get(pair.label, 0) + 1
        for key, vote in pair.votes.items():
            stats = summary.by_channel.setdefault(key, ChannelStats())
            if vote == POSITIVE:
                stats.positive.record(pair, POSITIVE)
            elif vote == NEGATIVE:
                stats.negative.record(pair, NEGATIVE)
    summary.base_rate = positives / len(sample) if sample else None
    return summary


# --- the shadow replay -----------------------------------------------------------


def shadow(
    sample: list[Pair],
    key: str,
    positive_score: float,
    negative_score: float,
    settings: Optional[Settings] = None,
) -> Shadow:
    """Replay one channel's archived scores at a threshold pair it never ran with.

    Threshold-only on purpose: ``corroborated`` was computed from evidence that is
    not fully archived, so it cannot be replayed. The negatives here are therefore
    an upper bound, and ``corroborated_negatives`` says how many of them the stored
    evidence still backs (channel B only — its neighbours carry their labels).
    """
    settings = settings or get_settings()
    result = Shadow(channel=key, positive_score=positive_score, negative_score=negative_score)
    corroborated = 0
    for pair in sample:
        if key not in pair.scores:
            continue  # the channel abstained, or was not running that round
        result.scored += 1
        score = pair.scores[key]
        if score >= positive_score:
            result.positive.record(pair, POSITIVE)
        elif score <= negative_score:
            result.negative.record(pair, NEGATIVE)
            corroborated += pair.down_neighbours >= settings.condenser_verdict_min_down_neighbors
    if key == 'b':
        result.corroborated_negatives = corroborated
    return result
