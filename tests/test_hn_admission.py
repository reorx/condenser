"""HN admission — plan 2026-08-14, phases 1 (A), 2 (B) and 3 (D, schema v14).

Phases 1+2 added two floors to a query-time rank; phase 3 moved the whole decision
off the read path. A story is on the timeline iff it carries ``qualified_at``, a
stamp the sampling round writes once and never takes back. The floors did not go
away — they became the judge's candidate conditions, which is why their cases are
still here, only driven through ``sources.hn.qualify`` instead of through the
query.

Why the move, in one sentence per defect it closes:

* the day quota was a *relative* bar that does not exist yet at the start of a UTC
  day — nine rows in the partition made "top 10" mean "everything", and UTC
  midnight is 08:00 Beijing, so the bar hit zero exactly when the reader opened
  the app (that is how 6-point stories got in);
* a story sorted by ``first_seen_at`` but became visible an hour or more later,
  when its score crossed the day's Nth — landing *behind* the reader's cursor,
  where paging cannot reach it and ``/timeline/new`` (which asks for items newer
  than an anchor) could never report it;
* and the reverse: a story that fell below the cut as the day filled up vanished
  from a timeline the reader had already read.
"""

import json
from datetime import datetime, timedelta

from telememo import db as tdb

from condenser import db, search
from condenser.hn import DEFAULT_FEED_CONFIG
from condenser.sources import hn as hn_source
from tests.conftest import BASE
from tests.test_multi_source import _client, _login, seed_hn, subscribe_hn

# Noon on the seed day: half the budget has accrued, which keeps the arithmetic
# out of cases that are not about the budget.
NOON = BASE.replace(tzinfo=None)
WINDOW = 48  # condenser_hn_refresh_hours


def _judge(at=NOON, window=WINDOW):
    """Run one round's admission decision and return how many were stamped."""
    return hn_source.qualify(at, window)


def _ids(client, **params):
    """Visible HN story ids on the aggregate timeline, newest first."""
    r = client.get('/api/timeline', params={'limit': 100, **params})
    assert r.status_code == 200, r.text
    return [it['hn']['id'] for it in r.json()['items'] if it['source'] == 'hn']


def _config(**over):
    db.update_hn_subscription('front', config={'display_mode': 'top10', **over})


def _pending(sid, minutes, **over):
    """A story the judge has not looked at yet."""
    seed_hn(sid, minutes, qualified_at=None, qualified_rank=None, **over)


def _unjudge():
    """Rewind every admission, so one case can run the judge twice under two
    settings and compare. Nothing in the app may do this — admission is one-way."""
    db.HNStory.update(qualified_at=None, qualified_rank=None).execute()


# --- A: the absolute score floor --------------------------------------------


def test_a_formed_day_is_untouched_by_the_floor(env):
    """The floor must be inert where the quota already works.

    A formed day cuts at hundreds of points, so nothing the floor could reject was
    ever going to win a slot. This is the acceptance condition for having it at
    all: it changes no formed day.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        for i in range(30):
            _pending(100 + i, i, score=100 + i * 10, peak_rank=30 - i)

        _config(min_score=0)
        assert _judge() == 5  # ceil(10 * 12h / 24h)
        without_floor = _ids(client)

        _unjudge()
        _config(min_score=50)
        assert _judge() == 5
        assert _ids(client) == without_floor


def test_an_unformed_day_stops_admitting_anything_with_a_pulse(env):
    """The reported bug: 6- and 7-point stories on the timeline.

    Nine stories exist so far today and the old rule ranked them 1..9, all inside
    "top 10". The floor keeps the one that actually earned a place.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        for i, score in enumerate([79, 40, 22, 15, 12, 9, 7, 6, 5]):
            _pending(200 + i, i, score=score, peak_rank=1 + i)

        _config(min_score=0)
        _judge()
        assert len(_ids(client)) == 5

        _unjudge()
        _config()  # defaults: min_score 50
        _judge()
        assert _ids(client) == [200]


