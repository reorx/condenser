"""Behavior tests for the RSS summary pipeline, Phase 3.

The project's **second per-item billed component** (channel C's attribute
extractor was the first), and the tests are shaped by that: most of them are
about the API *not* being called — no key, a read entry, an entry short enough to
read as-is, a paused feed, a batch already spent, an entry that has failed too
often. The one that does spend is deliberately the least interesting.

The summariser is injected (``FakeSummarizer``), so no test touches the network —
the ``FakeExtractor`` / ``FakeEmbedder`` pattern. The real HTTP call gets its own
transport-level section at the bottom, because Phase 1's live run proved that an
injectable boundary leaves the implementation behind it completely uncovered.

Plan: kb/plans/2026-08-20-rss-source-opml-llm-summary.md §3 / §10 Phase 3.
"""

import asyncio
import json
import os
import time
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from condenser import db, search
from condenser import summary as summary_mod
from condenser.app import create_app
from condenser.config import get_settings
from condenser.items import parse_key
from tests.conftest import BASE

FEED = 'https://a.example.com/feed.xml'
OTHER_FEED = 'https://b.example.com/feed.xml'

# The archive's clock. Naive UTC, the storage convention.
T0 = BASE.replace(tzinfo=None)


@pytest.fixture
def summary_env(env, monkeypatch):
    """RSS on, a summary API key configured, and both background loops silenced.

    The key is the on switch (plan §3), so a fixture that forgot it would make
    every test below pass for the wrong reason. ``conftest`` blanks it by default
    for exactly the opposite reason — no other test may spend money.
    """
    monkeypatch.setenv('CONDENSER_RSS_ENABLED', 'true')
    monkeypatch.setenv('CONDENSER_SUMMARY_API_KEY', 'test-key')
    # This module's clock is fixed in the past and the daily sweep runs on the
    # first round of every app, so the retention rule would delete the fixtures
    # out from under the assertions (the trap test_x_verdict hit on 2026-08-09).
    monkeypatch.setenv('CONDENSER_CLEANUP_RSS_ENABLED', 'false')
    get_settings.cache_clear()

    async def _no_loop(self):
        return None

    monkeypatch.setattr('condenser.rss.RssManager.startup', _no_loop)
    yield


class FakeSummarizer:
    """(title, text) -> a canned summary, recording every call.

    "Was the API called at all, and with what" is what most of these tests assert,
    so the call log is the fixture's real output. ``errors`` is consumed one entry
    per call: an exception is raised, ``None`` succeeds.
    """

    def __init__(self, answer='这篇文章讲了三件事。', errors=()):
        self.answer = answer
        self.errors = list(errors)
        self.calls: list[tuple] = []

    async def __call__(self, title, text):
        self.calls.append((title, text))
        error = self.errors.pop(0) if self.errors else None
        if error is not None:
            raise error
        return self.answer(title) if callable(self.answer) else self.answer


def configure(monkeypatch, **overrides):
    """Apply env overrides, reload settings, open the DB, subscribe the feed."""
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    get_settings.cache_clear()
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    db.add_rss_subscription(FEED)
    return get_settings()


def body(chars=400, tag='p'):
    """An HTML body whose *text* is ``chars`` long — the gate measures the text."""
    return f'<{tag}>{"A" * chars}</{tag}>'


def seed_entry(guid, content=None, title=None, minutes=0, read=False, feed_url=FEED, **over):
    row = {
        'feed_url': feed_url,
        'guid': guid,
        'title': title if title is not None else f'Entry {guid}',
        'link': f'{feed_url}#{guid}',
        'author': None,
        'content': body() if content is None else content,
        'published_at': T0 + timedelta(minutes=minutes),
        'first_seen_at': T0 + timedelta(minutes=minutes),
    }
    row.update(over)
    db.insert_rss_entries([row], read_before=None, now=T0)
    entry = db.RssEntry.get((db.RssEntry.feed_url == feed_url) & (db.RssEntry.guid == guid))
    if read:
        db.mark_read([parse_key(f'rss:{entry.id}')])
    return entry


def reload_entry(entry):
    return db.RssEntry.get_by_id(entry.id)


def run(settings, summarize):
    return asyncio.run(summary_mod.run_round(settings, summarize=summarize))


# --- the happy path -----------------------------------------------------------


