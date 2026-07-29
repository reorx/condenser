"""Behavior tests for the prospective (online) verdict monitor — plan v2 step 5.

Plan: kb/plans/2026-07-27-x-verdict-style-channels.md (§9 as revised 2026-07-28,
§13 item 0)

The revised §9 replaced "hold out a set and pass a one-shot gate" with "admit a
channel's negative side, then keep measuring it in production". This module is the
measuring half, and it rests on one structural fact rather than on a timestamp:

    ``db.x_pending_verdict_rows`` never judges an already-labeled tweet.

So a For You row that has **both** a verdict and a label was necessarily judged
first and labeled afterwards — every such pair is out-of-sample by construction,
with none of the selection bias the leave-one-out backtest carries (it picks its
operating point and scores it on the same 59 labels). No ``verdict_at`` column is
needed, which is why there is none.

The tests below pin the accounting, not the classifier: which rows count as a
call, which count as a hit, what makes a wrong negative the expensive kind (a
*saved* item — §9's kill trigger), and that the archived scores can be replayed at
thresholds nobody was running, so a channel's negative side can be evaluated
before it is ever admitted.
"""

import json
import os
from datetime import datetime, timedelta

from condenser import db, prospective
from condenser.config import get_settings

NOW = datetime(2026, 7, 28, 12, 0)


def setup_db(monkeypatch, **overrides) -> None:
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    db.init_db(os.environ['CONDENSER_DB_PATH'])


def judged(tweet_id: int, verdict: str, meta: dict | None = None, minutes: int = 0, feed: str = 'foryou') -> None:
    """A For You appearance that has already been judged."""
    db.XTweet.create(id=tweet_id, author_handle='someone', text=f'tweet {tweet_id}', fetched_at=NOW)
    db.XFeedItem.create(
        channel_id=feed,
        tweet_id=tweet_id,
        first_seen_at=NOW - timedelta(minutes=minutes),
        verdict=verdict,
        verdict_meta=json.dumps(meta if meta is not None else {'score': 0.0, 'neighbors': [], 'algo': 'knn-v1'}),
    )


def unjudged(tweet_id: int, minutes: int = 0) -> None:
    db.XTweet.create(id=tweet_id, author_handle='someone', text=f'tweet {tweet_id}', fetched_at=NOW)
    db.XFeedItem.create(channel_id='foryou', tweet_id=tweet_id, first_seen_at=NOW - timedelta(minutes=minutes))


def label(tweet_id: int, verdict: str, reason: str | None = None) -> None:
    db.set_feedback(db.ItemKey(source='x', ref1=tweet_id), verdict, reason)


def save(tweet_id: int) -> None:
    db.SavedItem.create(source='x', ref1=tweet_id, ref2=0, raw_data='{}', created_at=NOW)


def knn_meta(score: float, downs: int = 0, ups: int = 0) -> dict:
    """A channel-B (knn-v1) meta blob with the archived nearest neighbours."""
    neighbors = [{'tweet_id': str(900 + i), 'distance': 0.2, 'label': 'down'} for i in range(downs)]
    neighbors += [{'tweet_id': str(950 + i), 'distance': 0.2, 'label': 'up'} for i in range(ups)]
    return {'score': score, 'neighbors': neighbors, 'algo': 'knn-v1', 'model': 'fake@256'}


def vote_meta(channels: dict[str, tuple[str, float]], score: float = 0.0) -> dict:
    """A vote-v1 meta blob: the top level stays channel B's, plus the channels block."""
    return {
        'score': score,
        'neighbors': [],
        'algo': 'vote-v1',
        'channels': {key: {'verdict': vote, 'score': value} for key, (vote, value) in channels.items()},
    }


# --- what counts as a pair ------------------------------------------------------


def test_only_judged_then_labeled_rows_are_pairs(env, monkeypatch):
    """The whole sample: a verdict *and* a label on the same For You row.

    A judged tweet nobody labeled has no ground truth; a labeled tweet with no
    verdict was labeled before the judge ever saw it (that is exactly why
    ``x_pending_verdict_rows`` skipped it) and says nothing about the judge.
    """
    setup_db(monkeypatch)
    judged(1, 'positive')
    label(1, 'up')
    judged(2, 'neutral')  # judged, never labeled
    unjudged(3)
    label(3, 'down')  # labeled, never judged

    assert [pair.tweet_id for pair in prospective.pairs()] == [1]