def test_min_score_zero_turns_the_floor_off(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        _pending(300, 0, score=6, peak_rank=3)

        _config(min_score=50)
        assert _judge() == 0
        assert _ids(client) == []

        _config(min_score=0)
        assert _judge() == 1
        assert _ids(client) == [300]


# --- B: the peak-rank gate ---------------------------------------------------


def test_second_chance_repost_is_gated_when_the_reader_turns_it_on(env):
    """A story that never climbed above #21 is what the score floor cannot see.

    Both clear the score floor; only their best front-page position differs, which
    is the signal HN's own age-normalised ranking gives for free — when it is
    switched on, which by default it is not (see the test below).
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        _pending(400, 0, score=60, peak_rank=21)  # second-chance pool: front-page tail
        _pending(401, 1, score=60, peak_rank=20)

        _config(max_peak_rank=20)
        _judge()
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
        _pending(410, 0, score=1235, peak_rank=21)  # first sampled on its way down

        _config()
        _judge()
        assert _ids(client) == [410]


def test_backfilled_stories_have_no_peak_rank_and_stay_admissible(env):
    """``peak_rank IS NULL`` must pass — do not "tidy" this away.

    The hckrnews backfill stores rank=None, and production holds 593 such rows. A
    gate that rejected NULL would delete the whole imported history in one deploy.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        _pending(500, 0, score=200, peak_rank=None, backfilled=True)

        _config(max_peak_rank=20)
        _judge()
        assert _ids(client) == [500]


def test_max_peak_rank_zero_turns_the_gate_off(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        _pending(600, 0, score=200, peak_rank=27)

        _config(max_peak_rank=20)
        assert _judge() == 0

        _config(max_peak_rank=0)
        assert _judge() == 1
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
        _pending(700, 0, score=7, peak_rank=1)

        _config()
        assert _judge() == 0
        assert _ids(client) == []


# --- D: admission is one-way -------------------------------------------------


def test_an_admitted_story_never_disappears(env):
    """The defect the stamp exists to close, from the reader's side.

    Under the query-time rank, a story's visibility was recomputed on every
    request against a day that kept filling up: the reader would read something
    and watch the timeline shrink behind them. Nothing that has been shown may be
    withdrawn — not by a score collapse, not by better stories arriving, not by
    tightening the rules.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        _pending(800, 0, score=60)
        _config()
        _judge()
        assert _ids(client) == [800]

        db.update_hn_snapshot(800, score=3, comments_count=0, updated_at=NOON)
        for i in range(20):
            _pending(810 + i, 1 + i, score=500)
        _config(min_score=150, max_peak_rank=10)
        _judge(at=NOON + timedelta(hours=11))

        assert 800 in _ids(client)
        assert client.get('/api/timeline/days').json()[0]['count'] >= 1


def test_a_story_is_judged_once_and_keeps_its_slot_number(env):
    """The badge is stored, not recomputed — today it jumps between two refreshes."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        _pending(900, 0, score=300)
        _config()
        _judge()

        rank = [it['hn']['day_rank'] for it in client.get('/api/timeline').json()['items']][0]
        assert rank == 1

        _pending(901, 1, score=999)  # outranks it on score
        _judge(at=NOON + timedelta(hours=3))
        by_id = {it['hn']['id']: it['hn']['day_rank'] for it in client.get('/api/timeline').json()['items']}
        assert by_id == {900: 1, 901: 2}


# --- D: the budget line ------------------------------------------------------


def test_the_day_quota_is_a_rate_not_a_midnight_grant(env):
    """The heart of phase 3: `ceil(N * elapsed / 24)`, spent cumulatively.

    A whole day's worth available at 00:00 UTC is the same hole the score floor
    was patching — with the population thin and the quota full, everything gets
    in. Spreading it means the early morning gives you the best 1-2 stories so far
    instead of whatever exists.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        for i in range(30):
            _pending(1000 + i, i, score=100 + i)
        _config()

        midnight = NOON.replace(hour=0, minute=0)
        assert _judge(at=midnight + timedelta(hours=1)) == 1  # ceil(10 * 1/24)
        assert _judge(at=midnight + timedelta(hours=3)) == 1  # budget 2, spent 1
        assert _judge(at=midnight + timedelta(hours=12)) == 3  # budget 5, spent 2
        assert _judge(at=midnight + timedelta(hours=23, minutes=59)) == 5  # budget 10
        assert _judge(at=midnight + timedelta(hours=23, minutes=59)) == 0  # spent out


def test_the_budget_resets_the_next_day(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        for i in range(30):
            _pending(1100 + i, i, score=100 + i)
        _config()

        end_of_day = NOON.replace(hour=23, minute=30)
        assert _judge(at=end_of_day) == 10
        assert _judge(at=end_of_day + timedelta(hours=1)) == 1  # next UTC day, 00:30


def test_the_budget_belongs_to_the_admission_day_not_the_archive_day(env):
    """A 23:50 story admitted at 02:00 spends the second day's budget, and is
    shown under the second day — which is where it sorts (plan §5.4a)."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        late = NOON.replace(hour=23, minute=50)
        _pending(1200, 0, first_seen_at=late, day=str(late.date()), score=300)
        _config()

        next_day = late + timedelta(hours=2, minutes=10)
        assert _judge(at=next_day) == 1
        assert db.hn_qualified_count(str(late.date())) == 0
        assert db.hn_qualified_count(str(next_day.date())) == 1

        days = {d['date']: d['count'] for d in client.get('/api/timeline/days').json()}
        assert days == {str(next_day.date()): 1}
        assert _ids(client, date=str(next_day.date())) == [1200]


def test_all_mode_has_no_ceiling(env):
    with _client() as client:
        _login(client)
        subscribe_hn()
        for i in range(12):
            _pending(1300 + i, i, score=100)
        db.update_hn_subscription('front', config={'display_mode': 'all', 'min_score': 50})

        assert _judge(at=NOON.replace(hour=0, minute=30)) == 12


def test_half_mode_takes_its_rate_from_the_archive_volume(env):
    """'half of the day' has no fixed N to spread, so the rate comes from how much
    the archive actually collects — the median of the last complete days."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        # three prior days of 20 archived stories each -> quota ceil(20/2) = 10
        for d in range(1, 4):
            for i in range(20):
                past = NOON - timedelta(days=d)
                _pending(2000 + d * 100 + i, 0, first_seen_at=past, day=str(past.date()), score=10)
        for i in range(30):
            _pending(1400 + i, i, score=100 + i)
        db.update_hn_subscription('front', config={'display_mode': 'half', 'min_score': 50})

        assert hn_source.day_quota(hn_source.stored_config(), str(NOON.date())) == 10
        assert _judge() == 5  # ceil(10 * 12/24)


# --- D: the candidate window -------------------------------------------------


def test_a_story_past_the_refresh_window_is_never_admitted(env):
    """Two windows, one constant, on purpose (plan §5.4b).

    Past the refresh window we stop pulling scores, so a story can no longer
    *earn* its way in — only a freed slot could let it in, and stamping a
    three-day-old story with today's timestamp would drop it at the top of the
    timeline as if it had just arrived.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        old = NOON - timedelta(hours=WINDOW + 1)
        _pending(1500, 0, first_seen_at=old, day=str(old.date()), score=999)
        _pending(1501, 0, score=60)
        _config()

        assert _judge() == 1
        assert _ids(client) == [1501]


# --- D: the surfaces ---------------------------------------------------------


def test_the_poll_reports_a_story_admitted_after_the_page_loaded(env):
    """The core payoff, written as the before/after it is (plan §6).

    A story archived *before* the page loaded but admitted after it: under the
    query-time rule it became visible at a `first_seen_at` already older than the
    poll anchor, so `/timeline/new` could not report it and the reader got no
    signal at all. Stamped at admission time, it is newer than the anchor by
    construction.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(1600, 0, score=300)  # already visible; gives the page a head cursor
        _pending(1601, 5, score=60)  # archived, not yet admitted

        head = client.get('/api/timeline').json()['head_cursor']
        assert client.get('/api/timeline/new', params={'after': head}).json()['count'] == 0

        _config()
        assert _judge(at=NOON + timedelta(hours=1)) == 1

        new = client.get('/api/timeline/new', params={'after': head}).json()
        assert new['count'] == 1
        assert [it['hn']['id'] for it in new['items']] == [1601]


def test_every_surface_reads_the_same_stamp(env):
    """The page, the calendar and the badge are three queries over one column."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(1700, 0, score=200)
        for i in range(4):
            _pending(1710 + i, 1 + i, score=6)

        assert [d['count'] for d in client.get('/api/timeline/days').json()] == [1]
        assert _hn_unread(client) == 1
        assert _ids(client) == [1700]

        _config(min_score=0)
        _judge()
        assert [d['count'] for d in client.get('/api/timeline/days').json()] == [5]
        assert _hn_unread(client) == 5


def _hn_unread(client) -> int:
    groups = client.get('/api/sources').json()
    hn = next(g for g in groups if g['source'] == 'hn')
    return hn['subscriptions'][0]['unread']


def test_bulk_read_burns_only_what_was_admitted(env):
    """ "Mark all read" must burn exactly what the view showed (X's bulk_read_scope
    precedent). Burning an unadmitted story pre-reads an arrival the reader has
    not seen yet — it would land at the head of the timeline already grey."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(1800, 0, score=300)
        _pending(1801, 1, score=60)

        assert client.post('/api/read/bulk', json={'source': 'hn'}).status_code == 200
        assert all(it['is_read'] for it in client.get('/api/timeline').json()['items'])

        _config()
        _judge(at=NOON + timedelta(hours=1))
        arrivals = [it for it in client.get('/api/timeline').json()['items'] if it['hn']['id'] == 1801]
        assert arrivals and arrivals[0]['is_read'] is False


def test_search_still_finds_a_story_that_was_never_admitted(env):
    """Search reads the archive, not the reading list — every phase re-checks this."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        _pending(1900, 0, title='rust compiler internals', score=6)
        search.index_hn_story({'id': 1900, 'title': 'rust compiler internals', 'text': None, 'first_seen_at': NOON})

        _config()
        _judge()
        assert _ids(client) == []
        r = client.get('/api/search', params={'q': 'rust'})
        assert [it['key'] for it in r.json()['items']] == ['hn:1900']
        # no stamp, so the envelope falls back to the archive timestamp
        assert r.json()['items'][0]['datetime'].startswith(str(NOON.date()))


# --- D: history is stamped where it already sits -----------------------------


def test_the_v14_upgrade_reproduces_the_old_visible_set_exactly(env):
    """The migration is a backfill, and it has one acceptance condition: the
    timeline is item-for-item and position-for-position what it was (plan §5.4d).

    Rewound below to a pre-v14 database — columns dropped, version marker back to
    13 — then re-initialised, which is what a deploy does.
    """
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'top10', 'min_score': 50, 'max_peak_rank': 0})
        # one formed day: ranks 1..12 by score, the tail below the floor
        for i in range(12):
            seed_hn(2100 + i, i, score=300 - i * 25, qualified_at=None, qualified_rank=None)
        cfg = hn_source.stored_config()
        expected = db.stamp_hn_history(cfg, hn_source.day_quota(cfg, str(NOON.date())))
        before = _ids(client)
        assert expected == 10 and len(before) == 10

    # Rewind to a pre-v14 database, through peewee's own connection: ALTER TABLE
    # re-reads the whole schema, and a bare sqlite3 connection cannot parse the
    # sqlite-vec virtual table in it.
    tdb.db.execute_sql('DROP INDEX IF EXISTS hnstory_qualified_at')
    for column in ('qualified_at', 'qualified_rank'):
        tdb.db.execute_sql(f'ALTER TABLE hn_stories DROP COLUMN {column}')
    db.set_meta('schema_version', '13')
    db.set_meta(db.BACKFILL_META_KEY, '')  # a v13 database has no marker
    db.close_db()

    with _client() as client:  # re-runs init_db -> the v14 migration
        _login(client)
        assert db.get_meta('schema_version') == '14'
        assert _ids(client) == before
        # The migration adds an indexed column, and getting its position in
        # init_db wrong corrupts the table while reporting something unrelated
        # ("database disk image is malformed" on the next write). Ask directly.
        assert tdb.db.execute_sql('PRAGMA integrity_check').fetchall() == [('ok',)]