def test_an_unread_article_gets_a_chinese_summary(summary_env, monkeypatch):
    """The whole feature in one round: the entry's text goes out, the summary comes
    back onto the row, and the model that wrote it is recorded beside it."""
    settings = configure(monkeypatch)
    entry = seed_entry('a', content='<p>' + '独立开发者的故事。' * 40 + '</p>', title='A post')
    fake = FakeSummarizer()

    stats = run(settings, fake)

    saved = reload_entry(entry)
    assert saved.summary == '这篇文章讲了三件事。'
    assert saved.summary_model == summary_mod.model_tag(settings)
    assert saved.summary_attempts == 0
    assert stats['summarized'] == 1
    # the title travels with the text: a summary written without it is a summary of
    # a body that may never restate what the article is called
    assert fake.calls[0][0] == 'A post'
    assert '独立开发者的故事。' in fake.calls[0][1]
    # ...and the markup does not
    assert '<p>' not in fake.calls[0][1]


def test_a_summarized_entry_is_never_summarized_again(summary_env, monkeypatch):
    settings = configure(monkeypatch)
    seed_entry('a')
    fake = FakeSummarizer()

    run(settings, fake)
    run(settings, fake)

    assert len(fake.calls) == 1


def test_the_summary_joins_the_search_document(summary_env, monkeypatch):
    """The card shows the summary instead of the body (plan §0.4), so a phrase the
    reader remembers reading may exist nowhere else. The entry was indexed at ingest
    time, before the summary existed — the pipeline has to re-index."""
    settings = configure(monkeypatch)
    entry = seed_entry('a')
    search.index_rss_entries([entry.id])

    run(settings, FakeSummarizer(answer='文章介绍了新的压缩算法。'))

    rows, _total = search.search(search.build_match('压缩算法'), limit=10)
    assert [row['ref1'] for row in rows] == [entry.id]


# --- the fences: what must not be billed --------------------------------------


def test_without_an_api_key_nothing_is_summarized(summary_env, monkeypatch):
    """The key *is* the on switch (plan §3): deploying this code must not start
    spending on its own, so an install that never sets one runs the pipeline as a
    no-op forever."""
    settings = configure(monkeypatch, CONDENSER_SUMMARY_API_KEY='')
    entry = seed_entry('a')
    fake = FakeSummarizer()

    stats = run(settings, fake)

    assert fake.calls == []
    assert reload_entry(entry).summary is None
    assert stats['summarized'] == 0
    assert summary_mod.available(settings) is False


def test_the_switch_turns_it_off_with_a_key_configured(summary_env, monkeypatch):
    settings = configure(monkeypatch, CONDENSER_SUMMARY_ENABLED='false')
    seed_entry('a')
    fake = FakeSummarizer()

    run(settings, fake)

    assert fake.calls == []


def test_a_read_entry_is_not_summarized(summary_env, monkeypatch):
    """Only unread entries (plan §3). An OPML import archives every feed's whole
    retained window and marks all but the last week read; summarizing that backlog
    would be the import's real cost, and nobody would read a line of it."""
    settings = configure(monkeypatch)
    seed_entry('old', read=True)
    seed_entry('new')
    fake = FakeSummarizer()

    run(settings, fake)

    assert [title for title, _ in fake.calls] == ['Entry new']


def test_a_paused_feed_is_not_summarized(summary_env, monkeypatch):
    """Pausing a feed stops it reaching the reader, so its backlog stops being
    something they might read — and paying to describe it follows from nothing."""
    settings = configure(monkeypatch)
    db.add_rss_subscription(OTHER_FEED)
    db.update_rss_subscription(OTHER_FEED, enabled=False)
    seed_entry('paused', feed_url=OTHER_FEED)
    seed_entry('live')
    fake = FakeSummarizer()

    run(settings, fake)

    assert [title for title, _ in fake.calls] == ['Entry live']


def test_a_short_entry_is_shown_as_it_is(summary_env, monkeypatch):
    """Under the threshold the original *is* the summary (plan §0.1), so there is
    nothing to buy — a link-blog one-liner summarized is strictly worse than the
    one-liner."""
    settings = configure(monkeypatch)
    entry = seed_entry('short', content=body(50))
    fake = FakeSummarizer()

    stats = run(settings, fake)

    assert fake.calls == []
    assert reload_entry(entry).summary is None
    # Never even considered: a body this short cannot clear the gate whatever the
    # markup is, so the SQL pre-filter keeps it out of the batch entirely — and out
    # of `skipped_short`, which counts entries the pipeline actually measured.
    assert stats['skipped_short'] == 0
    assert reload_entry(entry).summary_model is None


