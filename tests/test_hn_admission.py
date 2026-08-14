"""HN admission floors — plan 2026-08-14, phases 1 (A) and 2 (B).

Both are one AND on the read path, on top of the existing per-day top-N rank:

* **A** an absolute ``score`` floor (default 50),
* **B** a ``peak_rank`` gate (default 20, ``NULL`` always passes).

They exist for exactly one window. ``day_rank <= 10`` degenerates to "everything"
while a day's partition still holds nine rows, and UTC midnight is 08:00 Beijing —
so the bar drops to zero at the moment the reader opens the app. On a mature day
the real cut sits at 243-476 points (30 days of production data), which is why
neither floor is ever binding there: the first test below is the one that says so.

The two are not redundant. peak_rank is time-normalised — HN's own ranking already
divides age out — so it catches the second-chance-pool repost that sits at #21-30
for days while carrying a respectable score, which no absolute floor reaches.
"""

import json

from condenser import db, search
from condenser.hn import DEFAULT_FEED_CONFIG
from tests.conftest import BASE
from tests.test_multi_source import _client, _login, seed_hn, subscribe_hn


def _ids(client, **params):
    """Visible HN story ids on the aggregate timeline, newest first."""
    r = client.get('/api/timeline', params={'limit': 100, **params})
    assert r.status_code == 200, r.text
    return [it['hn']['id'] for it in r.json()['items'] if it['source'] == 'hn']


def _config(**over):
    db.update_hn_subscription('front', config={'display_mode': 'top10', **over})


# --- A: the absolute score floor --------------------------------------------


def test_mature_day_visible_set_is_unchanged(env):
    """The floors must be inert where the rule already works.

    A formed day cuts at hundreds of points, so nothing the floors could reject
    was reachable anyway. This is the acceptance condition for shipping them at
    all: turning them on changes no mature day.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        # 30 stories on one day at mature scores. Rank tracks score, as it does in
        # production: a story in a day's top 10 averages peak_rank 2.7 there.
        for i in range(30):
            seed_hn(100 + i, i, score=100 + i * 10, peak_rank=30 - i)

        _config(min_score=0, max_peak_rank=0)
        without_floors = _ids(client)
        _config(min_score=50, max_peak_rank=20)
        assert _ids(client) == without_floors
        assert len(without_floors) == 10


def test_unformed_day_stops_admitting_anything_with_a_pulse(env):
    """The reported bug: 6- and 7-point stories on the timeline.

    Nine stories exist so far today, so `day_rank <= 10` admits all nine. The
    floor keeps the one story that actually earned a place.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        for i, score in enumerate([79, 40, 22, 15, 12, 9, 7, 6, 5]):
            seed_hn(200 + i, i, score=score, peak_rank=1 + i)

        _config(min_score=0, max_peak_rank=0)
        assert len(_ids(client)) == 9
        _config()  # defaults: min_score 50
        assert _ids(client) == [200]


