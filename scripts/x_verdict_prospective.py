"""Prospective (online) precision of the For You verdict — the §9 monitoring half.

Plan: kb/plans/2026-07-27-x-verdict-style-channels.md (§9 as revised 2026-07-28,
§13 item 0).

The backtest picks an operating point and scores it on the same labels it picked
from. This script scores only what the judge committed to **before** the reader
said anything — no held-out set to assemble, no selection bias to argue about.
The sample builds itself: ``db.x_pending_verdict_rows`` never judges an
already-labeled tweet, so a For You row with both a verdict and a label was
judged first, full stop.

Read it in this order:

1. **coverage** — how much of the judged set has been read and labeled at all. A
   channel is not being validated just because it has been running; with nothing
   labeled there is simply no evidence yet, and every number below is anecdote.
2. **the matrix** — verdict against label, so the shape is visible before any
   percentage is.
3. **negative precision**, then **positive precision**, each against the base
   rate printed beside it, and each with its call count. §9's bar is 85% over 15
   calls with no *saved* item condemned.
4. **the shadow replay** — the same arithmetic on channels whose negative side is
   switched off, using the scores the archive keeps anyway. This is how a
   channel earns admission without being admitted first.

Two biases that no flag here can remove, so read them into every figure:

- a badge may change whether a tweet gets read and labeled at all (badge-only and
  no re-ranking keeps this small, not zero);
- channel B's ``corroborated`` is not fully archived (it counted every close
  neighbour; only the nearest five are stored), so B's shadow negatives are an
  upper bound on what it would really have cast. Channel A's rule is the down
  count sitting in its own evidence, so A's replay is exact.

Usage::

    uv run python scripts/x_verdict_prospective.py                    # local db
    CONDENSER_DB_PATH=tmp/prod-snapshot.db uv run python scripts/x_verdict_prospective.py --sweep
    ... --shadow b,d          # replay only these channels

Read-only on the database — unlike the backtest, this one never touches the KNN
index, so it is safe to point at a live copy.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from condenser import db, prospective  # noqa: E402
from condenser.config import get_settings  # noqa: E402
from condenser.prospective import Pair, Side  # noqa: E402

VERDICTS = ('positive', 'neutral', 'negative')
LABELS = ('up', 'save', 'down')

POSITIVE_THRESHOLDS = (0.15, 0.25, 0.35, 0.45)
NEGATIVE_THRESHOLDS = (-0.25, -0.35, -0.45, -0.55, -0.65)

# The plan's §9 bar for admitting (or retiring) a channel's negative side.
NEGATIVE_BAR, NEGATIVE_BAR_CALLS = 0.85, 15


def pct(value: Optional[float]) -> str:
    return f'{value:6.1%}' if value is not None else '     —'


def line(name: str, side: Side) -> str:
    condemned = f'  [saved condemned: {side.saved_misses}]' if side.saved_misses else ''
    return f'  {name:16s} precision {pct(side.precision)}  ({side.hits}/{side.calls} calls){condemned}'


def coverage() -> None:
    print('=== coverage: is there anything to measure yet? ===')
    rows = db.x_verdict_label_coverage()
    if not rows:
        print('  no For You row has been judged at all.')
        return
    for row in rows:
        print(
            f'  {row["verdict"]:9s} judged {row["judged"]:5d}   read {row["read"] or 0:5d}   '
            f'labeled {row["labeled"] or 0:5d}'
        )


def matrix(sample: list[Pair]) -> None:
    summary = prospective.summarize(sample)
    print(f'\n=== verdict x label — n={summary.total} pairs (judged first, labeled after) ===')
    print(f'  {"":10s}' + ''.join(f'{label:>8s}' for label in LABELS))
    for shown in VERDICTS:
        counts = [summary.matrix.get((shown, label), 0) for label in LABELS]
        if any(counts):
            print(f'  {shown:10s}' + ''.join(f'{count:8d}' for count in counts))
    print(f'  base rate: {pct(summary.base_rate)} of the labeled pairs were positives')
    algos = Counter(pair.algo or '(unknown)' for pair in sample)
    print(f'  algo mix: {dict(algos)}')


def as_shipped(sample: list[Pair]) -> None:
    """What the reader was actually shown — the only figures §9's kill switch acts on."""
    summary = prospective.summarize(sample)
    print('\n=== as shipped: the badges the reader saw ===')
    print(line('negative', summary.negative))
    print(line('positive', summary.positive))
    missed = summary.neutral_labels
    print(f'  {"neutral":16s} {sum(missed.values())} shrugs, labeled {dict(missed)}')
    verdict_bar(summary.negative, 'the running verdict')

    if summary.by_channel:
        print('\n  per channel (its own claim, even where the vote resolved against it):')
        for key in sorted(summary.by_channel):
            stats = summary.by_channel[key]
            print('  ' + line(f'{key}: negative', stats.negative))
            print('  ' + line(f'{key}: positive', stats.positive))


