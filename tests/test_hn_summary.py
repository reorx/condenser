"""Behavior tests for the HN summary pipeline (plan 2026-09-02 Phase B).

The project's **third** per-item billed component, and it copies the RSS one's
fences (``tests/test_rss_summary.py``): most cases here are about the API *not*
being called — no key, the switch off, a read story, a story the judge never
admitted, a discussion that has not formed yet, a batch already spent, a story
that failed too often.

What is new against RSS is the *material*: an HN story carries no body of its
own, so the round fetches two things per story — the article (``fetch_article``,
the injected extraction) and the discussion (Algolia, through ``fetch_json``,
the same seam ``HNManager`` already has). Both fail independently and neither
failure is the model's fault, so neither is charged to the story's retry budget
(plan §0.7): the article degrades to the preview description, and a missing
discussion skips the story for this round.

Everything is injected; no test touches the network. The one real HTTP path —
the article fetch — gets a transport-level test at the bottom, for the reason
``test_rss_summary`` states: an injectable boundary leaves what is behind it
uncovered.
"""

import asyncio
import json
import os
import sqlite3
from datetime import timedelta

import httpx
import pytest

from condenser import db, search
from condenser import hn_summary as hn_summary_mod
from condenser import preview as preview_mod
from condenser import summary as summary_mod
from condenser.config import get_settings
from condenser.items import parse_key
from tests.conftest import BASE
from tests.test_multi_source import _client, _login, seed_hn, subscribe_hn
from tests.test_rss_summary import FakeSummarizer

# The round's clock (naive UTC). Stories are seeded relative to it.
NOW = BASE.replace(tzinfo=None)


def algolia_url(sid):
    return hn_summary_mod.ALGOLIA_ITEM_URL.format(id=sid)


@pytest.fixture
def hn_summary_env(env, monkeypatch):
    """HN on, a summary API key configured, background loops silenced.

    The key is the on switch (shared with RSS — plan §3.4), so a fixture that
    forgot it would make every test below pass for the wrong reason. The fixed
    clock is in the past, so the retention rules are off (the CLAUDE.md trap).
    """
    monkeypatch.setenv('CONDENSER_HN_ENABLED', 'true')
    monkeypatch.setenv('CONDENSER_SUMMARY_API_KEY', 'test-key')
    monkeypatch.setenv('CONDENSER_CLEANUP_RSS_ENABLED', 'false')
    monkeypatch.setenv('CONDENSER_CLEANUP_X_ENABLED', 'false')
    get_settings.cache_clear()

    async def _no_loop(self):
        return None

    monkeypatch.setattr('condenser.hn.HNManager.startup', _no_loop)
    monkeypatch.setattr('condenser.rss.RssManager.startup', _no_loop)
    yield


class FakeFetch:
    """URL -> canned JSON (or an Exception to raise). Records every call."""

    def __init__(self):
        self.responses = {}
        self.calls = []

    def set(self, url, payload):
        self.responses[url] = payload

    async def __call__(self, url):
        self.calls.append(url)
        if url not in self.responses:
            raise KeyError(f'unexpected URL fetched: {url}')
        v = self.responses[url]
        if isinstance(v, Exception):
            raise v
        return json.loads(json.dumps(v)) if v is not None else None


class FakeArticle:
    """URL -> extracted article text (or an Exception to raise). Records every call."""

    def __init__(self, default='文章正文：一种新的压缩算法把索引缩小了一半。'):
        self.default = default
        self.results = {}
        self.calls = []

    def set(self, url, result):
        self.results[url] = result

    async def __call__(self, url):
        self.calls.append(url)
        r = self.results.get(url, self.default)
        if isinstance(r, Exception):
            raise r
        return r


def configure(monkeypatch, **overrides):
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    get_settings.cache_clear()
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    subscribe_hn()
    return get_settings()


def comment(cid, text, author='bob', children=()):
    return {'id': cid, 'type': 'comment', 'author': author, 'text': f'<p>{text}</p>', 'children': list(children)}


def thread(sid, children=()):
    """An Algolia items/{id} document: the story with its whole comment tree."""
    return {'id': sid, 'type': 'story', 'title': f'S{sid}', 'children': list(children)}