def test_a_short_entry_wrapped_in_markup_is_still_short(summary_env, monkeypatch):
    """The gate measures text, not markup — and the decision is *recorded*, or a
    heavily-marked-up one-liner would fill a batch slot every round forever (its raw
    length clears the cheap SQL pre-filter, only the stripped text does not)."""
    settings = configure(monkeypatch)
    markup = '<div class="post-body entry-content">' + '<span><em>hi</em></span> ' * 20 + '</div>'
    entry = seed_entry('fat', content=markup)
    fake = FakeSummarizer()

    run(settings, fake)
    run(settings, fake)

    assert fake.calls == []
    assert reload_entry(entry).summary_model == summary_mod.SKIP_SHORT
    assert reload_entry(entry).summary is None  # the card still renders the body


def test_an_entry_with_no_body_is_left_alone(summary_env, monkeypatch):
    """Some feeds publish title + link only. There is nothing to summarize, and a
    model handed an empty body will invent one."""
    settings = configure(monkeypatch)
    seed_entry('empty', content='')
    seed_entry('null', minutes=1)
    # NULL rather than empty: feedparser leaves the column unset when an entry
    # carries neither <content:encoded> nor <description>.
    db.RssEntry.update(content=None).where(db.RssEntry.guid == 'null').execute()
    fake = FakeSummarizer()

    run(settings, fake)

    assert fake.calls == []


# --- rate limiting ------------------------------------------------------------


def test_a_round_summarizes_at_most_one_batch(summary_env, monkeypatch):
    """The per-round cap is the spend ceiling (plan §3 fence 3). An OPML import puts
    hundreds of unread entries in front of the pipeline at once, and without the cap
    the first round after an import is an unbounded bill."""
    settings = configure(monkeypatch, CONDENSER_SUMMARY_BATCH=2)
    for i in range(5):
        seed_entry(f'e{i}', minutes=i)
    fake = FakeSummarizer()

    run(settings, fake)
    assert len(fake.calls) == 2

    run(settings, fake)
    assert len(fake.calls) == 4  # the backlog drains one batch per round


def test_the_newest_entries_are_summarized_first(summary_env, monkeypatch):
    """A backlog drains over hours, so the order decides what the reader finds
    summarized when they next open the app — which is the top of the timeline."""
    settings = configure(monkeypatch, CONDENSER_SUMMARY_BATCH=2)
    seed_entry('oldest', minutes=0)
    seed_entry('middle', minutes=10)
    seed_entry('newest', minutes=20)
    fake = FakeSummarizer()

    run(settings, fake)

    assert [title for title, _ in fake.calls] == ['Entry newest', 'Entry middle']


def test_each_entry_is_its_own_request(summary_env, monkeypatch):
    """Never batched into one prompt (the attributes lesson): a model that returns
    four answers for five articles silently misaligns every one after the gap, and
    here the damage is a summary attached to the wrong article."""
    settings = configure(monkeypatch)
    for i in range(3):
        seed_entry(f'e{i}', content=body(300 + i))
    fake = FakeSummarizer()

    run(settings, fake)

    assert len(fake.calls) == 3
    assert len({text for _, text in fake.calls}) == 3


def test_the_input_is_truncated(summary_env, monkeypatch):
    """A long-read costs input tokens linearly and adds nothing after the first few
    thousand characters — the summary is 2-3 sentences either way."""
    settings = configure(monkeypatch, CONDENSER_SUMMARY_MAX_INPUT_CHARS=500)
    seed_entry('long', content=body(20_000))
    fake = FakeSummarizer()

    run(settings, fake)

    assert len(fake.calls[0][1]) == 500


# --- failure ------------------------------------------------------------------


