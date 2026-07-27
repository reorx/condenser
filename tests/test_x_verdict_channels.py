"""Behavior tests for the verdict's channels beyond the topic kNN.

Plan: kb/plans/2026-07-27-x-verdict-style-channels.md (step 1, channel D)

Why this channel exists is the whole design, so it is worth restating: on
2026-07-27 the topic kNN's negative half was switched off because a leave-one-out
backtest on 59 real labels put it at 55.6% precision against a 49.2% base rate —
it knew nothing. The cause was in the labels, not the thresholds: 24 of the 29
downs were *style* judgements (promo / engagement_farming / ai_slop), and an
embedding trained for topic similarity cannot represent style. It only sees the
subject the complaint happened to be attached to.

Channel D reads the words themselves, so the tests below are mostly about one
property the topic channel structurally cannot have: **the same bait phrasing on
a subject you have never labeled is still bait**. The rest guard the two gates
that keep a bag-of-words model honest on a few hundred documents — a token seen
once is not evidence, and having nothing to say is not the same as saying zero.
"""

import math
import statistics

import pytest

from condenser import ngram
from condenser.channels import ChannelScore, combine
from condenser.config import get_settings

# A training set in the shape of the real one: the downs share a *voice*, not a
# subject (crypto, fitness, SaaS), and the ups share a subject the way the reader's
# real upvotes do. Every bait phrase appears in at least two documents, because a
# token seen once is deliberately not evidence.
BAIT = [
    'save this thread 🧵 before it disappears — 7 crypto tools you must know',
    'save this 🔖 a thread on fitness hacks nobody tells you about',
    'i built a saas in 7 days. a thread 🧵 on how you must start today',
    '5 tools you must know to grow. save this thread and follow for more',
]
LIKED = [
    'notes on the rust borrow checker and lifetime elision',
    'postgres index-only scans explained with a query plan',
    'rust async runtimes compared on a real workload',
    'a postgres vacuum walkthrough with query plan traces',
]


@pytest.fixture
def model():
    return ngram.fit([(text, True) for text in LIKED] + [(text, False) for text in BAIT])


def score(model, text, **overrides):
    return ngram.score(model, text, get_settings().model_copy(update=overrides))


# --- what the channel is for ----------------------------------------------------


def test_bait_phrasing_you_downvoted_scores_negative(env, model):
    result = score(model, 'save this thread 🧵 — 5 crypto tools you must know')

    assert result is not None
    assert result.score < 0


def test_the_same_bait_phrasing_on_an_unlabeled_subject_still_scores_negative(env, model):
    """The reason this channel exists.

    Nothing in the training set mentions gardening. A topic kNN would call this
    out-of-domain and abstain (correctly, on its own terms — it has no gardening
    neighbour to reason from), while the complaint the reader actually filed was
    about the phrasing, which is right here in the words.
    """
    result = score(model, 'save this thread 🧵 — 7 gardening tools you must know')

    assert result is not None
    assert result.score < 0


def test_subject_matter_you_upvoted_scores_positive(env, model):
    result = score(model, 'rust lifetime elision notes, with a postgres query plan')

    assert result is not None
    assert result.score > 0


# --- the gates ------------------------------------------------------------------


def test_a_tweet_with_no_familiar_words_abstains(env, model):
    """Abstain is ``None``, never 0.0 — see channels.py. A bag-of-words model on a
    few hundred documents will not recognize most tweets, and silence has to stay
    distinguishable from a considered "neutral" or the combiner counts it as a vote.
    """
    assert score(model, 'ふつうの日本語のツイートです') is None


def test_a_word_seen_in_a_single_tweet_is_not_evidence(env):
    """One occurrence is an anecdote. With ``min_df`` at 1 the same word decides the
    verdict, which is how a bag-of-words model on a small corpus fools a backtest.
    """
    single = ngram.fit([('quokka pictures', True), ('an unrelated liked post', True), ('a downvoted post', False)])
    loose = {'condenser_verdict_d_min_hits': 1, 'condenser_verdict_d_min_weight': 0.0}

    assert score(single, 'quokka', **loose) is None
    assert score(single, 'quokka', **loose, condenser_verdict_d_min_df=1) is not None


def test_a_near_neutral_word_is_not_evidence_either(env, model):
    """The floor under |weight|, and the second half of the same 2026-07-27 finding:
    words both sides use are not free to accumulate. Enough of them and a tweet gets
    a confident verdict assembled entirely out of noise.
    """
    weak = ngram.fit(
        [('shared words here', True), ('shared words there', True)]
        + [
            ('shared words everywhere', False),
            ('shared words again', False),
        ]
    )

    assert score(weak, 'shared words', condenser_verdict_d_min_hits=1) is None
    assert score(weak, 'shared words', condenser_verdict_d_min_hits=1, condenser_verdict_d_min_weight=0.0) is not None