def seed(sid, hours_ago=4, comments=1, read=False, **over):
    """A qualified, unread, linkable story ``hours_ago`` old with ``comments`` replies.

    The default clears the age gate (3h) and not the comment gate (10), so a case
    that wants the comment gate says so.
    """
    minutes = -int(hours_ago * 60)
    fields = dict(
        comments_count=comments, preview=json.dumps({'url': f'https://ex.com/{sid}', 'description': f'Desc {sid}'})
    )
    fields.update(over)
    seed_hn(sid, minutes, **fields)
    if read:
        db.mark_read([parse_key(f'hn:{sid}')])
    return db.get_hn_story(sid)


def reload(sid):
    return db.get_hn_story(sid)


def run(settings, fetch, article=None, summarize=None, now=NOW):
    return asyncio.run(
        hn_summary_mod.run_round(
            settings,
            fetch_json=fetch,
            fetch_article=article or FakeArticle(),
            summarize=summarize or FakeSummarizer(),
            now=now,
        )
    )


def wired(sid, fetch=None, children=()):
    """A FakeFetch that knows the story's discussion."""
    fetch = fetch or FakeFetch()
    fetch.set(algolia_url(sid), thread(sid, children))
    return fetch


# --- schema -------------------------------------------------------------------


def test_schema_version_is_19(env):
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    assert db.SCHEMA_VERSION == 19
    assert db.get_meta('schema_version') == '19'


def test_a_pre_v19_hn_stories_table_gains_the_summary_columns(env):
    """Shape-based ADD COLUMNs before ``create_tables`` (the v14/v16/v18 position),
    data intact, idempotent, and the table stays writable afterwards — the failure
    v14 found is a corrupted index that only shows on the next write."""
    path = os.environ['CONDENSER_DB_PATH']
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE hn_stories ('
        'id INTEGER NOT NULL PRIMARY KEY, title TEXT, url TEXT, domain TEXT, author TEXT, text TEXT, '
        'type VARCHAR(255) NOT NULL, submitted_at DATETIME, first_seen_at DATETIME NOT NULL, '
        'day VARCHAR(255) NOT NULL, score INTEGER NOT NULL, comments_count INTEGER NOT NULL, '
        'score_updated_at DATETIME, peak_rank INTEGER, is_dead INTEGER NOT NULL, backfilled INTEGER NOT NULL, '
        'preview TEXT, preview_attempts INTEGER NOT NULL DEFAULT 0, qualified_at DATETIME, qualified_rank INTEGER)'
    )
    conn.execute(
        'INSERT INTO hn_stories (id, title, url, type, first_seen_at, day, score, comments_count, is_dead, backfilled) '
        "VALUES (1, 'old', 'https://example.com/1', 'story', '2026-07-01 10:00:00', '2026-07-01', 5, 0, 0, 0)"
    )
    conn.commit()
    conn.close()

    db.init_db(path)
    db.init_db(path)  # idempotent

    story = db.get_hn_story(1)
    assert story.title == 'old'
    assert story.summary is None and story.summary_model is None and story.summary_attempts == 0
    db.set_hn_summary(1, '摘要。', 'm@v1')
    assert db.get_hn_story(1).summary == '摘要。'
    conn = sqlite3.connect(path)
    assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    conn.close()


# --- the happy path -----------------------------------------------------------


def test_a_discussed_story_gets_a_summary_from_article_and_thread(hn_summary_env, monkeypatch):
    """The whole feature in one round: the article text and the discussion go out
    together, the summary comes back onto the row, and what wrote it is recorded."""
    settings = configure(monkeypatch)
    seed(1, comments=12)
    fetch = wired(1, children=[comment(10, '这个算法的内存开销被低估了', children=[comment(11, '作者在附录里回应了')])])
    article = FakeArticle()
    fake = FakeSummarizer(answer='文章介绍了新的压缩算法。讨论集中在内存开销。')

    stats = run(settings, fetch, article, fake)

    story = reload(1)
    assert story.summary == '文章介绍了新的压缩算法。讨论集中在内存开销。'
    assert story.summary_model == hn_summary_mod.model_tag(settings)
    assert story.summary_attempts == 0
    assert stats['summarized'] == 1
    assert article.calls == ['https://ex.com/1']
    title, material = fake.calls[0]
    assert title == 'S1'
    assert '一种新的压缩算法' in material
    assert '内存开销被低估' in material
    assert '作者在附录里回应了' in material  # a reply travels under its parent
    assert '<p>' not in material