def test_a_failing_entry_is_retried_then_given_up_on(summary_env, monkeypatch):
    """Per-entry degradation (the t.co precedent): the card falls back to truncated
    source text and every other entry is unaffected. The ceiling exists because some
    entries fail every time — a body the model refuses, one that trips a content
    filter — and retrying those forever is a standing charge."""
    settings = configure(monkeypatch)
    entry = seed_entry('bad')

    for expected in (1, 2, 3):
        fake = FakeSummarizer(errors=[summary_mod.SummaryError('unusable answer')])
        stats = run(settings, fake)
        assert len(fake.calls) == 1
        assert reload_entry(entry).summary_attempts == expected
        assert stats['failed'] == 1

    fake = FakeSummarizer()
    run(settings, fake)
    assert fake.calls == []  # the ceiling is final
    assert reload_entry(entry).summary is None


def test_one_bad_entry_does_not_stop_the_others(summary_env, monkeypatch):
    settings = configure(monkeypatch)
    seed_entry('bad', minutes=10)
    good = seed_entry('good', minutes=0)
    fake = FakeSummarizer(errors=[summary_mod.SummaryError('nope'), None])

    stats = run(settings, fake)

    assert reload_entry(good).summary is not None
    assert stats == {'summarized': 1, 'skipped_short': 0, 'failed': 1, 'provider_error': None}


def test_a_provider_outage_does_not_burn_the_retry_budget(summary_env, monkeypatch):
    """ "The API is down" is not evidence about an entry. Counting it would spend all
    three attempts of every queued entry during one outage and leave a whole backlog
    permanently unsummarizable (the HN "a fresh negative cache hit is not an attempt"
    lesson). The round stops too: with the provider down, the next 19 requests are
    19 more failures."""
    settings = configure(monkeypatch)
    first = seed_entry('a', minutes=10)
    second = seed_entry('b', minutes=0)
    fake = FakeSummarizer(errors=[summary_mod.ProviderUnavailable('502 from the gateway')])

    stats = run(settings, fake)

    assert len(fake.calls) == 1  # stopped, rather than failing 19 more times
    assert reload_entry(first).summary_attempts == 0
    assert reload_entry(second).summary_attempts == 0
    assert stats['provider_error'] and stats['summarized'] == 0

    # ...and the next round picks both up as if nothing had happened
    recovered = FakeSummarizer()
    run(settings, recovered)
    assert len(recovered.calls) == 2


# --- text extraction ----------------------------------------------------------


def test_plain_text_reads_the_prose_and_drops_the_rest():
    """What reaches the model is what a reader would see: no tags, no script or
    style *contents* (a stylesheet inside <style> is not prose, and paying to send
    one is paying twice — once for the tokens, once for the worse summary)."""
    html = (
        '<style>.post { color: red }</style>'
        '<script>var x = 1;</script>'
        '<h2>Title</h2><p>First line.</p><p>Second &amp; last.</p>'
    )

    text = summary_mod.plain_text(html)

    assert 'color: red' not in text and 'var x' not in text
    assert 'Title' in text and 'First line.' in text
    assert 'Second & last.' in text  # entities are decoded, as the reader sees them


def test_plain_text_strips_an_unclosed_script_or_style_block():
    """A body truncated mid-<script>, or closed with `</script >`, must not leak
    the script's source into the "prose": the leaked JS inflates the length past
    the min_chars gate, gets billed as the article, and the garbage summary is
    stored with ``summary_model`` set — so it is never redone."""
    truncated = '<p>Intro.</p><script>var tracker = "abc"; loadAds();'
    text = summary_mod.plain_text(truncated)
    assert 'tracker' not in text and 'loadAds' not in text
    assert 'Intro.' in text

    spaced_closer = '<p>Intro.</p><script>secretPayload();</script ><p>After.</p>'
    text = summary_mod.plain_text(spaced_closer)
    assert 'secretPayload' not in text
    assert 'Intro.' in text and 'After.' in text

    open_style = '<p>Intro.</p><style>.a { color: red }'
    text = summary_mod.plain_text(open_style)
    assert 'color: red' not in text
    assert 'Intro.' in text


