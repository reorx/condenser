"""Leave-one-out backtest of the For You verdict, on your real labels.

This is the tool that turns constants into decisions, and — since the v2 plan —
the tool that decides which *channels* the verdict is made of at all. It never
writes to the database: every label is held out in turn, judged against the
others, and the results are tallied per channel, per setting, per threshold.

Read the numbers in this order:

1. **abstain / coverage** — how often the channel commits at all. A classifier
   that answers "neutral" to everything is 100% precise and useless, and it is
   the first way a new channel flatters itself.
2. **base rate** — printed next to every table on purpose. The 2026-07-27 finding
   that killed the negative side was 55.6% precision against a 49.2% base rate;
   without the comparison it reads as "not great but usable".
3. **negative precision** — of the tweets called `negative`, how many you really
   had marked down. This decides whether hiding is ever safe: a wrong negative
   costs the tweet. The bar for switching it back on is written down in the plan
   (§9) and is not to be relaxed in front of a pretty table.
4. **positive precision** — cheaper to get wrong (a wrong recommendation costs
   one glance), so it may run looser.

Usage::

    uv run python scripts/x_verdict_backtest.py                       # current settings, channel b
    uv run python scripts/x_verdict_backtest.py --channels b,d        # per-channel + combined
    uv run python scripts/x_verdict_backtest.py --channels b,d --sweep
    uv run python scripts/x_verdict_backtest.py --negatives topic     # drop style downs from training
    uv run python scripts/x_verdict_backtest.py --embed-missing       # embed labeled gaps first

``--embed-missing`` is the only mode that calls an API (and only for labeled
tweets that have no stored vector yet). Run everything against a **copy** of the
production database — the folds trash the KNN index and rebuild it at the end::

    ssh <host> 'sqlite3 /opt/apps/condenser/data/condenser.db ".backup /tmp/snap.db"'
    scp <host>:/tmp/snap.db tmp/prod-snapshot.db
    CONDENSER_DB_PATH=tmp/prod-snapshot.db uv run python scripts/x_verdict_backtest.py --channels b,d --sweep

Two properties of the label set that every reading has to account for:

- **There is a discontinuity.** Downs written before 2026-07-26 carry no
  ``item_feedback.reason`` (the chips did not exist); that is a property of the
  data, not a gap to fill in.
- **The reasons are a variant, not a footnote.** A down whose reason is `promo`,
  `ai_slop`, `engagement_farming` or `author` is not a judgement about the
  tweet's *topic*, so feeding it to a topic-embedding kNN as a negative is the
  entanglement failure the design note describes. ``--negatives topic`` runs
  without them; ``down recall by reason`` shows which kinds each channel can
  reproduce at all, which is how channel D earned its slot.
"""

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condenser import attributes, db, embedding, ngram, vectors, verdict  # noqa: E402
from condenser.channels import ChannelScore, combine  # noqa: E402
from condenser.config import Settings, get_settings  # noqa: E402
from condenser.db import ItemFeedback  # noqa: E402

# The label a correct judge would produce for each training label.
EXPECTED = {'up': verdict.POSITIVE, 'save': verdict.POSITIVE, 'down': verdict.NEGATIVE}

# Reasons that say something about *how* a tweet talks rather than what it is
# about — the ones a topic embedding structurally cannot represent.
STYLE_REASONS = ('promo', 'ai_slop', 'engagement_farming', 'author')

POSITIVE_THRESHOLDS = (0.15, 0.25, 0.35, 0.45)
NEGATIVE_THRESHOLDS = (-0.25, -0.35, -0.45, -0.55, -0.65)

# Below this many calls a precision figure is anecdote, not evidence.
MIN_CALLS_TO_RANK = 5
# The plan's §9 bar for ever switching negative verdicts back on.
NEGATIVE_BAR, NEGATIVE_BAR_CALLS = 0.85, 15

CURRENT = 'current'


@dataclass
class Sample:
    tweet_id: int
    label: str  # 'up' | 'save' | 'down'
    reason: Optional[str]  # the down chip, when there was one
    text: str  # what the judge reads (same text that got embedded)
    vector: Optional[list[float]]
    flags: list[str]  # the LLM's style flags (channel C); empty when undescribed

    @property
    def positive(self) -> bool:
        return self.label != 'down'

    @property
    def expected(self) -> str:
        return EXPECTED[self.label]


# --- channels -----------------------------------------------------------------
#
# A channel here is a thin harness wrapper around the production scoring code —
# never a reimplementation of it, or the backtest measures something that will
# never run. Each one is asked to `prepare` on the fold's training set, to capture
# threshold-independent `evidence` about the held-out tweet, and then to `score`
# that evidence under as many settings cells as the sweep wants (cheap, pure).