def test_a_summarized_story_is_never_summarized_again(hn_summary_env, monkeypatch):
    """One summary per story (plan §3.3): no refresh when the thread doubles."""
    settings = configure(monkeypatch)
    seed(1, comments=12)
    fetch = wired(1)
    fake = FakeSummarizer()

    run(settings, fetch, summarize=fake)
    db.update_hn_snapshot(1, 200, 80, NOW)
    run(settings, fetch, summarize=fake)

    assert len(fake.calls) == 1


def test_the_summary_joins_the_search_document(hn_summary_env, monkeypatch):
    """The story was indexed at ingest, before the summary existed; the round has
    to re-index — it is what the card will show, and the reader searches for
    what they remember reading."""
    settings = configure(monkeypatch)
    seed(1, comments=12)
    search.index_hn_story({'id': 1, 'title': 'S1', 'text': None, 'first_seen_at': NOW, 'is_dead': False})

    run(settings, wired(1), summarize=FakeSummarizer(answer='文章介绍了新的压缩算法。'))

    rows, _total = search.search(search.build_match('压缩算法'), limit=10)
    assert [row['ref1'] for row in rows] == [1]


def test_the_payload_carries_the_summary(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch)
    seed(1, comments=12)
    seed(2, comments=12)
    fetch = wired(1)
    run(settings, fetch, summarize=FakeSummarizer(answer='摘要一。'))

    with _client() as client:
        _login(client)
        items = client.get('/api/timeline', params={'limit': 10}).json()['items']

    by_id = {it['hn']['id']: it['hn'] for it in items if it['source'] == 'hn'}
    assert by_id[1]['summary'] == '摘要一。'
    assert by_id[2]['summary'] is None


# --- candidates: what waits for a summary -------------------------------------


def test_only_a_formed_discussion_is_summarized(hn_summary_env, monkeypatch):
    """The gate (plan §3.3): ten comments **or** three hours on the front page.
    Earlier than both, the thread is still writing itself."""
    settings = configure(monkeypatch)
    seed(1, hours_ago=1, comments=12)  # comments clear it
    seed(2, hours_ago=4, comments=0)  # age clears it
    seed(3, hours_ago=1, comments=3)  # neither
    fetch = wired(1)
    wired(2, fetch)
    wired(3, fetch)
    fake = FakeSummarizer()

    run(settings, fetch, summarize=fake)

    assert sorted(title for title, _ in fake.calls) == ['S1', 'S2']


def test_a_story_the_judge_never_admitted_is_not_summarized(hn_summary_env, monkeypatch):
    """Not on the timeline (v14) means not in front of the reader."""
    settings = configure(monkeypatch)
    seed(1, comments=12, qualified_at=None, qualified_rank=None)
    fake = FakeSummarizer()

    run(settings, wired(1), summarize=fake)

    assert fake.calls == []


def test_a_read_story_is_not_summarized(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch)
    seed(1, comments=12, read=True)
    seed(2, comments=12)
    fetch = wired(1)
    wired(2, fetch)
    fake = FakeSummarizer()

    run(settings, fetch, summarize=fake)

    assert [title for title, _ in fake.calls] == ['S2']


def test_dead_stories_and_jobs_are_not_summarized(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch)
    seed(1, comments=12, is_dead=True)
    seed(2, comments=12, type='job')
    fetch = wired(1)
    wired(2, fetch)
    fake = FakeSummarizer()

    run(settings, fetch, summarize=fake)

    assert fake.calls == []


def test_a_round_summarizes_at_most_one_batch_newest_first(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch, CONDENSER_HN_SUMMARY_BATCH=2)
    fetch = FakeFetch()
    for sid, hours in ((1, 6), (2, 5), (3, 4)):
        seed(sid, hours_ago=hours, comments=12)
        wired(sid, fetch)
    fake = FakeSummarizer()

    run(settings, fetch, summarize=fake)

    assert [title for title, _ in fake.calls] == ['S3', 'S2']


# --- the fences: what must not be billed --------------------------------------


def test_without_an_api_key_nothing_is_summarized(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch, CONDENSER_SUMMARY_API_KEY='')
    seed(1, comments=12)
    fetch = wired(1)
    article = FakeArticle()
    fake = FakeSummarizer()

    stats = run(settings, fetch, article, fake)

    assert fake.calls == [] and article.calls == [] and fetch.calls == []
    assert stats['summarized'] == 0
    assert hn_summary_mod.available(settings) is False