def test_plain_text_strips_noise_in_linear_time():
    """A page full of unclosed ``<script`` openers must not take quadratic time.

    Regression, 2026-08-23. The old rule was one regex per opener —
    ``<(script|style)\\b.*?</\\1\\s*>`` — and an opener with no closer makes the
    engine scan to the end of the document *from every candidate position*.
    Measured: 64KB = 0.37s, 256KB = 6.6s, 1MB = 97s, which puts production's
    largest archived entry (7.1MB) past an hour. Harmless while this only ran on
    summary candidates; not harmless once ``text.excerpt`` runs it at every ingest
    and over the whole archive in the v16 backfill.

    Lives beside the other ``plain_text`` tests rather than with the excerpt's:
    one home for what this function does is worth more than filing by module.
    """
    body = '<p>a</p><script src="x">' * (256 * 1024 // 24)
    start = time.perf_counter()
    text = summary_mod.plain_text(body)
    elapsed = time.perf_counter() - start

    # The bound is deliberately loose (measured ~4ms after the fix, 6.6s before):
    # this test is about the exponent, not about milliseconds on any given machine.
    assert elapsed < 1.0, f'plain_text took {elapsed:.1f}s on 256KB — the quadratic path is back'
    # ...and it still does the job: everything from the first unclosed opener on is gone
    assert text == 'a'


def test_plain_text_survives_nothing():
    assert summary_mod.plain_text(None) == ''
    assert summary_mod.plain_text('') == ''


# --- status -------------------------------------------------------------------


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def test_status_reports_the_summary_backlog(summary_env, monkeypatch):
    """Fence 4 (plan §3): the spend has to be visible. "Nothing is summarized" and
    "nothing needs summarizing" look identical from the timeline."""
    settings = configure(monkeypatch, CONDENSER_SUMMARY_BATCH=1)
    seed_entry('waiting', minutes=1)
    seed_entry('done', minutes=2)  # newest first, so one round leaves one behind
    seed_entry('short', content=body(20), minutes=3)
    run(settings, FakeSummarizer())

    with _client() as client:
        _login(client)
        st = client.get('/api/rss/status').json()['summary']

    assert st['enabled'] is True
    assert st['model'] == summary_mod.model_tag(settings)
    assert st['done'] == 1
    assert st['pending'] == 1  # the short one is not pending, it is decided
    assert st['failed'] == 0


def test_status_says_when_summaries_are_off(summary_env, monkeypatch):
    configure(monkeypatch, CONDENSER_SUMMARY_API_KEY='')
    seed_entry('a')

    with _client() as client:
        _login(client)
        st = client.get('/api/rss/status').json()['summary']

    assert st['enabled'] is False
    assert st['pending'] == 1  # what it *would* summarize, so the switch has a number


# --- wiring -------------------------------------------------------------------


def test_a_poll_round_summarizes_what_it_ingested(summary_env, monkeypatch):
    """The pipeline hangs off the tail of a polling round rather than owning a loop
    of its own (plan §3): RSS content only arrives with a round, so there is nothing
    for a second timer to discover."""
    from condenser.rss import RssManager

    settings = configure(monkeypatch)
    xml = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>A</title>'
        '<link>https://a.example.com/</link><item><title>Fresh</title>'
        f'<link>https://a.example.com/1</link><description>{"word " * 100}</description>'
        '</item></channel></rss>'
    ).encode()

    async def fetch(url, etag=None, last_modified=None):
        from condenser.rss import FetchResult

        return FetchResult(status=200, body=xml)

    fake = FakeSummarizer()
    mgr = RssManager(settings, fetch_feed=fetch, summarize=fake)
    mgr._now = lambda: T0 + timedelta(minutes=30)

    asyncio.run(mgr.poll_once())

    assert [title for title, _ in fake.calls] == ['Fresh']
    assert db.RssEntry.get(db.RssEntry.guid == 'https://a.example.com/1').summary is not None
    assert mgr.status()['last_round']['summarized'] == 1


def test_a_summary_failure_does_not_sink_the_polling_round(summary_env, monkeypatch):
    """Fetching is the source's job; summarizing is an extra. A pipeline that threw
    (a provider returning something unexpected, say) must not cost the round its
    ingest — the entries are already archived by then."""
    from condenser.rss import RssManager

    settings = configure(monkeypatch)

    async def boom(title, text):
        raise RuntimeError('unexpected')

    async def fetch(url, etag=None, last_modified=None):
        from condenser.rss import FetchResult

        return FetchResult(status=200, body=b'<rss version="2.0"><channel><title>A</title></channel></rss>')

    mgr = RssManager(settings, fetch_feed=fetch, summarize=boom)
    mgr._now = lambda: T0
    seed_entry('a')

    asyncio.run(mgr.poll_once())

    assert db.get_meta('rss_last_poll_at')  # the round still completed