def test_min_score_zero_turns_the_floor_off(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(300, 0, score=6, peak_rank=3)

        _config(min_score=50)
        assert _ids(client) == []
        _config(min_score=0)
        assert _ids(client) == [300]


# --- B: the peak-rank gate ---------------------------------------------------


def test_second_chance_repost_is_gated_when_the_reader_turns_it_on(env):
    """A story that never climbed above #21 is what the score floor cannot see.

    Both stories here clear the score floor; only their best front-page position
    differs, which is the signal HN's own age-normalised ranking gives for free —
    when it is switched on, which by default it is not (see the test below).
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(400, 0, score=60, peak_rank=21)  # second-chance pool: front-page tail
        seed_hn(401, 1, score=60, peak_rank=20)

        _config(max_peak_rank=20)
        assert _ids(client) == [401]


def test_the_peak_rank_gate_is_off_by_default(env):
    """Do not flip this back on without re-running the snapshot diff.

    On 32 days of production data the gate at 20 had **zero** true positives and
    three false ones — 1235-, 708- and 703-point stories sitting at #2, #8 and #2
    of their day. peak_rank is the best rank we *sampled*, not the best rank the
    story reached, and a story whose peak lands in a sampling gap is recorded on
    its way down. Evidence: tmp/2026-08-14-hn-admission/.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(410, 0, score=1235, peak_rank=21)  # first sampled on its way down

        _config()
        assert _ids(client) == [410]


def test_backfilled_stories_have_no_peak_rank_and_stay_visible(env):
    """``peak_rank IS NULL`` must pass — do not "tidy" this away.

    The hckrnews backfill stores rank=None, and production holds 593 such rows.
    A gate that rejected NULL would delete the whole imported history from the
    timeline in one deploy.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(500, 0, score=200, peak_rank=None, backfilled=True)

        _config(max_peak_rank=20)
        assert _ids(client) == [500]


def test_max_peak_rank_zero_turns_the_gate_off(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(600, 0, score=200, peak_rank=27)

        _config(max_peak_rank=20)
        assert _ids(client) == []
        _config(max_peak_rank=0)
        assert _ids(client) == [600]


def test_peak_rank_is_only_an_and_never_a_fast_lane(env):
    """A great peak rank does not buy a pass on the score floor.

    Measured: 689 of the 2679 stories that never made a day's top 10 had reached
    the front page's top 5 at some point. As an OR this would admit ~23 pieces of
    junk a day.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(700, 0, score=7, peak_rank=1)

        _config()
        assert _ids(client) == []


# --- every surface that counts ----------------------------------------------


def test_floors_shape_days_and_unread_counts_too(env):
    """The page, the calendar and the badge are three queries over one rule.

    A floor applied to the page alone would leave the badge advertising a backlog
    no view can produce — the same defect `aggregate_unread` was added for.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(800, 0, score=200, peak_rank=2)
        for i in range(4):
            seed_hn(810 + i, 1 + i, score=6, peak_rank=25)

        _config(min_score=0, max_peak_rank=0)
        assert [d['count'] for d in client.get('/api/timeline/days').json()] == [5]
        assert _hn_unread(client) == 5

        _config()
        assert [d['count'] for d in client.get('/api/timeline/days').json()] == [1]
        assert _hn_unread(client) == 1


def _hn_unread(client) -> int:
    groups = client.get('/api/sources').json()
    hn = next(g for g in groups if g['source'] == 'hn')
    return hn['subscriptions'][0]['unread']


def test_floors_shape_the_new_content_poll(env):
    """`/timeline/new` must not raise a banner for a story no page would render."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(900, 0, score=200, peak_rank=2)
        head = client.get('/api/timeline').json()['head_cursor']

        seed_hn(901, 10, score=6, peak_rank=25)
        _config()
        assert client.get('/api/timeline/new', params={'after': head}).json()['count'] == 0

        _config(min_score=0, max_peak_rank=0)
        assert client.get('/api/timeline/new', params={'after': head}).json()['count'] == 1


def test_search_still_finds_a_floored_out_story(env):
    """Search reads the archive, not the reading list — every phase re-checks this."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(1000, 0, title='rust compiler internals', score=6, peak_rank=25)
        search.index_hn_story(
            {'id': 1000, 'title': 'rust compiler internals', 'text': None, 'first_seen_at': BASE.replace(tzinfo=None)}
        )

        _config()
        assert _ids(client) == []
        r = client.get('/api/search', params={'q': 'rust'})
        assert [it['key'] for it in r.json()['items']] == ['hn:1000']


# --- configuration ----------------------------------------------------------


def test_a_config_without_the_new_keys_gets_the_defaults(env):
    """Production's row predates both keys; the score floor must still be armed."""
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'top10'})
        seed_hn(1100, 0, score=6, peak_rank=3)
        seed_hn(1101, 1, score=200, peak_rank=3)

        assert _ids(client) == [1101]


def test_unparseable_floor_values_fall_back_to_the_defaults(env):
    """The config is a free-form JSON dict a PATCH can write anything into.

    Coercing at the read boundary keeps junk out of the SQL, and falling back to
    the default rather than to 0 means a typo cannot silently disarm the floor.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(1200, 0, score=6, peak_rank=3)

        _config(min_score='fifty', max_peak_rank=[20])
        assert _ids(client) == []


def test_new_subscriptions_carry_both_floors(env):
    assert DEFAULT_FEED_CONFIG['min_score'] == 50
    assert DEFAULT_FEED_CONFIG['max_peak_rank'] == 0  # shipped off — see the test above
    with _client() as client:
        _login(client)
        assert client.post('/api/sources/hn/subscriptions', json={'channel_id': 'front'}).status_code == 200
        assert json.loads(db.get_hn_subscription('front').config) == DEFAULT_FEED_CONFIG


def test_config_patch_merges_instead_of_replacing(env):
    """Three keys share one config column, so a whole-value write loses two of them.

    Until now the config held `display_mode` alone and replace-on-PATCH was
    invisible; with the floors in it, changing the display mode would disarm both.
    """
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'top10', 'min_score': 100, 'max_peak_rank': 10})

        r = client.patch('/api/sources/hn/subscriptions/front', json={'config': {'display_mode': 'top20'}})
        assert r.status_code == 200
        assert json.loads(db.get_hn_subscription('front').config) == {
            'display_mode': 'top20',
            'min_score': 100,
            'max_peak_rank': 10,
        }

        client.patch('/api/sources/hn/subscriptions/front', json={'config': {'min_score': 30}})
        assert json.loads(db.get_hn_subscription('front').config) == {
            'display_mode': 'top20',
            'min_score': 30,
            'max_peak_rank': 10,
        }


def test_patching_a_floor_takes_effect_without_a_restart(env):
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'top10', 'min_score': 0, 'max_peak_rank': 0})
        seed_hn(1300, 0, score=30, peak_rank=3)
        assert _ids(client) == [1300]

        client.patch('/api/sources/hn/subscriptions/front', json={'config': {'min_score': 50}})
        assert _ids(client) == []