def test_the_hn_switch_turns_it_off_with_a_key_configured(hn_summary_env, monkeypatch):
    """Its own switch, the shared key: turning HN summaries off must not touch RSS."""
    settings = configure(monkeypatch, CONDENSER_HN_SUMMARY_ENABLED='false')
    seed(1, comments=12)
    fake = FakeSummarizer()

    run(settings, wired(1), summarize=fake)

    assert fake.calls == []
    assert summary_mod.available(settings) is True


# --- material: the two fetches and their failures -----------------------------


def test_an_unreachable_article_degrades_to_the_preview_description(hn_summary_env, monkeypatch):
    """Plan §0.7: the fetch failing is not the model's fault. The summary is still
    written — from the discussion and whatever the preview prefetch saw — and the
    story's retry budget is untouched."""
    settings = configure(monkeypatch)
    seed(1, comments=12)
    article = FakeArticle()
    article.set('https://ex.com/1', httpx.ConnectTimeout('slow'))
    fake = FakeSummarizer()

    run(settings, wired(1, children=[comment(10, '很有意思')]), article, fake)

    story = reload(1)
    assert story.summary is not None
    assert story.summary_attempts == 0
    _title, material = fake.calls[0]
    assert 'Desc 1' in material
    assert '很有意思' in material
    assert hn_summary_mod.NO_ARTICLE in material  # the model is told, not left to guess


def test_a_self_post_uses_its_own_text_and_fetches_nothing(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch)
    seed(1, comments=12, url=None, domain=None, text='<p>Ask HN: how do you <i>test</i> migrations?</p>', preview=None)
    article = FakeArticle()
    fake = FakeSummarizer()

    run(settings, wired(1), article, fake)

    assert article.calls == []
    _title, material = fake.calls[0]
    assert 'how do you test migrations?' in material
    assert '<i>' not in material


def test_a_missing_discussion_skips_the_story_for_this_round(hn_summary_env, monkeypatch):
    """Algolia down is not evidence about the story: no charge, no decision, and
    the next round picks it up where it was."""
    settings = configure(monkeypatch)
    seed(1, comments=12)
    fetch = FakeFetch()
    fetch.set(algolia_url(1), httpx.ReadTimeout('algolia'))
    fake = FakeSummarizer()

    stats = run(settings, fetch, summarize=fake)

    assert fake.calls == []
    assert stats['skipped'] == 1
    assert reload(1).summary_attempts == 0 and reload(1).summary_model is None

    wired(1, fetch)
    run(settings, fetch, summarize=fake)
    assert reload(1).summary is not None


def test_a_story_with_nothing_to_read_is_decided_not_retried(hn_summary_env, monkeypatch):
    """No article, no description, no comments, no self text: there is nothing to
    summarize, and paying to say so would be the worst outcome. Recorded as a
    decision (the ``skip:short`` arrangement) so it stops re-entering the batch."""
    settings = configure(monkeypatch)
    seed(1, hours_ago=4, comments=0, preview=None)
    article = FakeArticle()
    article.set('https://ex.com/1', httpx.ConnectTimeout('slow'))
    fake = FakeSummarizer()

    stats = run(settings, wired(1), article, fake)

    assert fake.calls == []
    assert reload(1).summary is None
    assert reload(1).summary_model == hn_summary_mod.SKIP_EMPTY
    assert stats['skipped_empty'] == 1
    assert hn_summary_mod.counts(settings)['pending'] == 0