def test_the_score_says_how_one_sided_a_tweet_is_not_how_long_it_is(env, model):
    """The calibration defect the first real backtest found, and the reason the
    channel scores the *mean* of its strong evidence rather than the sum.

    Summing token weights grows with the number of words, and downvoted tweets are
    simply longer (measured on real labels: 30.8 informative tokens against 15.3 —
    threads, listicles and promos take more room). So every long tweet saturated at
    -1 whatever it said: not one upvoted tweet scored positive, and the channel
    called 78% of everything negative at the base rate. Ranking, not thresholds, is
    what a bag of words is good for — so a half-and-half tweet has to land in
    between, not at the floor with the pure bait.
    """
    bait = score(model, 'save this thread 🧵 5 tools you must know')
    liked = score(model, 'notes on the rust borrow checker with a query plan')
    mixed = score(model, 'save this thread 🧵 5 rust tools you must know: borrow checker query plan notes')

    assert bait.score < mixed.score < liked.score


def test_the_estimator_is_the_backtested_one(env, model):
    """The arithmetic, pinned — because it is a measured decision, not a taste.

    Leave-one-out over 59 production labels, comparing estimators by AUC (the
    chance a random upvoted tweet outranks a random downvoted one, where 0.50 is a
    coin and no threshold can save you):

        df / mean / |w|>=0.5 / hits>=3    AUC 0.804   abstain 15.3%   p@15 86.7%
        df / sum  / |w|>=0.0 / hits>=3    AUC 0.792   abstain 10.2%   p@15 80.0%
        mnb / mean over class token mass  AUC 0.845   abstain 64.4%   p@15 73.3%

    So: keep document frequencies (the multinomial normalization buys AUC only by
    abstaining on two thirds of the corpus), filter to strong evidence, average it.
    Re-run tmp/x_ngram_variants.py against a fresh snapshot before changing any of
    this — and note the numbers above are optimistic, since the variant was chosen
    on the same 59 labels it was scored on.
    """
    settings = get_settings()
    text = 'save this thread 🧵 you must know these tools, follow for more'
    strong = [
        weight
        for _, weight in ngram.contributions(model, text, settings)
        if abs(weight) >= settings.condenser_verdict_d_min_weight
    ][: settings.condenser_verdict_d_top_tokens]

    centered = statistics.fmean(strong) - model.offset
    assert score(model, text).score == pytest.approx(math.tanh(centered / settings.condenser_verdict_d_scale))


def test_the_neutral_point_comes_from_the_corpus_not_from_zero(env, model):
    """Zero has to mean "no opinion" — here as in every channel, because the
    combiner averages them on one scale. It does not come out that way for free.

    Downvoted tweets carry about twice the words of upvoted ones (threads,
    listicles and promos take room), so most of the vocabulary appears in more
    downs than ups and the whole scale leans negative. Measured on the 59-label
    production snapshot, leave-one-out, as the calibration was fixed:

        uncentered                     up median -0.43 / down -0.68, best up -0.05
        centered in-sample             up median -0.15 / down -0.48
        centered leave-one-out         up median +0.07 / down -0.31   <- shipped

    In-sample was not enough because the self-vote is worth more to one side: a
    downvoted tweet's words survive in its 28 neighbours, an upvoted tweet's
    usually do not. The offset is a pure shift applied to the finished score —
    never to the token weights, which would reorder the evidence and, measured,
    dropped the channel below its own base rate.
    """
    # the real shape in miniature: the downs are longer *and* they talk about the
    # same things the ups do, so the shared vocabulary tilts their way
    ups = ['rust notes', 'postgres notes', 'redis notes', 'rust postgres notes']
    downs = [
        f'save this thread you must know these {topic} tools — rust postgres redis notes and more'
        for topic in ('crypto', 'fitness', 'saas', 'ai')
    ]
    lopsided = ngram.fit([(text, True) for text in ups] + [(text, False) for text in downs])

    # An uncalibrated model has no offset at all, so this is the whole guarantee:
    # the correction exists, is read off the corpus, and points the way the corpus
    # leans. How *much* it is worth is a question only real labels answer — see the
    # measurements above, and re-take them with tmp/x_ngram_diagnose.py.
    assert lopsided.offset < 0