def test_an_imported_hckrnews_day_is_stamped_where_it_sits(env):
    """The live judge would admit none of these — they are outside its window by
    construction (hckrnews days are >= 2 days old) — and stamping them at ``now``
    would dump a week of history at the top of the timeline."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        day = (NOON - timedelta(days=4)).date()
        for i in range(12):
            past = datetime.combine(day, datetime.min.time()) + timedelta(hours=i)
            _pending(2200 + i, 0, first_seen_at=past, day=str(day), score=300 - i * 25, backfilled=True)
        _config()

        assert _judge() == 0
        assert hn_source.stamp_history(str(day)) == 10

        days = {d['date']: d['count'] for d in client.get('/api/timeline/days').json()}
        assert days == {str(day): 10}


def test_topping_up_a_day_the_sampler_already_watched(env):
    """Every new subscriber hits this: they subscribe on day 0, and on day 2 the
    hckrnews import arrives for day 0 — which already has live-admitted stories.
    The import fills the day's remaining slots, it does not double them."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        _config()
        for i in range(3):
            _pending(2300 + i, i, score=300)
        assert _judge(at=NOON.replace(hour=8)) == 3  # ceil(10 * 8/24)

        for i in range(12):
            _pending(2400 + i, 20 + i, score=200 - i)
        assert hn_source.stamp_history(str(NOON.date())) == 7  # 10 - 3
        assert len(_ids(client)) == 10