def test_the_discussion_is_flattened_two_replies_deep_and_capped(hn_summary_env, monkeypatch):
    """Top-level comments in Algolia's order, each with at most two levels of
    replies (plan §3.2); deleted comments (null text) vanish; the whole thing is cut
    at the configured length so a 900-comment thread is not the bill."""
    settings = configure(monkeypatch, CONDENSER_HN_SUMMARY_MAX_DISCUSSION_CHARS=120)
    seed(1, comments=12)
    deep = comment(13, 'level three', children=[comment(14, 'level four')])
    children = [
        comment(
            10, 'top one', children=[comment(11, 'reply one', children=[comment(12, 'reply two', children=[deep])])]
        ),
        {'id': 20, 'type': 'comment', 'author': None, 'text': None, 'children': []},
        comment(30, 'top two ' + 'x' * 200),
    ]
    fake = FakeSummarizer()

    run(settings, wired(1, children=children), summarize=fake)

    _title, material = fake.calls[0]
    assert 'top one' in material and 'reply one' in material and 'reply two' in material
    assert 'level three' not in material and 'level four' not in material
    assert material.index('top one') < material.index('reply one') < material.index('reply two')
    discussion = hn_summary_mod.discussion_text(thread(1, children), max_chars=120)
    assert len(discussion) <= 120 + len(hn_summary_mod.CUT_MARK)
    assert discussion.endswith(hn_summary_mod.CUT_MARK)


def test_the_article_is_truncated(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch, CONDENSER_HN_SUMMARY_MAX_ARTICLE_CHARS=100)
    seed(1, comments=12)
    fake = FakeSummarizer()

    run(settings, wired(1), FakeArticle(default='正' * 500), fake)

    _title, material = fake.calls[0]
    assert material.count('正') == 100


# --- failure accounting -------------------------------------------------------


def test_a_failing_story_is_retried_then_given_up_on(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch)
    seed(1, comments=12)
    fetch = wired(1)
    fake = FakeSummarizer(errors=[summary_mod.SummaryError('rejected')] * 4)

    for _ in range(4):
        run(settings, fetch, summarize=fake)

    assert len(fake.calls) == summary_mod.MAX_ATTEMPTS
    assert reload(1).summary is None
    assert reload(1).summary_attempts == summary_mod.MAX_ATTEMPTS
    assert hn_summary_mod.counts(settings)['failed'] == 1


def test_one_bad_story_does_not_stop_the_others(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch)
    seed(1, hours_ago=5, comments=12)
    seed(2, hours_ago=4, comments=12)
    fetch = wired(1)
    wired(2, fetch)
    fake = FakeSummarizer(errors=[summary_mod.SummaryError('rejected'), None])

    stats = run(settings, fetch, summarize=fake)

    assert stats == {'summarized': 1, 'failed': 1, 'skipped': 0, 'skipped_empty': 0, 'provider_error': None}
    assert reload(2).summary_attempts == 1 and reload(1).summary is not None


def test_a_provider_outage_ends_the_round_and_charges_nobody(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch)
    seed(1, hours_ago=5, comments=12)
    seed(2, hours_ago=4, comments=12)
    fetch = wired(1)
    wired(2, fetch)
    article = FakeArticle()
    fake = FakeSummarizer(errors=[summary_mod.ProviderUnavailable('503')])

    stats = run(settings, fetch, article, fake)

    assert len(fake.calls) == 1  # the newest was tried; the older was never reached
    assert stats['provider_error'] and stats['summarized'] == 0
    assert reload(1).summary_attempts == 0 and reload(2).summary_attempts == 0
    assert article.calls == ['https://ex.com/2']  # nothing fetched for the story never reached


# --- status -------------------------------------------------------------------


def test_status_reports_the_summary_backlog(hn_summary_env, monkeypatch):
    settings = configure(monkeypatch, CONDENSER_HN_SUMMARY_BATCH=1)
    seed(1, hours_ago=5, comments=12)  # left behind by a batch of one
    seed(2, hours_ago=4, comments=12)  # done
    seed(3, hours_ago=1, comments=2)  # not formed: not pending
    fetch = wired(1)
    wired(2, fetch)
    run(settings, fetch)
    # the age gate reads the manager's clock, and the app builds its own manager
    monkeypatch.setattr('condenser.hn.HNManager._now', staticmethod(lambda: NOW))

    with _client() as client:
        _login(client)
        st = client.get('/api/hn/status').json()['summary']

    assert st == {
        'enabled': True,
        'model': hn_summary_mod.model_tag(settings),
        'pending': 1,
        'done': 1,
        'failed': 0,
    }


def test_status_says_when_summaries_are_off(hn_summary_env, monkeypatch):
    configure(monkeypatch, CONDENSER_SUMMARY_API_KEY='')
    seed(1, comments=12)

    with _client() as client:
        _login(client)
        st = client.get('/api/hn/status').json()['summary']

    assert st['enabled'] is False and st['model'] is None
    assert st['pending'] == 1