def test_followed_feeds_are_not_judged_and_do_not_count(env, monkeypatch):
    """Only For You is judged, so only For You can be scored."""
    setup_db(monkeypatch)
    judged(1, 'positive', feed='someone')
    label(1, 'up')

    assert prospective.pairs() == []


def test_a_save_outranks_a_thumb_and_a_contradiction_is_dropped(env, monkeypatch):
    """Mirrors ``db.x_labeled_samples``: the training set and the scoring set must
    agree on what a label *is*, or the monitor grades a different reader."""
    setup_db(monkeypatch)
    judged(1, 'positive')
    label(1, 'up')
    save(1)
    judged(2, 'positive')
    label(2, 'down')
    save(2)  # saved *and* downvoted: contradictory, teaches nothing

    labels = {pair.tweet_id: pair.label for pair in prospective.pairs()}
    assert labels == {1: 'save'}


# --- the as-shipped report ------------------------------------------------------


def test_positive_precision_counts_ups_and_saves_as_hits(env, monkeypatch):
    setup_db(monkeypatch)
    judged(1, 'positive')
    label(1, 'up')
    judged(2, 'positive')
    save(2)
    judged(3, 'positive')
    label(3, 'down')

    summary = prospective.summarize(prospective.pairs())
    assert (summary.positive.calls, summary.positive.hits) == (3, 2)
    assert round(summary.positive.precision, 3) == 0.667


def test_neutral_verdicts_are_not_calls_but_their_labels_are_reported(env, monkeypatch):
    """A shrug is not a claim, so it cannot be wrong — but a channel that shrugs at
    everything is useless, and the neutral label mix is the only place that shows."""
    setup_db(monkeypatch)
    judged(1, 'neutral')
    label(1, 'down')
    judged(2, 'neutral')
    label(2, 'up')
    judged(3, 'negative')
    label(3, 'down')

    summary = prospective.summarize(prospective.pairs())
    assert summary.positive.calls == 0
    assert summary.negative.calls == 1
    assert summary.neutral_labels == {'down': 1, 'up': 1}


def test_base_rate_is_reported_beside_precision(env, monkeypatch):
    """The 2026-07-27 lesson: 55.6% precision reads as usable until the 49.2% base
    rate is printed next to it. A prospective table repeats that mistake unless the
    share of positive labels travels with it."""
    setup_db(monkeypatch)
    for tweet_id in (1, 2, 3):
        judged(tweet_id, 'neutral')
        label(tweet_id, 'up')
    judged(4, 'neutral')
    label(4, 'down')

    assert prospective.summarize(prospective.pairs()).base_rate == 0.75


def test_a_saved_item_called_negative_is_the_kill_trigger(env, monkeypatch):
    """§9's most expensive error, and the one condition that is not a percentage:
    a *saved* item badged "not for you" retires the channel's negative side."""
    setup_db(monkeypatch)
    judged(1, 'negative')
    save(1)
    judged(2, 'negative')
    label(2, 'up')  # wrong too, but only the cheap kind
    judged(3, 'negative')
    label(3, 'down')

    summary = prospective.summarize(prospective.pairs())
    assert summary.negative.saved_misses == [1]
    assert summary.negative.calls == 3 and summary.negative.hits == 1


# --- attribution ----------------------------------------------------------------


def test_a_negative_is_attributed_to_the_channels_that_voted_for_it(env, monkeypatch):
    """The property the vote combiner exists for: §9 kills *one channel's* negative
    side, so a wrong negative has to name the channel that cast it."""
    setup_db(monkeypatch)
    judged(1, 'negative', vote_meta({'b': ('neutral', -0.1), 'd': ('negative', -0.6)}))
    label(1, 'up')
    judged(2, 'negative', vote_meta({'c': ('negative', -0.3), 'd': ('negative', -0.5)}))
    label(2, 'down')

    summary = prospective.summarize(prospective.pairs())
    assert summary.by_channel['d'].negative.calls == 2
    assert summary.by_channel['d'].negative.hits == 1
    assert summary.by_channel['c'].negative.calls == 1
    assert 'b' not in summary.by_channel or summary.by_channel['b'].negative.calls == 0