class TopicChannel:
    """Channel B — kNN over the embedding of the labeled tweets."""

    key = 'b'
    title = 'topic kNN (embeddings)'
    needs_vector = True

    def __init__(self, settings: Settings):
        self._k = settings.condenser_verdict_k  # not swept: it bounds the evidence, not the rule
        self._labels: dict[int, str] = {}

    def prepare(self, train: list[Sample]) -> None:
        self._labels = {sample.tweet_id: sample.label for sample in train}
        vectors.clear()
        for sample in train:
            vectors.upsert(sample.tweet_id, sample.vector)

    def evidence(self, sample: Sample) -> list[verdict.Neighbour]:
        hits = vectors.knn(sample.vector, self._k)
        return [verdict.Neighbour(tid, distance, self._labels[tid]) for tid, distance in hits if tid in self._labels]

    def score(self, evidence, settings: Settings) -> Optional[ChannelScore]:
        return verdict.topic_score(evidence, settings)

    def grid(self) -> list[tuple[str, dict]]:
        return [
            (
                f'D{distance:.2f} M{minimum}',
                {
                    'condenser_verdict_max_distance': distance,
                    'condenser_verdict_min_neighbors': minimum,
                },
            )
            for distance in (0.4, 0.5, 0.6, 0.7)
            for minimum in (1, 3, 5)
        ]


class AttributeChannel:
    """Channel C — per-attribute counts over the LLM's reading of each tweet."""

    key = 'c'
    title = 'LLM attributes (style flags)'
    needs_vector = False

    def __init__(self, settings: Settings):
        self._model = attributes.FlagModel()

    def prepare(self, train: list[Sample]) -> None:
        self._model = attributes.fit_flags(
            attributes.LabeledFlags(flags=sample.flags, verdict=sample.label, reason=sample.reason) for sample in train
        )

    def evidence(self, sample: Sample) -> tuple[attributes.FlagModel, list[str]]:
        return self._model, sample.flags

    def score(self, evidence, settings: Settings) -> Optional[ChannelScore]:
        model, flags = evidence
        return attributes.score_flags(model, flags, settings)

    def grid(self) -> list[tuple[str, dict]]:
        return [(f'obs>={minimum}', {'condenser_verdict_c_min_observations': minimum}) for minimum in (2, 4, 6, 10)]


class NgramChannel:
    """Channel D — naive Bayes over the words of the labeled tweets."""

    key = 'd'
    title = 'n-gram bayes (words)'
    needs_vector = False

    def __init__(self, settings: Settings):
        self._model = ngram.NgramModel()

    def prepare(self, train: list[Sample]) -> None:
        self._model = ngram.fit((sample.text, sample.positive) for sample in train)

    def evidence(self, sample: Sample) -> tuple[ngram.NgramModel, str]:
        return self._model, sample.text

    def score(self, evidence, settings: Settings) -> Optional[ChannelScore]:
        model, text = evidence
        return ngram.score(model, text, settings)

    def grid(self) -> list[tuple[str, dict]]:
        # `scale` is deliberately not gridded: it is a monotone squash, so moving it
        # is the same experiment as moving the thresholds, which the report already
        # sweeps. Gridding both would just print each operating point twice.
        return [
            (
                f'df{min_df} hits{hits} top{top} |w|{weight}',
                {
                    'condenser_verdict_d_min_df': min_df,
                    'condenser_verdict_d_min_hits': hits,
                    'condenser_verdict_d_top_tokens': top,
                    'condenser_verdict_d_min_weight': weight,
                },
            )
            for min_df in (2, 3)
            for hits in (3, 5)
            for top in (5, 8)
            for weight in (0.0, 0.5, 1.0)
        ]


CHANNELS = {'b': TopicChannel, 'c': AttributeChannel, 'd': NgramChannel}
DEFAULT_WEIGHTS = {'b': 1.0, 'c': 1.0, 'd': 0.5}


# --- data ---------------------------------------------------------------------