# --- wiring -------------------------------------------------------------------


def test_a_poll_round_summarizes_after_admission(hn_summary_env, monkeypatch):
    """The pipeline hangs off the tail of the sampling round, after ``_qualify``:
    a story admitted this round is a candidate this round."""
    from tests.test_hn import TOPSTORIES, FakePreview, item_url, make_manager, story, unix

    configure(monkeypatch)
    fetch = FakeFetch()
    fetch.set(TOPSTORIES, [1])
    # score clears the admission floor (sources/hn.DEFAULT_MIN_SCORE); the comment
    # count clears the summary gate the same round
    fetch.set(item_url(1), story(1, descendants=15, score=120, time=unix(NOW - timedelta(hours=1))))
    wired(1, fetch, children=[comment(10, 'good')])
    fake = FakeSummarizer()
    mgr = make_manager(fetch, now=NOW, fetch_preview=FakePreview())
    mgr._fetch_article = FakeArticle()
    mgr._summarize = fake

    asyncio.run(mgr.poll_once())

    assert [title for title, _ in fake.calls] == ['Story 1']
    assert reload(1).qualified_at is not None
    assert reload(1).summary is not None
    assert mgr.status()['last_error'] is None


def test_a_summary_failure_does_not_sink_the_polling_round(hn_summary_env, monkeypatch):
    from tests.test_hn import TOPSTORIES, FakePreview, item_url, make_manager, story, unix

    configure(monkeypatch)
    fetch = FakeFetch()
    fetch.set(TOPSTORIES, [1])
    fetch.set(item_url(1), story(1, descendants=15, score=120, time=unix(NOW - timedelta(hours=1))))
    wired(1, fetch)

    async def boom(*_a, **_k):
        raise RuntimeError('unexpected shape')

    mgr = make_manager(fetch, now=NOW, fetch_preview=FakePreview())
    mgr._fetch_article = FakeArticle()
    mgr._summarize = boom

    asyncio.run(mgr.poll_once())

    assert reload(1) is not None  # the ingest survived
    assert mgr.status()['last_poll_at'] is not None
    assert mgr.status()['last_error'] is None


# --- the article: extraction + the real fetch ---------------------------------


PAGE = (
    '<html><head><title>Compression</title><style>p{color:red}</style></head><body>'
    '<nav><a href="/">Home</a><a href="/about">About</a></nav>'
    '<div id="content"><h1>A smaller index</h1>'
    + ''.join(
        f'<p>Paragraph {i}: the new compression scheme halves the index while keeping lookups constant time.</p>'
        for i in range(8)
    )
    + '</div><script>track()</script><footer>© 2026 Example</footer></body></html>'
)


def test_extract_article_keeps_the_prose_and_drops_the_chrome():
    text = hn_summary_mod.extract_article(PAGE)
    assert 'halves the index' in text
    assert 'Paragraph 7' in text
    assert 'track()' not in text and 'color:red' not in text
    assert '<p>' not in text


def test_extract_article_survives_garbage():
    """Empty is None (nothing to read); non-HTML does not raise — readability
    returns it as text, and the round would rather feed the model a line of junk
    than lose the discussion half over it."""
    assert hn_summary_mod.extract_article('') is None
    assert hn_summary_mod.extract_article('   ') is None
    assert isinstance(hn_summary_mod.extract_article('<<<>>>'), (str, type(None)))


def test_the_real_article_fetch_goes_through_the_preview_fetcher(hn_summary_env, monkeypatch):
    """Same UA, same timeout, its own byte cap (plan §3.2) — and a non-HTML answer
    (a PDF link, a bare JSON API) is "no article", not a crash."""
    settings = configure(monkeypatch)
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith('.pdf'):
            return httpx.Response(200, content=b'%PDF-1.4', headers={'content-type': 'application/pdf'})
        return httpx.Response(200, content=PAGE.encode(), headers={'content-type': 'text/html; charset=utf-8'})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        preview_mod.httpx,
        'AsyncClient',
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    text = asyncio.run(hn_summary_mod.fetch_article('https://ex.com/post', settings))
    assert 'halves the index' in text
    assert seen[0].headers['user-agent'] == settings.condenser_preview_user_agent

    assert asyncio.run(hn_summary_mod.fetch_article('https://ex.com/paper.pdf', settings)) is None