def test_single_channel_rounds_are_attributed_to_channel_b(env, monkeypatch):
    """Rounds archived before the ensemble carry no channels block; their verdicts
    were channel B's alone, and the history must not be dropped for lacking a field
    that did not exist yet."""
    setup_db(monkeypatch)
    judged(1, 'positive', knn_meta(0.5, ups=3))
    label(1, 'up')

    summary = prospective.summarize(prospective.pairs())
    assert summary.by_channel['b'].positive.calls == 1


# --- shadow replay --------------------------------------------------------------


def test_shadow_replays_archived_scores_at_thresholds_nobody_ran(env, monkeypatch):
    """The reason this is worth building: the score is archived even when the
    channel's negative side is switched off, so "what would admitting it have
    done?" is answerable from production data — prospectively — before admitting
    anything."""
    setup_db(monkeypatch)
    judged(1, 'neutral', knn_meta(-0.6, downs=2))
    label(1, 'down')
    judged(2, 'neutral', knn_meta(-0.5, downs=2))
    label(2, 'up')
    judged(3, 'neutral', knn_meta(0.1))
    label(3, 'up')

    at_45 = prospective.shadow(prospective.pairs(), 'b', positive_score=0.25, negative_score=-0.45)
    assert (at_45.negative.calls, at_45.negative.hits) == (2, 1)

    at_55 = prospective.shadow(prospective.pairs(), 'b', positive_score=0.25, negative_score=-0.55)
    assert (at_55.negative.calls, at_55.negative.hits) == (1, 1)


def test_shadow_skips_pairs_where_the_channel_never_spoke(env, monkeypatch):
    """Abstention is not a score of zero (the channels.py rule). A pair judged in a
    round that channel D did not run must not be counted as D shrugging."""
    setup_db(monkeypatch)
    judged(1, 'neutral', vote_meta({'b': ('neutral', 0.0), 'd': ('neutral', -0.9)}))
    label(1, 'down')
    judged(2, 'neutral', knn_meta(-0.9, downs=2))  # channel D was not running yet
    label(2, 'down')

    result = prospective.shadow(prospective.pairs(), 'd', positive_score=0.25, negative_score=-0.45)
    assert result.scored == 1
    assert (result.negative.calls, result.negative.hits) == (1, 1)


def test_shadow_corroborates_the_author_prior_exactly(env, monkeypatch):
    """Channel A is the one channel whose corroboration replays *exactly*.

    B's rule counts close neighbours and only the nearest five are archived, so its
    replay is an upper bound. A's rule is "two downs on this account", and the down
    count is right there in the archived evidence — so the shadow can say what the
    channel would really have done, which is what admitting it turns on."""
    setup_db(monkeypatch)
    meta = vote_meta({'a': ('neutral', -0.56)})
    meta['channels']['a'].update({'handle': 'ibkr', 'down': 6, 'up': 0, 'shadow': True})
    judged(1, 'neutral', meta)
    label(1, 'down')
    thin = vote_meta({'a': ('neutral', -0.5)})
    thin['channels']['a'].update({'handle': 'someone', 'down': 1, 'up': 0, 'shadow': True})
    judged(2, 'neutral', thin)
    label(2, 'down')

    result = prospective.shadow(prospective.pairs(), 'a', positive_score=0.25, negative_score=-0.25)

    assert (result.negative.calls, result.negative.hits) == (2, 2)
    assert result.corroborated_negatives == 1  # only the six-down account clears the rule


def test_shadow_reports_how_many_negatives_the_archive_can_corroborate(env, monkeypatch):
    """Honesty about what a replay cannot know: ``corroborated`` was computed over
    every close neighbour, and only the nearest five are archived. So a shadow
    negative count is an upper bound, and the report says how much of it the
    evidence actually backs."""
    setup_db(monkeypatch)
    judged(1, 'neutral', knn_meta(-0.8, downs=2))
    label(1, 'down')
    judged(2, 'neutral', knn_meta(-0.8, downs=1, ups=1))
    label(2, 'down')

    result = prospective.shadow(prospective.pairs(), 'b', positive_score=0.25, negative_score=-0.45)
    assert result.negative.calls == 2
    assert result.corroborated_negatives == 1