# --- the real HTTP path -------------------------------------------------------
# Everything above injects the summariser. Phase 1's live run proved what that
# leaves uncovered (httpx treats 304 as a redirect and raise_for_status() raised on
# the most common outcome of a healthy round), so the request itself gets a
# transport-level test — including the two failure kinds, which are the whole
# difference between "burn a retry" and "come back later".


def _mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_a_round_with_nothing_injected_reaches_the_provider(summary_env, monkeypatch):
    """The path production actually takes: ``run_round`` with no summariser handed
    to it, building its own client.

    Every other test here injects, which is what let a real bug ship for one live
    run — inside ``run_round`` the ``summarize`` parameter shadowed the module
    function of the same name, so the round called its own empty injection slot and
    every entry died on ``'NoneType' object is not callable``. Nothing that injects
    a summariser can see that, by construction.
    """
    settings = configure(monkeypatch)
    entry = seed_entry('a')
    seen: list = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': '真实路径。'}}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        summary_mod.httpx,
        'AsyncClient',
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    stats = asyncio.run(summary_mod.run_round(settings))

    assert len(seen) == 1
    assert stats['summarized'] == 1
    assert reload_entry(entry).summary == '真实路径。'


def test_the_real_request_carries_the_prompt_and_the_article(summary_env, monkeypatch):
    settings = configure(monkeypatch, CONDENSER_SUMMARY_MODEL='qwen3.7-flash')
    seen: list = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': '  摘要：一段中文。 '}}]})

    text = asyncio.run(summary_mod.summarize_entry('T', 'body text', settings, client=_mock_client(handler)))

    assert text == '一段中文。'  # the label the model insists on prefixing is not the summary
    payload = json.loads(seen[0].content)
    assert payload['model'] == 'qwen3.7-flash'
    assert payload['messages'][0]['role'] == 'system'
    assert 'T' in payload['messages'][1]['content'] and 'body text' in payload['messages'][1]['content']
    assert seen[0].headers['authorization'] == 'Bearer test-key'


def test_thinking_is_turned_off_and_can_be_turned_back_on(summary_env, monkeypatch):
    """A thinking model bills its reasoning as output and ``max_tokens`` does not
    bound it — measured at 1274 reasoning tokens against 99 tokens of summary, for
    an answer no better (tmp/2026-08-22-rss-phase3/probe_thinking.py). The field is
    DashScope's, though, so a strict OpenAI-compatible endpoint gets to opt out."""
    seen: list = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '一段中文。'}}]})

    settings = configure(monkeypatch)
    asyncio.run(summary_mod.summarize_entry('T', 'body', settings, client=_mock_client(handler)))
    assert seen[-1]['enable_thinking'] is False

    settings = configure(monkeypatch, CONDENSER_SUMMARY_DISABLE_THINKING='false')
    asyncio.run(summary_mod.summarize_entry('T', 'body', settings, client=_mock_client(handler)))
    assert 'enable_thinking' not in seen[-1]


def test_a_server_error_is_the_provider_being_down(summary_env, monkeypatch):
    settings = configure(monkeypatch)

    with pytest.raises(summary_mod.ProviderUnavailable):
        asyncio.run(
            summary_mod.summarize_entry('T', 'body', settings, client=_mock_client(lambda r: httpx.Response(503)))
        )


def test_a_rejected_request_is_this_entry_failing(summary_env, monkeypatch):
    """A 400 is about what we sent — this article — so it counts against this
    article's three attempts. A 503 is about the provider and counts against
    nothing."""
    settings = configure(monkeypatch)

    with pytest.raises(summary_mod.SummaryError):
        asyncio.run(
            summary_mod.summarize_entry('T', 'body', settings, client=_mock_client(lambda r: httpx.Response(400)))
        )


def test_an_empty_answer_is_a_failure_not_a_summary(summary_env, monkeypatch):
    """Storing '' would mark the entry summarized forever and leave the card with a
    blank body — worse than never having tried."""
    settings = configure(monkeypatch)

    def handler(request):
        return httpx.Response(200, json={'choices': [{'message': {'content': '   '}}]})

    with pytest.raises(summary_mod.SummaryError):
        asyncio.run(summary_mod.summarize_entry('T', 'body', settings, client=_mock_client(handler)))