def test_too_few_recognizable_words_abstains(env, model):
    """One familiar token is not a judgement — ``min_hits`` is the OOD gate's peer."""
    assert score(model, 'rust', condenser_verdict_d_min_hits=3) is None
    assert score(model, 'rust', condenser_verdict_d_min_hits=1) is not None


def test_one_negative_token_is_not_corroboration(env, model):
    """The same asymmetry the kNN has: a negative verdict costs the tweet, so it
    takes more than one accidental token. The score still stands — corroboration
    gates the *verdict*, not the evidence."""
    lone = ngram.fit(
        [('rust borrow checker notes', True), ('postgres query plan notes', True)]
        + [('giveaway rust notes', False), ('giveaway postgres notes', False)]
    )
    result = score(lone, 'giveaway rust borrow checker notes', condenser_verdict_d_min_hits=1)

    assert result is not None
    assert result.score < 0
    assert result.corroborated is False


def test_the_score_stays_inside_the_unit_range(env, model):
    """Log-odds are unbounded; the contract is [-1, +1], because the combiner mixes
    channels whose scales have nothing to do with each other."""
    piled = 'save this thread 🧵 save this 🔖 you must know a thread must know tools'

    result = score(model, piled, condenser_verdict_d_scale=0.1)

    assert -1.0 <= result.score <= 1.0
    assert result.score < -0.9  # squashed, not clipped: the evidence is still loud


# --- explainability -------------------------------------------------------------


def test_the_evidence_names_the_words_that_moved_the_score(env, model):
    """Channel D's advantage over every other channel: it can say *why* in words the
    reader recognizes. This is what the detail pane renders."""
    result = score(model, 'save this thread 🧵 — 7 gardening tools you must know')

    tokens = [token for token, _ in result.meta['tokens']]
    assert 'save this' in tokens
    weights = [weight for _, weight in result.meta['tokens']]
    assert weights == sorted(weights, key=abs, reverse=True)  # most influential first


# --- tokenization ---------------------------------------------------------------


def test_urls_and_mentions_are_dropped_but_hashtag_words_are_kept(env):
    tokens = ngram.tokenize('Great read https://t.co/abc via @someone #giveaway')

    assert not [token for token in tokens if 't.co' in token or '@' in token]
    assert 'giveaway' in tokens


def test_bigrams_span_a_stopword_that_is_dropped_on_its_own(env):
    """'this' alone is noise; 'save this' is the signature. So stopwords are filtered
    out of the unigrams *after* the bigrams are built, not before."""
    tokens = ngram.tokenize('save this now')

    assert 'this' not in tokens
    assert 'save this' in tokens


def test_chinese_is_tokenized_as_character_bigrams(env):
    """No jieba: the dependency cost is real and the alternative is two lines. Character
    bigrams are the standard cheap stand-in for Chinese word segmentation."""
    tokens = ngram.tokenize('必看干货')

    assert '必看' in tokens and '看干' in tokens


def test_emoji_are_tokens(env):
    """'🧵' and '🔖' are the load-bearing words of engagement bait."""
    assert '🧵' in ngram.tokenize('a thread 🧵')


# --- the combiner ---------------------------------------------------------------


def test_an_abstaining_channel_does_not_dilute_the_one_that_spoke(env):
    mixed = combine({'b': None, 'd': ChannelScore(-0.8)}, {'b': 1.0, 'd': 1.0})

    assert mixed.score == pytest.approx(-0.8)


def test_channels_are_weighted_by_configuration_and_confidence(env):
    mixed = combine(
        {'b': ChannelScore(1.0, confidence=1.0), 'd': ChannelScore(-1.0, confidence=1.0)},
        {'b': 1.0, 'd': 0.5},
    )

    assert mixed.score == pytest.approx((1.0 - 0.5) / 1.5)


def test_a_thin_channel_carries_its_thinness_into_the_mix(env):
    mixed = combine({'d': ChannelScore(-1.0, confidence=0.25)}, {'d': 1.0})

    assert mixed.confidence == pytest.approx(0.25)


def test_silence_from_everyone_is_not_a_verdict(env):
    assert combine({'b': None, 'd': None}, {'b': 1.0, 'd': 1.0}) is None


def test_a_channel_with_no_weight_does_not_vote(env):
    assert combine({'d': ChannelScore(-1.0)}, {'b': 1.0}) is None


def test_corroboration_must_be_unanimous_among_the_channels_that_spoke(env):
    mixed = combine({'b': ChannelScore(-0.8), 'd': ChannelScore(-0.8, corroborated=False)}, {'b': 1.0, 'd': 1.0})

    assert mixed.corroborated is False
