"""Behavior tests for channel C — scoring a tweet from its extracted attributes.

Plan: kb/plans/2026-07-27-x-verdict-style-channels.md (step 3)

Step 2 taught an LLM to say *what a tweet is and how it talks*. This step turns
those attributes into an opinion, and the interesting half is **credit
assignment**, which is the reason the down-reason chips were built in the first
place: a thumbs-down with the chip 「广告营销」 says *the promo attribute of this
tweet* earned the down — not its emoji, not its subject, not its author. A bag of
flags all penalized together is exactly the averaging defect that killed the
topic kNN's negative side, reproduced one layer up.

The live smoke test on real labels (2026-07-28) is what makes this concrete: all
six sampled downvotes carried `promo_cta` — and so did two of six *upvotes*, both
of them recommendations the reader liked. So no flag is inherently bad, and the
channel has to learn each flag's rate from the labels rather than assume it.
"""

import pytest

from condenser import attributes as attrs
from condenser.config import get_settings


def labeled(flags, verdict, reason=None):
    """One training sample: the tweet's flags, the reader's label, and the chip."""
    return attrs.LabeledFlags(flags=flags, verdict=verdict, reason=reason)


def score(model, flags, **overrides):
    return attrs.score_flags(model, flags, get_settings().model_copy(update=overrides))


@pytest.fixture
def model():
    """Bait was downed for being bait; the same tweets happen to advertise something.

    ``promo_cta`` is the innocent bystander here because ``emoji_spam`` stopped being
    one on 2026-07-29: 「博眼球」 now accuses it, so an engagement_farming down does
    charge it. Only a chip that names *another* attribute can leave a flag innocent.
    """
    return attrs.fit_flags(
        [
            labeled(['engagement_bait', 'promo_cta'], 'down', 'engagement_farming'),
            labeled(['engagement_bait', 'promo_cta'], 'down', 'engagement_farming'),
            labeled(['engagement_bait'], 'down', 'engagement_farming'),
            labeled(['promo_cta'], 'up'),
            labeled(['listicle'], 'up'),
            labeled(['listicle'], 'up'),
        ]
    )


# --- credit assignment ----------------------------------------------------------


def test_a_reason_credits_the_attribute_it_names(env, model):
    """The chip's whole purpose. Two downs carried `promo_cta` alongside the bait,
    but the reader said the bait was the problem — so the promo must come out of this
    innocent, or the channel has just re-invented "penalize the whole bag"."""
    bait = score(model, ['engagement_bait'], condenser_verdict_c_min_observations=1)
    promo = score(model, ['promo_cta'], condenser_verdict_c_min_observations=1)

    assert bait.score < 0
    assert promo.score > 0  # its only *credited* appearance was on a tweet you liked


def test_a_down_with_no_reason_is_shared_out_across_the_flags(env):
    """Pre-chip labels (before 2026-07-26) and skipped chips are bag-level by nature.
    Spreading the blame — rather than charging every flag in full — keeps one
    unexplained down from convicting three attributes at once."""
    liked = [labeled(['promo_cta'], 'up')]  # a baseline so every corpus clears the gate
    untouched = attrs.fit_flags(liked)
    spread = attrs.fit_flags([labeled(['promo_cta', 'emoji_spam'], 'down'), *liked])
    focused = attrs.fit_flags([labeled(['promo_cta', 'emoji_spam'], 'down', 'promo'), *liked])
    loose = {'condenser_verdict_c_min_observations': 1}

    # the same downvote on the same tweet, with and without the chip
    assert (
        score(focused, ['promo_cta'], **loose).score
        < score(spread, ['promo_cta'], **loose).score
        < score(untouched, ['promo_cta'], **loose).score
    )


def test_a_reason_this_channel_cannot_represent_teaches_it_nothing(env):
    """`topic` belongs to the embedding channel and `author` to the author prior.
    Feeding them here would repeat the original mistake in a new coat of paint."""
    off_topic = attrs.fit_flags(
        [
            labeled(['promo_cta'], 'down', 'topic'),
            labeled(['promo_cta'], 'down', 'author'),
            labeled(['listicle'], 'up'),
        ]
    )

    assert score(off_topic, ['promo_cta'], condenser_verdict_c_min_observations=1) is None


def test_a_chip_that_matches_nothing_falls_back_to_sharing_rather_than_vanishing(env):
    """The reader said "AI slop" and the extractor described the tweet as a listicle.
    They disagree about the description — but the downvote is still real.

    This started as the opposite rule (a chip that matches nothing charges nobody),
    and 59 production labels proved it wrong in a way worth remembering: upvotes are
    credited to every flag in full, since an upvote has no chip and never can, so
    any flag the chips fail to reach could only ever *gain* positive evidence.
    `humblebrag` came out at **+0.600 while sitting on seven downvoted tweets** —
    the channel had learned that success theatre is a good sign. Falling back to the
    bag-level share is what keeps the two sides symmetric.

    Measured mismatch rates, for scale: the `promo` chip matched an extracted flag
    11 times out of 11, `engagement_farming` 4 out of 10, and `ai_slop` 0 out of 3.
    """
    mismatch = attrs.fit_flags([labeled(['listicle'], 'down', 'ai_slop'), labeled(['promo_cta'], 'up')])

    assert score(mismatch, ['listicle'], condenser_verdict_c_min_observations=1).score < 0


# --- how a tweet's flags become one score ---------------------------------------


def test_one_clearly_bad_attribute_carries_the_tweet(env, model):
    """Multiple-instance intuition: a post with one unmistakable bait line *is* bait,
    however much innocuous material surrounds it. Averaging would dilute it away."""
    mixed = score(model, ['engagement_bait', 'listicle'], condenser_verdict_c_min_observations=1)
    clean = score(model, ['listicle'], condenser_verdict_c_min_observations=1)

    assert mixed.score < 0 < clean.score