def load_samples(settings: Settings) -> list[Sample]:
    """Every label, with both representations the channels read."""
    labels = db.x_labeled_samples()
    reasons = {
        row.ref1: row.reason
        for row in ItemFeedback.select().where(ItemFeedback.source == 'x', ItemFeedback.verdict == 'down')
    }
    blobs = db.x_embedding_vectors(set(labels), embedding.model_tag(settings))
    texts = {row['tweet_id']: verdict.judge_text(row) for row in db.x_tweet_judge_rows(list(labels))}
    described = db.x_attributes_for(set(labels), attributes.model_tag(settings))
    return [
        Sample(
            tweet_id=tweet_id,
            label=label,
            reason=reasons.get(tweet_id),
            text=texts.get(tweet_id) or '',
            vector=vectors.unpack(blobs[tweet_id]) if tweet_id in blobs else None,
            flags=described.get(tweet_id, []),
        )
        for tweet_id, label in sorted(labels.items())
    ]


def usable(samples: list[Sample], channels: list) -> tuple[list[Sample], str]:
    """Restrict to labels every selected channel can read, so the folds are shared.

    Per-channel filtering would make the tables incomparable — which is the one
    thing this harness exists to prevent.
    """
    needs_vector = any(channel.needs_vector for channel in channels)
    keep = [sample for sample in samples if sample.text and (sample.vector is not None or not needs_vector)]
    dropped = len(samples) - len(keep)
    note = f' ({dropped} dropped: no {"vector" if needs_vector else "text"})' if dropped else ''
    return keep, note


def restrict_negatives(samples: list[Sample], mode: str) -> list[Sample]:
    """``topic``: train only on downs that were about the subject matter.

    The corollary of the 2026-07-27 backtest: a topic kNN fed style complaints
    learns nothing from them. Whether dropping them helps is a data question, and
    at 1 topic-down it could not be answered then — re-run this when the chip mix
    has moved.
    """
    if mode != 'topic':
        return samples
    return [s for s in samples if s.positive or s.reason in (None, 'topic')]


async def embed_missing(settings: Settings) -> int:
    """Embed labeled tweets that have no vector yet (the only API-calling path)."""
    labels = db.x_labeled_samples()
    have = set(db.x_embedding_vectors(set(labels), embedding.model_tag(settings)))
    missing = sorted(set(labels) - have)
    if not missing:
        return 0
    return await verdict.VerdictManager(settings)._embed_and_index(missing)


# --- the folds ----------------------------------------------------------------


@dataclass
class Cell:
    """One settings variant a channel is scored under."""

    label: str
    settings: Settings


def cells_for(channel, settings: Settings, sweep: bool) -> list[Cell]:
    """The current settings always come first — the combined report reads that cell."""
    cells = [Cell(CURRENT, settings)]
    if sweep:
        cells += [Cell(label, settings.model_copy(update=overrides)) for label, overrides in channel.grid()]
    return cells


def run_folds(channels: list, samples: list[Sample], cells: dict[str, list[Cell]]) -> dict:
    """Leave-one-out over every sample -> {(channel, cell): {tweet_id: score|None}}.

    The index is rebuilt per fold so the held-out tweet cannot vote for itself —
    the single most common way a backtest flatters a nearest-neighbour model. The
    n-gram counts are refit per fold for exactly the same reason.

    Evidence is captured once per fold and scored under every cell, so a sweep
    costs one pass of the expensive part instead of one per grid point.
    """
    scores = {(channel.key, cell.label): {} for channel in channels for cell in cells[channel.key]}
    for held_out in samples:
        train = [sample for sample in samples if sample.tweet_id != held_out.tweet_id]
        for channel in channels:
            channel.prepare(train)
            evidence = channel.evidence(held_out)
            for cell in cells[channel.key]:
                scores[(channel.key, cell.label)][held_out.tweet_id] = channel.score(evidence, cell.settings)
    return scores


def combined_scores(channels: list, scores: dict, weights: dict[str, float]) -> dict[int, Optional[ChannelScore]]:
    """The ensemble, at each channel's current settings."""
    tweet_ids = next(iter(scores.values())).keys()
    return {
        tweet_id: combine({channel.key: scores[(channel.key, CURRENT)][tweet_id] for channel in channels}, weights)
        for tweet_id in tweet_ids
    }


# --- reporting ----------------------------------------------------------------


@dataclass
class Side:
    calls: int = 0
    right: int = 0
    total: int = 0
    # Negative side only: wrong calls on a *saved* tweet — the plan's §9 condition 4
    # (clarified 2026-07-28). A save is the ×2-weight positive, so condemning one is
    # the most expensive mistake available; a wrong call on a mere thumbs-up is
    # bounded by the precision bar instead.
    saved_misses: int = 0

    def add(self, called: bool, correct: bool, saved: bool = False) -> None:
        self.total += 1
        self.calls += called
        self.right += called and correct
        self.saved_misses += called and not correct and saved

    @property
    def coverage(self) -> float:
        return self.calls / self.total if self.total else 0.0

    @property
    def precision(self) -> Optional[float]:
        return self.right / self.calls if self.calls else None


