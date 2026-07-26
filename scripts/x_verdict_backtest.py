"""Leave-one-out backtest of the For You verdict, on your real labels.

This is the tool that turns the Phase 4 constants from guesses into decisions. It
never writes to the database: every label is held out in turn, judged against the
others, and the results are tallied per threshold setting.

Read the numbers in this order:

1. **coverage** — how often the judge commits at all. A classifier that answers
   "neutral" to everything is 100% precise and useless.
2. **negative precision** — of the tweets called `negative`, how many you really
   had marked down. This is the number that decides whether hiding (a later
   iteration) is ever safe: a wrong negative costs the tweet forever.
3. **positive precision** — cheaper to get wrong (a wrong recommendation costs
   one glance), so it may run looser.

Usage:

    uv run python scripts/x_verdict_backtest.py                  # current settings
    uv run python scripts/x_verdict_backtest.py --sweep          # try a grid
    uv run python scripts/x_verdict_backtest.py --embed-missing  # embed unlabeled gaps first

``--embed-missing`` is the only mode that calls the embedding API (and only for
labeled tweets that have no stored vector yet).

Two things this script does not yet know about, and whoever runs the sweep should:

- **The label set has a discontinuity.** Downs written before 2026-07-26 carry no
  `item_feedback.reason` (the chips did not exist); that is a real property of the
  data, not a gap to fill in.
- **The reasons are worth a sweep variant.** A down whose reason is `author`,
  `promo` or `ai_slop` is not a judgement about the tweet's *topic*, so feeding it
  to a topic-embedding kNN as a negative is the entanglement failure the design
  note describes — restricting the negative set to
  ``reason IS NULL OR reason = 'topic'`` is a one-line comparison against the
  current all-downs behavior. Untested; that is the point of running it here.

And a scope reminder, because this script makes it easy to believe the job ends
with a tuned D_MAX: today's single-channel kNN is the **baseline**, and the target
shape is the multi-channel ensemble in
``kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md`` — whose channels are
meant to be selected by exactly this leave-one-out harness.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condenser import db, embedding, vectors, verdict  # noqa: E402
from condenser.config import get_settings  # noqa: E402

# The label a correct judge would produce for each training label.
EXPECTED = {'up': verdict.POSITIVE, 'save': verdict.POSITIVE, 'down': verdict.NEGATIVE}


@dataclass
class Tally:
    total: int = 0
    committed: int = 0
    correct: int = 0
    positive_calls: int = 0
    positive_right: int = 0
    negative_calls: int = 0
    negative_right: int = 0

    def add(self, expected: str, got: str) -> None:
        self.total += 1
        if got == verdict.NEUTRAL:
            return
        self.committed += 1
        self.correct += got == expected
        if got == verdict.POSITIVE:
            self.positive_calls += 1
            self.positive_right += expected == verdict.POSITIVE
        else:
            self.negative_calls += 1
            self.negative_right += expected == verdict.NEGATIVE

    def line(self, prefix: str) -> str:
        def pct(hit: int, of: int) -> str:
            return f'{hit / of:6.1%}' if of else '     —'

        return (
            f'{prefix}  coverage {pct(self.committed, self.total)}  '
            f'accuracy {pct(self.correct, self.committed)}  '
            f'pos {pct(self.positive_right, self.positive_calls)} ({self.positive_calls})  '
            f'neg {pct(self.negative_right, self.negative_calls)} ({self.negative_calls})'
        )


def load_samples(settings) -> dict[int, tuple[str, list[float]]]:
    """Labeled tweets that have a stored vector for the current model."""
    labels = db.x_labeled_samples()
    blobs = db.x_embedding_vectors(set(labels), embedding.model_tag(settings))
    return {tid: (labels[tid], vectors.unpack(blob)) for tid, blob in blobs.items()}


async def embed_missing(settings) -> int:
    """Embed labeled tweets that have no vector yet (the only API-calling path)."""
    labels = db.x_labeled_samples()
    have = set(db.x_embedding_vectors(set(labels), embedding.model_tag(settings)))
    missing = sorted(set(labels) - have)
    if not missing:
        return 0
    manager = verdict.VerdictManager(settings)
    return await manager._embed_and_index(missing)


def leave_one_out(samples: dict[int, tuple[str, list[float]]], settings) -> Tally:
    """Judge each labeled tweet against all the others.

    The index is rebuilt per fold so the held-out tweet cannot vote for itself —
    the single most common way a backtest flatters a nearest-neighbour model.
    """
    tally = Tally()
    for held_out, (label, vector) in samples.items():
        others = {tid: lbl for tid, (lbl, _) in samples.items() if tid != held_out}
        vectors.clear()
        for tid in others:
            vectors.upsert(tid, samples[tid][1])
        hits = vectors.knn(vector, settings.condenser_verdict_k)
        neighbours = [verdict.Neighbour(tid, distance, others[tid]) for tid, distance in hits if tid in others]
        tally.add(EXPECTED[label], verdict.score_neighbours(neighbours, settings).verdict)
    return tally


def sweep(samples, settings) -> None:
    """Grid over the knobs the plan left as placeholders."""
    print('\nsweep (max_distance / min_neighbors / pos / neg):')
    for max_distance in (0.4, 0.5, 0.6, 0.7):
        for min_neighbors in (1, 3, 5):
            for positive, negative in ((0.25, -0.45), (0.35, -0.55), (0.45, -0.65)):
                tuned = settings.model_copy(
                    update={
                        'condenser_verdict_max_distance': max_distance,
                        'condenser_verdict_min_neighbors': min_neighbors,
                        'condenser_verdict_positive_score': positive,
                        'condenser_verdict_negative_score': negative,
                    }
                )
                prefix = f'  D{max_distance:.2f} M{min_neighbors} +{positive:.2f}/{negative:.2f}'
                print(leave_one_out(samples, tuned).line(prefix))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sweep', action='store_true', help='grid over distance/threshold settings')
    parser.add_argument(
        '--embed-missing', action='store_true', help='embed labeled tweets with no vector (uses the API)'
    )
    args = parser.parse_args()

    settings = get_settings()
    db.init_db(settings.condenser_db_path, settings.condenser_embedding_dimensions)
    if not vectors.available():
        print('sqlite-vec is not loadable here — nothing to backtest against.')
        return 1

    if args.embed_missing:
        print(f'embedded {await embed_missing(settings)} labeled tweets')

    samples = load_samples(settings)
    labels = db.x_labeled_samples()
    counts = {kind: sum(1 for label, _ in samples.values() if label == kind) for kind in ('up', 'save', 'down')}
    print(f'labels: {len(labels)} total, {len(samples)} with vectors {counts}')
    if len(samples) < 4:
        print('not enough embedded labels to backtest yet (try --embed-missing, then label some more).')
        return 1

    print('\ncurrent settings:')
    print(leave_one_out(samples, settings).line('  '))
    if args.sweep:
        sweep(samples, settings)

    # the folds trashed the live index; put it back
    print(f'\nrestored index: {verdict.rebuild_labeled_index()} vectors')
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