def verdict_bar(side: Side, what: str) -> None:
    if not side.calls:
        return
    clears = (side.precision or 0) >= NEGATIVE_BAR and side.calls >= NEGATIVE_BAR_CALLS and not side.saved_misses
    if side.saved_misses:
        print(f'  ⚠ {what}: a SAVED item was called negative — §9 says retire this negative side.')
    elif not clears:
        print(f'  ⚠ {what}: negative side below §9 ({NEGATIVE_BAR:.0%} over {NEGATIVE_BAR_CALLS} calls).')
    else:
        print(f'  ✓ {what}: negative side is holding above §9 ({NEGATIVE_BAR:.0%} over {NEGATIVE_BAR_CALLS} calls).')


def shadow(sample: list[Pair], keys: list[str], sweep: bool) -> None:
    """What a channel would have said at thresholds it never ran with.

    The point of the exercise: the score is archived even when the negative side
    is off, so a channel's admission case can be made out of production data
    instead of out of the backtest that keeps flattering itself.
    """
    settings = get_settings()
    print('\n=== shadow replay: what the archived scores would have called ===')
    for key in keys:
        scored = sum(1 for pair in sample if key in pair.scores)
        print(f'\n  channel {key} — spoke on {scored}/{len(sample)} pairs')
        if not scored:
            print('    (no archived score: this channel was not running in these rounds)')
            continue
        negatives = NEGATIVE_THRESHOLDS if sweep else (_negative_default(key, settings),)
        positives = POSITIVE_THRESHOLDS if sweep else (_positive_default(key, settings),)
        for threshold in negatives:
            result = prospective.shadow(sample, key, 1.0, threshold, settings)
            backed = (
                '' if result.corroborated_negatives is None else f'  [{result.corroborated_negatives} corroborated]'
            )
            print(line(f'neg <= {threshold:+.2f}', result.negative).rstrip() + backed)
        for threshold in positives:
            result = prospective.shadow(sample, key, threshold, -1.0, settings)
            print(line(f'pos >= {threshold:+.2f}', result.positive))


def _negative_default(key: str, settings) -> float:
    return getattr(settings, f'condenser_verdict_{key}_negative_score', settings.condenser_verdict_negative_score)


def _positive_default(key: str, settings) -> float:
    return getattr(settings, f'condenser_verdict_{key}_positive_score', settings.condenser_verdict_positive_score)


def misses(sample: list[Pair]) -> None:
    """Every wrong call, in full. At this sample size the individual tweets are the
    evidence — a percentage over two calls is not a measurement."""
    wrong = [pair for pair in sample if pair.verdict in ('positive', 'negative') and not pair.correct]
    if not wrong:
        return
    print('\n=== the wrong calls, one by one ===')
    for pair in wrong:
        text = ' '.join((pair.text or '').split())[:80]
        scores = ' '.join(f'{key}={value:+.3f}' for key, value in sorted(pair.scores.items()))
        print(
            f'  {pair.verdict:8s} but {pair.label:4s} ({pair.reason or "no reason"})  @{pair.handle or "?"}  {scores}'
        )
        print(f'    {text}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--shadow', default='', help='channels to replay (default: whichever left scores)')
    parser.add_argument(
        '--sweep', action='store_true', help='replay a grid of thresholds instead of the configured one'
    )
    args = parser.parse_args()

    settings = get_settings()
    db.init_db(settings.condenser_db_path, settings.condenser_embedding_dimensions)

    coverage()
    sample = prospective.pairs()
    if not sample:
        print('\nno judged-then-labeled pair yet — nothing to validate prospectively.')
        print('This is the expected state right after the cold-start gate opens: every label so far')
        print('predates the first judging round, so all of it is training data and none of it is evidence.')
        return 0

    matrix(sample)
    as_shipped(sample)
    keys = [key.strip() for key in args.shadow.split(',') if key.strip()] or sorted(
        {key for pair in sample for key in pair.scores}
    )
    shadow(sample, keys, args.sweep)
    misses(sample)
    print(
        '\nCaveats that travel with every number above: a badge may bias whether a tweet gets read'
        '\nand labeled at all, and shadow negatives are an upper bound (corroboration is not fully'
        '\narchived). Small samples are the norm here — read the call counts before the percentages.'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