def pct(value: Optional[float]) -> str:
    return f'{value:6.1%}' if value is not None else '     —'


def side_metrics(samples: list[Sample], scores: dict, threshold: float, negative: bool) -> Side:
    """One polarity, evaluated on its own — the other side is never in the way.

    Decoupling matters: with both thresholds live in one run, a positive call
    silently removes a tweet from the negative side's denominator, and the two
    numbers stop meaning what their names say.
    """
    side = Side()
    for sample in samples:
        score = scores[sample.tweet_id]
        if score is None:
            side.total += 1
            continue
        called = (score.score <= threshold and score.corroborated) if negative else score.score >= threshold
        wanted = verdict.NEGATIVE if negative else verdict.POSITIVE
        side.add(called, sample.expected == wanted, saved=negative and sample.label == 'save')
    return side


def header(title: str, samples: list[Sample], scores: dict) -> None:
    positives = sum(1 for sample in samples if sample.positive)
    negatives = len(samples) - positives
    abstained = sum(1 for score in scores.values() if score is None)
    base = f'base rate pos {positives / len(samples):.1%} / neg {negatives / len(samples):.1%}'
    print(f'\n=== {title} — n={len(samples)} ({positives} pos / {negatives} neg, {base}) ===')
    print(f'    abstain {pct(abstained / len(samples))}  ({abstained}/{len(samples)} said nothing)')


def report(samples: list[Sample], scores: dict, settings: Settings, sweep: bool, where: str) -> list[dict]:
    """Coverage first, then the negative side, then the positive one (see the docstring)."""
    rows = []
    for negative, thresholds in (
        (True, NEGATIVE_THRESHOLDS if sweep else (settings.condenser_verdict_negative_score,)),
        (False, POSITIVE_THRESHOLDS if sweep else (settings.condenser_verdict_positive_score,)),
    ):
        for threshold in thresholds:
            metrics = side_metrics(samples, scores, threshold, negative)
            side = f'neg <= {threshold:+.2f}' if negative else f'pos >= {threshold:+.2f}'
            print(
                f'      {side}   coverage {pct(metrics.coverage)}  '
                f'precision {pct(metrics.precision)}  ({metrics.calls} calls)'
            )
            rows.append({'where': where, 'side': side, 'negative': negative, 'metrics': metrics})
    return rows


def summarize(rows: list[dict], settings: Settings) -> None:
    """The operating points worth arguing about, and whether any clears the bar.

    Three of the plan's four §9 conditions are checked here rather than eyeballed:
    >=85% precision, >=15 calls, and no *saved* tweet among the wrong negatives
    (condition 4, as clarified 2026-07-28 — a save is the ×2-weight positive, so
    condemning one is the most expensive mistake there is; a wrong call on a mere
    thumbs-up is what the precision bar is for). The fourth, "clearly above the
    base rate", stays a human call — it is printed beside every table, because a
    number that clears the bar while sitting on the base rate means the label set,
    not the classifier, is doing the work.
    """
    ranked = [row for row in rows if row['metrics'].calls >= MIN_CALLS_TO_RANK]
    ranked.sort(key=lambda row: (-(row['metrics'].precision or 0), -row['metrics'].calls))
    print(f'\n=== operating points with >= {MIN_CALLS_TO_RANK} calls, best precision first ===')
    for row in ranked[:15]:
        metrics = row['metrics']
        clears = (
            row['negative']
            and (metrics.precision or 0) >= NEGATIVE_BAR
            and metrics.calls >= NEGATIVE_BAR_CALLS
            and not metrics.saved_misses
        )
        condemned = f'  [{metrics.saved_misses} saved condemned]' if metrics.saved_misses else ''
        print(
            f'  {"*" if clears else " "} {pct(metrics.precision)} precision  {metrics.calls:3d} calls  '
            f'coverage {pct(metrics.coverage)}   {row["side"]}   {row["where"]}{condemned}'
        )
    if not any(row['negative'] for row in ranked):
        print('  (no negative operating point committed often enough to rank)')
    print(
        f"  * = clears the plan's §9 bar for re-enabling negative verdicts "
        f'({NEGATIVE_BAR:.0%} precision, {NEGATIVE_BAR_CALLS} calls, no saved tweet condemned).'
        '\n      Yours to judge: whether it beats the base rate above, and that picking the best'
        '\n      cell out of a grid scored on the same labels flatters whatever it picks.'
    )


