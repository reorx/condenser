"""Behavior tests for channel A — the author prior.

Plan: kb/plans/2026-07-27-x-verdict-style-channels.md (the channel the v2 plan
listed first and then deferred: at 29 labels only *one* down carried the `author`
chip, so there was nothing to learn from).

What brought it back is a measurement, not the plan. On 2026-07-29 the reader
asked whether the shipped machinery could reliably catch the Interactive Brokers
ads in For You. The archive held **14 @IBKR tweets, all of them ads, 6 of them
downvoted** — the single most-downvoted account — and production had judged every
one of them `neutral`. Rescoring them offline showed why no *text* channel is the
answer here:

* channel B abstained on 6 of 14 (out_of_domain — a broker ad is nowhere near
  anything the reader has labeled), and at judging time never once reached its
  own threshold;
* channel C abstained wherever the extractor had not yet read the tweet;
* channel D abstained on 4 of 14 (no token cleared `min_weight`).

The author, meanwhile, was present every single time. That is this channel's
whole claim: **it does not read the tweet**. It cannot tell you a good post from
a bad one by the same author, and in exchange it never abstains on an account you
have already judged — including on a subject, a phrasing and a set of attributes
it has never seen before.

The measured rule this replaces (`>= 2 downs and no positives -> negative`) hit
92.9% precision over 14 calls leave-one-out with **no saved tweet condemned**.
Beta smoothing is the same rule with the cliff taken out: one upvote should pull
an account back toward neutral in proportion to the evidence against it, not
acquit a 6-times-downvoted ad account outright.
"""

import pytest

from condenser import authors
from condenser.config import get_settings


def labeled(handle, verdict):
    return authors.LabeledAuthor(handle=handle, verdict=verdict)


def score(model, handle, **overrides):
    return authors.score(model, handle, get_settings().model_copy(update=overrides))


@pytest.fixture
def model():
    """The real shape: one ad account downed repeatedly, one account the reader
    likes, and one that got two downs before posting something worth reading."""
    return authors.fit(
        [
            *[labeled('IBKR', 'down')] * 6,
            *[labeled('goodposter', 'up')] * 3,
            labeled('mixed', 'down'),
            labeled('mixed', 'down'),
            labeled('mixed', 'up'),
        ]
    )


# --- what this channel is for ---------------------------------------------------


def test_a_repeatedly_downvoted_author_scores_negative(env, model):
    """The IBKR case, and the whole point of the channel."""
    result = score(model, 'IBKR')

    assert result is not None
    assert result.score < 0
    assert result.corroborated  # six downs is not a mis-tap


def test_the_channel_never_reads_the_tweet(env, model):
    """Its strength and its limit in one assertion: the score is a property of the
    account, so a brand-new subject in brand-new words gets judged just the same —
    which is exactly where B, C and D were abstaining on the IBKR ads."""
    assert authors.score(model, 'IBKR', get_settings()) == authors.score(model, 'IBKR', get_settings())
    # nothing in the signature to pass a tweet through, by design
    assert 'text' not in authors.score.__code__.co_varnames


def test_more_downs_means_a_stronger_claim(env):
    """Evidence accumulates: an account downed six times is further from neutral
    than one downed twice, so the threshold can separate 'an ad account' from
    'someone who posted two duds'."""
    twice = authors.fit([labeled('a', 'down')] * 2)
    six_times = authors.fit([labeled('a', 'down')] * 6)

    assert score(six_times, 'a').score < score(twice, 'a').score
    assert score(six_times, 'a').confidence > score(twice, 'a').confidence


def test_an_author_you_only_like_scores_positive(env, model):
    result = score(model, 'goodposter')

    assert result.score > 0


def test_a_save_outweighs_a_thumbs_up(env):
    """Same weights as every other channel: a save costs an intent, a thumb a reflex."""
    thumbed = authors.fit([labeled('a', 'up'), labeled('a', 'down')])
    saved = authors.fit([labeled('a', 'save'), labeled('a', 'down')])

    assert score(saved, 'a').score > score(thumbed, 'a').score


# --- the gates ------------------------------------------------------------------


def test_an_author_you_have_never_labeled_abstains(env, model):
    """The channel's blind spot, stated as a test: a *new* ad account is invisible
    to it until you have judged it, which is why it complements the text channels
    rather than replacing them. Abstaining is None, never 0.0 — a zero vote would
    drag the channels that do have something to say toward neutral."""
    assert score(model, 'someone_new') is None


def test_a_single_downvote_does_not_corroborate(env):
    """A negative verdict costs the tweet, so — as in every other channel — it
    takes a second, independent down. The score is still produced and archived."""
    result = score(authors.fit([labeled('a', 'down')]), 'a', condenser_verdict_a_min_observations=1)

    assert result.score < 0
    assert not result.corroborated


def test_thin_evidence_abstains_under_the_observation_floor(env):
    """One label about an author is an anecdote about a tweet."""
    thin = authors.fit([labeled('a', 'down')])

    assert score(thin, 'a', condenser_verdict_a_min_observations=2) is None
    assert score(thin, 'a', condenser_verdict_a_min_observations=1) is not None


def test_an_unknown_handle_abstains(env, model):
    """Nothing to key on — a tweet whose author bird did not give us."""
    assert score(model, None) is None
    assert score(model, '') is None


# --- amnesty --------------------------------------------------------------------


def test_one_positive_pulls_an_author_back_toward_neutral(env, model):
    """The failure mode the smoothing exists to prevent. The hard rule this channel
    replaces acquitted an account outright on its first upvote, which made it
    fragile in both directions; here the upvote *moves* the account instead — far
    enough that someone who posts one good thing in three is not condemned
    alongside an account that has never posted anything else."""
    occasional = score(model, 'mixed')
    ad_account = score(model, 'IBKR')

    assert ad_account.score < occasional.score
    assert occasional.score > -0.25  # above the threshold the backtest settled on


def test_the_score_stays_inside_the_channel_scale(env):
    """Every channel speaks in [-1, +1]; the combiner's vote depends on it."""
    for samples in ([labeled('a', 'down')] * 50, [labeled('a', 'save')] * 50):
        result = score(authors.fit(samples), 'a')
        assert -1.0 <= result.score <= 1.0


# --- handles --------------------------------------------------------------------


def test_handles_match_regardless_of_case_or_at_sign(env):
    """X shows handles however the account typed them and bird passes that through;
    `@IBKR`, `IBKR` and `ibkr` are one account and must share one prior."""
    model = authors.fit([labeled('@IBKR', 'down'), labeled('ibkr', 'down')])

    assert score(model, 'IBKR').score < 0
    assert score(model, '@ibkr').score == score(model, 'IBKR').score


def test_the_evidence_names_the_account_and_its_record(env, model):
    """The verdict trail has to say *why* — "you have downed @IBKR six times" is
    the most readable evidence any channel produces."""
    meta = score(model, 'IBKR').meta

    assert meta['handle'] == 'ibkr'
    assert meta['down'] == 6
    assert meta['up'] == 0