def test_a_paused_subscription_keeps_its_history_through_the_upgrade(env):
    """Stamping reads the stored config whether or not the feed is enabled: the
    archive *was* visible under some rule, and re-reading the defaults instead
    would rewrite that history the moment the reader resumes the feed."""
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'top10', 'min_score': 0})
        for i in range(4):
            seed_hn(2500 + i, i, score=6, qualified_at=None, qualified_rank=None)
        db.update_hn_subscription('front', enabled=False)

        assert hn_source.feed_config() is None
        assert hn_source.stamp_history() == 4

        db.update_hn_subscription('front', enabled=True)
        assert len(_ids(client)) == 4


# --- D: replay ---------------------------------------------------------------


def test_a_pre_v14_saved_record_falls_back_to_the_archive_timestamp(env):
    """A record saved before the stamp existed has no ``qualified_at`` in its
    snapshot at all, and its datetime must not come back null (plan §5.4e)."""
    with _client() as client:
        _login(client)
        subscribe_hn()
        seed_hn(2600, 0, score=300)
        assert client.post('/api/records', json={'key': 'hn:2600'}).status_code == 200

        rec = db.SavedItem.get(db.SavedItem.source == 'hn', db.SavedItem.ref1 == 2600)
        snapshot = json.loads(rec.raw_data)
        assert snapshot.pop('qualified_at')  # written today
        db.SavedItem.update(raw_data=json.dumps(snapshot)).where(db.SavedItem.ref1 == 2600).execute()

        item = client.get('/api/records').json()[0]
        assert item['datetime'] == item['hn']['first_seen_at']