def per_reason(samples: list[Sample], scores: dict, settings: Settings) -> None:
    """Which kinds of down can this channel reproduce at all?

    The table that explained the 2026-07-27 failure: at the best negative setting
    the topic kNN recovered 2 of 11 `promo` downs and 0 of everything else, which
    is what "the embedding cannot see style" looks like in numbers.
    """
    downs = [sample for sample in samples if not sample.positive]
    if not downs:
        return
    negative = settings.condenser_verdict_negative_score
    positive = settings.condenser_verdict_positive_score
    print(f'    down recall by reason (neg <= {negative:+.2f}, pos >= {positive:+.2f}):')
    tally: Counter = Counter()
    for sample in downs:
        reason = sample.reason or '(none)'
        score = scores[sample.tweet_id]
        tally[(reason, 'n')] += 1
        if score is None:
            tally[(reason, 'abstain')] += 1
        elif score.score <= negative and score.corroborated:
            tally[(reason, 'recalled')] += 1
        elif score.score >= positive:
            tally[(reason, 'wrong')] += 1
    for reason in sorted({key[0] for key in tally}):
        print(
            f'      {reason:20s} n={tally[(reason, "n")]:2d}  recalled {tally[(reason, "recalled")]:2d}  '
            f'called POSITIVE {tally[(reason, "wrong")]:2d}  abstained {tally[(reason, "abstain")]:2d}'
        )


def parse_weights(raw: str) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    for part in filter(None, raw.split(',')):
        key, _, value = part.partition('=')
        weights[key.strip()] = float(value)
    return weights


# --- entry point --------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--channels', default='b', help=f'comma-separated: {",".join(CHANNELS)} (default: b)')
    parser.add_argument('--weights', default='', help='combiner weights, e.g. b=1.0,d=0.5')
    parser.add_argument('--sweep', action='store_true', help="grid over each channel's settings")
    parser.add_argument('--negatives', choices=('all', 'topic'), default='all', help='which downs train (default: all)')
    parser.add_argument(
        '--embed-missing', action='store_true', help='embed labeled tweets with no vector (uses the API)'
    )
    args = parser.parse_args()

    settings = get_settings()
    db.init_db(settings.condenser_db_path, settings.condenser_embedding_dimensions)

    keys = [key.strip() for key in args.channels.split(',') if key.strip()]
    unknown = [key for key in keys if key not in CHANNELS]
    if unknown:
        print(f'unknown channel(s): {",".join(unknown)} (have: {",".join(CHANNELS)})')
        return 1
    channels = [CHANNELS[key](settings) for key in keys]
    if any(channel.needs_vector for channel in channels) and not vectors.available():
        print('sqlite-vec is not loadable here — channel b cannot run (try --channels d).')
        return 1

    if args.embed_missing:
        print(f'embedded {await embed_missing(settings)} labeled tweets')

    samples, note = usable(load_samples(settings), channels)
    samples = restrict_negatives(samples, args.negatives)
    counts = Counter(sample.label for sample in samples)
    print(f'labels: {len(samples)} usable{note}  {dict(counts)}  negatives={args.negatives}')
    if len(samples) < 4 or not any(not sample.positive for sample in samples):
        print('not enough labels on both sides to backtest yet (try --embed-missing, then label some more).')
        return 1

    cells = {channel.key: cells_for(channel, settings, args.sweep) for channel in channels}
    scores = run_folds(channels, samples, cells)

    weights = parse_weights(args.weights)
    rows = []
    for channel in channels:
        for cell in cells[channel.key]:
            title = f'channel {channel.key}: {channel.title}'
            where = channel.key if cell.label == CURRENT else f'{channel.key} [{cell.label}]'
            if cell.label != CURRENT:
                title = f'{title}  [{cell.label}]'
            cell_scores = scores[(channel.key, cell.label)]
            header(title, samples, cell_scores)
            rows += report(samples, cell_scores, cell.settings, args.sweep, where)
            if cell.label == CURRENT:
                per_reason(samples, cell_scores, cell.settings)

    if len(channels) > 1:
        mixed = combined_scores(channels, scores, weights)
        used = {channel.key: weights.get(channel.key, 0.0) for channel in channels}
        header(f'combined ({used}) — each channel at its current settings', samples, mixed)
        rows += report(samples, mixed, settings, args.sweep, 'combined')
        per_reason(samples, mixed, settings)

    summarize(rows, settings)
    if any(channel.needs_vector for channel in channels):
        # the folds trashed the live index; put it back
        print(f'\nrestored index: {verdict.rebuild_labeled_index()} vectors')
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