def test_a_tweet_with_no_flags_abstains(env, model):
    """Most tweets carry no flags at all — that is the extractor working, not a
    verdict of "fine". Silence has to stay distinguishable from a considered zero."""
    assert score(model, []) is None


def test_an_attribute_nobody_has_labeled_yet_abstains(env, model):
    assert score(model, ['dropshipping'], condenser_verdict_c_min_observations=1) is None


def test_a_thinly_observed_attribute_does_not_get_to_decide(env, model):
    """The plan's warning, as a gate: a flag needs real counts on both sides before
    it means anything, and at ~60 labels most flags will not have them."""
    assert score(model, ['engagement_bait'], condenser_verdict_c_min_observations=10) is None
    assert score(model, ['engagement_bait'], condenser_verdict_c_min_observations=1) is not None


def test_a_single_downvote_is_not_corroboration(env):
    """Same asymmetry as everywhere else: a negative costs the tweet, so one sample
    cannot carry it. The score still stands — corroboration gates the verdict."""
    thin = attrs.fit_flags([labeled(['giveaway'], 'down', 'promo'), labeled(['giveaway'], 'up')])
    thin_flags = attrs.fit_flags(
        [labeled(['crypto_shill'], 'down', 'promo'), labeled(['crypto_shill'], 'down', 'promo')]
    )

    assert score(thin, ['giveaway'], condenser_verdict_c_min_observations=1).corroborated is False
    assert score(thin_flags, ['crypto_shill'], condenser_verdict_c_min_observations=1).corroborated is True


def test_a_save_outweighs_a_thumbs_up(env):
    """Consistent with the kNN's sample weights: a save costs an intent, a thumb costs
    a reflex, so it is worth two of them."""
    saved = attrs.fit_flags([labeled(['promo_cta'], 'save'), labeled(['promo_cta'], 'down', 'promo')])
    thumbed = attrs.fit_flags([labeled(['promo_cta'], 'up'), labeled(['promo_cta'], 'down', 'promo')])

    assert score(saved, ['promo_cta'], condenser_verdict_c_min_observations=1).score > 0
    assert score(thumbed, ['promo_cta'], condenser_verdict_c_min_observations=1).score == pytest.approx(0)


def test_confidence_grows_with_the_evidence_behind_the_deciding_flag(env):
    """What keeps a flag seen twice from outvoting a flag seen forty times once the
    combiner mixes channels."""
    thin = attrs.fit_flags([labeled(['promo_cta'], 'down', 'promo'), labeled(['listicle'], 'up')])
    thick = attrs.fit_flags(
        [labeled(['promo_cta'], 'down', 'promo') for _ in range(20)] + [labeled(['listicle'], 'up')]
    )
    loose = {'condenser_verdict_c_min_observations': 1}

    assert score(thick, ['promo_cta'], **loose).confidence > score(thin, ['promo_cta'], **loose).confidence


# --- the evidence trail ---------------------------------------------------------


def test_the_evidence_names_the_attribute_that_decided(env, model):
    """Channel C's version of D's contributing tokens: the pane can say "because this
    reads as engagement bait, which you have downvoted 3 times"."""
    result = score(model, ['engagement_bait', 'listicle'], condenser_verdict_c_min_observations=1)

    flags = dict((flag, weight) for flag, weight in result.meta['flags'])
    assert flags['engagement_bait'] < 0
    assert result.meta['driver'] == 'engagement_bait'


def test_an_upvote_is_shared_out_the_way_an_unattributed_down_already_is(env):
    """The asymmetry this fixes was measured on 104 production labels (2026-07-29).

    A down carries the reader's own account of *what* was wrong; an upvote carries
    none and never can — the reader liked the tweet, not necessarily each attribute
    in it. Crediting every flag on a liked tweet in full therefore let any flag the
    chips rarely accuse bank positive evidence it had not earned: `ai_slop` scored
    **+0.429 while sitting on six downvoted tweets**. Spreading an upvote is the same
    rule an unattributed down already follows (see `_charged`'s first branch), so the
    two sides now treat "I cannot attribute this" identically.
    """
    solo = attrs.fit_flags([labeled(['listicle'], 'up')])
    shared = attrs.fit_flags([labeled(['listicle', 'promo_cta', 'emoji_spam'], 'up')])

    assert shared.up['listicle'] < solo.up['listicle']
    # the label is worth what it was worth; only its attribution is now uncertain
    assert sum(shared.up.values()) == pytest.approx(sum(solo.up.values()))


def test_every_style_flag_can_be_accused_by_some_chip(env):
    """The mirror of the test below, and the hole `emoji_spam` fell through for three
    days: it appeared in no chip's list at all, so no downvote could ever charge it
    while every upvote credited it — 1 up against 6 downs scored **+0.200**. Pinning
    both directions means a new flag cannot be added without deciding who accuses it."""
    accused = {flag for flags in attrs.REASON_FLAGS.values() for flag in flags}

    assert set(attrs.STYLE_FLAGS) == accused


def test_every_chip_reason_maps_somewhere_explicit(env):
    """A chip the scorer silently ignores is a chip that costs the reader a tap and
    buys nothing — so the mapping is exhaustive over db.FEEDBACK_REASONS, with the
    two that belong to other channels named as such rather than merely absent."""
    from condenser import db

    assert set(attrs.REASON_FLAGS) == set(db.FEEDBACK_REASONS)
    assert attrs.REASON_FLAGS['topic'] == ()  # channel B's business
    assert attrs.REASON_FLAGS['author'] == ()  # channel A's business