# --- configuration ----------------------------------------------------------


def test_a_config_without_the_new_keys_gets_the_defaults(env):
    """Production's row predates both floors; the score floor must still be armed."""
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'top10'})
        _pending(2700, 0, score=6, peak_rank=3)
        _pending(2701, 1, score=200, peak_rank=3)

        _judge()
        assert _ids(client) == [2701]


def test_unparseable_floor_values_fall_back_to_the_defaults(env):
    """The config is a free-form JSON dict a PATCH can write anything into.

    Coercing at the read boundary keeps junk out of the SQL, and falling back to
    the default rather than to 0 means a typo cannot silently disarm the floor.
    """
    with _client() as client:
        _login(client)
        subscribe_hn()
        _pending(2800, 0, score=6, peak_rank=3)

        _config(min_score='fifty', max_peak_rank=[20])
        assert _judge() == 0


def test_new_subscriptions_carry_both_floors(env):
    assert DEFAULT_FEED_CONFIG['min_score'] == 50
    assert DEFAULT_FEED_CONFIG['max_peak_rank'] == 0  # shipped off — see the test above
    with _client() as client:
        _login(client)
        assert client.post('/api/sources/hn/subscriptions', json={'channel_id': 'front'}).status_code == 200
        assert json.loads(db.get_hn_subscription('front').config) == DEFAULT_FEED_CONFIG


def test_config_patch_merges_instead_of_replacing(env):
    """Three keys share one config column, so a whole-value write loses two of them."""
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


def test_tightening_a_rule_only_binds_from_now_on(env):
    """`display_mode` changed meaning in v14: a retrospective view filter became a
    prospective rate. Widening admits more *from here*; narrowing does not recall
    what yesterday already gave you. The UI has to say so."""
    with _client() as client:
        _login(client)
        subscribe_hn(config={'display_mode': 'top10', 'min_score': 0})
        _pending(2900, 0, score=30)
        _judge()
        assert _ids(client) == [2900]

        client.patch('/api/sources/hn/subscriptions/front', json={'config': {'min_score': 150}})
        assert _ids(client) == [2900]
        _pending(2901, 1, score=30)
        _judge(at=NOON + timedelta(hours=6))
        assert _ids(client) == [2900]
