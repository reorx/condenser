"""Behavior tests for full-text search (plan kb/plans/2026-08-08-full-text-search.md).

The load-bearing decision here is that tokenization happens in **Python**, before
the text reaches FTS5: a Chinese two-character word ("模型", "编程") is shorter
than the built-in ``trigram`` tokenizer's three-character minimum, and the C++
``simple`` extension would mean shipping compiled binaries for two architectures.
So a CJK run is indexed as its character bigrams and queried as a *phrase* over
them, which makes matching mean substring — the same semantics, zero dependencies.

These tests pin that equivalence from both ends: what the tokenizer emits, and
what actually comes back out of a real FTS5 table.
"""

import asyncio
import os
import sqlite3
from datetime import timedelta

import pytest

from condenser import db, search, x
from condenser.items import ItemKey
from tests.conftest import BASE, md, seed_channel, seed_messages


def _init():
    db.init_db(os.environ['CONDENSER_DB_PATH'])


def _find(query, **kw):
    """Search by a raw user query string; returns item keys, newest first."""
    match = search.build_match(query)
    assert match is not None, f'{query!r} produced no searchable token'
    rows, _total = search.search(match, **kw)
    return [ItemKey(source=r['source'], ref1=r['ref1'], ref2=r['ref2']).key for r in rows]


def _seed_indexed(*items):
    """(source, ref1, ref2, text, minutes) -> one search_index row each."""
    for source, ref1, ref2, text, minutes in items:
        search.index_item(source, ref1, ref2, text, BASE + timedelta(minutes=minutes))


def _seed_x_tweet(tweet_id, text, feed='foryou', minutes=0, **over):
    stamp = (BASE + timedelta(minutes=minutes)).replace(tzinfo=None)
    fields = {
        'id': tweet_id,
        'author_handle': 'someone',
        'author_name': 'Some One',
        'text': text,
        'created_at': stamp,
        'fetched_at': stamp,
    }
    fields.update(over)
    db.upsert_x_tweet(fields)
    if feed:
        db.insert_x_feed_items([{'channel_id': feed, 'tweet_id': tweet_id, 'first_seen_at': stamp}])


# --- tokenizer ---------------------------------------------------------------


def test_tokenize_cjk_run_becomes_character_bigrams():
    """A CJK run is indexed as overlapping character bigrams — the unit that makes
    a two-character word findable at all — plus the run's final character, which is
    what a single-character *prefix* query needs to reach it (see the end-of-run
    test below). The query side gets the bigrams only."""
    assert search.tokenize('中文搜索') == ['中文', '文搜', '搜索', '索']
    assert search.build_match('中文搜索') == '"中文 文搜 搜索"'
    # a lone character has no bigram to make, so it is its own token
    assert search.tokenize('猫') == ['猫']


def test_tokenize_keeps_latin_words_whole_and_lowercased():
    assert search.tokenize('Hello WORLD') == ['hello', 'world']
    # digits and non-ASCII letters are words too — an index that dropped Cyrillic
    # or accents would silently lose whole channels
    assert search.tokenize('GPT-4 café Привет') == ['gpt', '4', 'café', 'привет']


def test_tokenize_emits_document_order_so_bigrams_cannot_span_runs():
    """Tokens stay in reading order, which is what keeps the phrase query honest:
    「中文」and「搜索」separated by other text must not answer「中文搜索」."""
    assert search.tokenize('中文abc搜索') == ['中文', '文', 'abc', '搜索', '索']


def test_tokenize_keeps_everything_a_reader_might_search_for():
    """Unlike ngram.py's tokenizer — which serves a classifier and deliberately
    throws away URLs, mentions and stopwords — this one serves recall."""
    tokens = search.tokenize('the link https://example.com/x by @novoreorx')
    assert {'the', 'example', 'com', 'novoreorx'} <= set(tokens)


def test_tokenize_ignores_punctuation_and_emoji():
    assert search.tokenize('!!! 🧵 ,.') == []


# --- query construction ------------------------------------------------------


def test_build_match_uses_a_phrase_for_a_cjk_word():
    """Position continuity is what turns bigrams back into substring semantics."""
    assert search.build_match('中文搜索') == '"中文 文搜 搜索"'


def test_build_match_uses_a_prefix_query_for_a_single_cjk_character():
    """One character has no bigram of its own, so it matches every bigram that
    starts with it — no separate unigram index needed."""
    assert search.build_match('猫') == '"猫" *'


def test_build_match_ands_the_groups():
    assert search.build_match('AI 模型') == '"ai" "模型"'


def test_build_match_returns_none_when_nothing_is_searchable():
    for empty in ('', '   ', '!!!', '🧵'):
        assert search.build_match(empty) is None


def test_fts5_syntax_in_a_query_is_content_not_syntax(env):
    """Quoting every token is what makes FTS5 read `AND` / `*` / `"` as words.
    Unquoted, the first would silently change the query and the last two would
    raise — from a search box that is one keystroke away at all times."""
    _init()
    _seed_indexed(
        ('hn', 1, 0, 'cats and dogs', 0),
        ('hn', 2, 0, 'cats', 1),
        ('hn', 3, 0, 'cats or dogs', 2),
    )
    # the operator words have to be *in* the document, i.e. they are content
    assert _find('cats AND dogs') == ['hn:1']
    assert _find('cats OR dogs') == ['hn:3']
    # and the syntax characters neither widen the query nor raise
    assert _find('cats"') == ['hn:3', 'hn:2', 'hn:1']
    assert _find('cats*') == ['hn:3', 'hn:2', 'hn:1']


# --- index round trip --------------------------------------------------------


def test_search_finds_a_two_character_chinese_word(env):
    """The whole reason for the Python tokenizer: trigram cannot answer this."""
    _init()
    _seed_indexed(
        ('telegram', 100, 1, '这是一篇关于模型训练的文章', 0),
        ('telegram', 100, 2, '今天天气不错', 1),
    )
    assert _find('模型') == ['tg:100:1']


def test_search_matches_across_word_boundaries_like_a_substring(env):
    """Bigrams give substring semantics, noise included: 「中文」finds「其中文件」.
    A property of a character-level index, not a defect — and the reason the
    fallback in the plan's non-goals is a real segmenter, not a threshold."""
    _init()
    _seed_indexed(('telegram', 100, 1, '其中文件很多', 0))
    assert _find('中文') == ['tg:100:1']


def test_search_single_character_matches_inside_a_word(env):
    _init()
    _seed_indexed(('telegram', 100, 1, '我的猫咪很可爱', 0))
    assert _find('猫') == ['tg:100:1']


def test_a_cjk_word_matches_mid_run_not_only_at_the_end(env):
    """The regression the index/query asymmetry exists for: if the trailing unigram
    leaked into `build_match`, 「中文搜索」 would become the phrase
    ``"中文 文搜 搜索 索"`` and only match text whose run *ends* there — so this
    document, where the word is followed by more characters, would stop matching."""
    _init()
    _seed_indexed(('telegram', 100, 1, '中文搜索工具', 0))
    assert _find('中文搜索') == ['tg:100:1']


def test_search_single_character_matches_at_the_end_of_a_run(env):
    """A prefix query only reaches bigrams that *start* with the character, so a
    character sitting last in its run had no token to match at all — 「猫」 could
    not find 「我买了一只猫」. That is why a run emits its final character as a
    token of its own; without it the prefix rule has a hole exactly where a
    sentence ends."""
    _init()
    _seed_indexed(('telegram', 100, 1, '我买了一只猫', 0))
    assert search.tokenize('一只猫')[-1] == '猫'
    assert _find('猫') == ['tg:100:1']


def test_search_is_case_insensitive_and_handles_mixed_scripts(env):
    _init()
    _seed_indexed(('hn', 1, 0, 'Rust 编程语言 tutorial', 0))
    assert _find('rust') == ['hn:1']
    assert _find('编程') == ['hn:1']
    assert _find('RUST 编程') == ['hn:1']


def test_search_requires_every_group_to_match(env):
    _init()
    _seed_indexed(
        ('hn', 1, 0, 'rust 编程', 0),
        ('hn', 2, 0, 'rust only', 1),
    )
    assert _find('rust 编程') == ['hn:1']


def test_reindexing_replaces_the_previous_text(env):
    """A Telegram edit re-dispatches the whole display unit, so an upsert has to
    make the old text unfindable — otherwise every edit leaves a ghost."""
    _init()
    _seed_indexed(('telegram', 100, 1, '原始内容', 0))
    assert _find('原始') == ['tg:100:1']
    _seed_indexed(('telegram', 100, 1, '修改后的内容', 0))
    assert _find('原始') == []
    assert _find('修改') == ['tg:100:1']


def test_indexing_empty_text_removes_the_row(env):
    """An edit that strips a caption (or a media-only message) has nothing to
    search — the row goes away rather than lingering as an empty document."""
    _init()
    _seed_indexed(('telegram', 100, 1, '有内容', 0))
    _seed_indexed(('telegram', 100, 1, '', 0))
    assert _find('有内容') == []
    _seed_indexed(('telegram', 100, 2, None, 0))
    assert search.count() == 0


def test_search_sorts_by_time_or_relevance(env):
    _init()
    _seed_indexed(
        ('hn', 1, 0, 'rust', 0),
        ('hn', 2, 0, 'rust rust rust and more rust', 10),
        ('hn', 3, 0, 'a very long document about rust and many other unrelated words ' * 5, 5),
    )
    assert _find('rust', sort='recent') == ['hn:2', 'hn:3', 'hn:1']
    # bm25 favours the short, dense document over the long, diluted one
    by_rank = _find('rust', sort='relevance')
    assert by_rank[-1] == 'hn:3'


def test_search_paginates_and_reports_the_total(env):
    _init()
    _seed_indexed(*[('hn', i, 0, 'rust', i) for i in range(1, 8)])
    match = search.build_match('rust')
    rows, total = search.search(match, limit=3)
    assert total == 7 and len(rows) == 3
    rows, total = search.search(match, offset=6, limit=3)
    assert total == 7 and len(rows) == 1


# --- rebuild + upgrade -------------------------------------------------------


def test_rebuild_is_idempotent_and_covers_every_source(env):
    _init()
    seed_channel(100, 'Chan')
    seed_messages([md(100, 1, 0, text='关于模型的文章'), md(100, 2, 1, text='hello world')])
    db.insert_hn_story(
        id=500, title='Rust is fast', text=None, first_seen_at=BASE.replace(tzinfo=None), day=str(BASE.date())
    )
    _seed_x_tweet(9001, '推特上的模型讨论')

    first = search.rebuild()
    assert first == {'telegram': 2, 'hn': 1, 'x': 1}
    assert search.rebuild() == first
    assert sorted(_find('模型')) == ['tg:100:1', 'x:9001']
    assert _find('rust') == ['hn:500']


def test_rebuild_indexes_an_album_once_under_its_display_anchor(env):
    """An album is one item, so it gets one index row — keyed by the anchor the
    rest of the app already calls it by (the lowest id), carrying the caption
    whichever sibling happens to hold it."""
    _init()
    seed_channel(100, 'Chan')
    seed_messages(
        [
            md(100, 10, 0, text=None, grouped_id=777),
            md(100, 11, 0, text=None, grouped_id=777),
            md(100, 12, 0, text='相册的说明文字', grouped_id=777),
        ]
    )
    assert search.rebuild()['telegram'] == 1
    assert _find('说明') == ['tg:100:10']


def test_rebuild_skips_a_tweet_that_never_appeared_in_a_feed(env):
    """A quoted tweet's body is archived but is not a timeline item, so it is not
    a search result either — otherwise a hit would open onto nothing."""
    _init()
    _seed_x_tweet(9001, '被引用的推文内容', feed=None)
    assert search.rebuild()['x'] == 0
    assert search.build_match('引用') and _find('引用') == []


def test_upgrade_from_v11_backfills_the_index(env):
    """A pre-search database has messages but no index; the upgrade rebuilds it
    rather than migrating anything — the text is all still in the source tables."""
    path = os.environ['CONDENSER_DB_PATH']
    _init()
    seed_channel(100, 'Chan')
    seed_messages([md(100, 1, 0, text='关于模型的文章')])
    # rewind to a v11 database: no index table, no version marker
    db.close_db()
    conn = sqlite3.connect(path)
    conn.execute('DROP TABLE IF EXISTS search_index')
    conn.execute("DELETE FROM app_meta WHERE key = 'search_index_version'")
    conn.execute("UPDATE app_meta SET value = '11' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    _init()
    assert db.get_meta('schema_version') == str(db.SCHEMA_VERSION) == '14'
    assert _find('模型') == ['tg:100:1']


def test_tokenizer_version_change_forces_a_rebuild(env):
    """The ``model_tag`` contract, simplified to one integer: a tokenizer edit
    invalidates every stored row, and the answer is to re-read the sources."""
    _init()
    seed_channel(100, 'Chan')
    seed_messages([md(100, 1, 0, text='关于模型的文章')])
    search.rebuild()
    db.set_meta(search.VERSION_META_KEY, '0')
    db.close_db()

    _init()
    assert db.get_meta(search.VERSION_META_KEY) == str(search.TOKENIZER_VERSION)
    assert _find('模型') == ['tg:100:1']


def test_a_ready_index_is_not_rebuilt_on_every_startup(env, monkeypatch):
    """Rebuilding reads every message, story and tweet — at production size that
    is seconds of startup, and it must not be the price of a restart."""
    _init()
    seed_channel(100, 'Chan')
    seed_messages([md(100, 1, 0, text='关于模型的文章')])
    search.rebuild()
    db.close_db()

    monkeypatch.setattr(search, 'rebuild', lambda: pytest.fail('rebuilt a healthy index'))
    _init()
    assert _find('模型') == ['tg:100:1']


# --- write paths --------------------------------------------------------------
# The index is materialized on the write side, exactly like `messages.is_filtered`:
# every path that stores an item has to index it, or the item is simply missing
# from search until the next rebuild — a silent failure, which is why each of the
# four ingest paths gets its own test.


def test_telegram_realtime_ingest_indexes_the_message(env):
    from telememo.types import DisplayMessage

    _init()
    seed_channel(100, 'Chan')
    tg = _tg_manager()
    seed_messages([md(100, 1, 0, text='关于模型的文章')])
    asyncio.run(tg._on_new_message(DisplayMessage(id=1, channel_id=100, date=BASE, text='关于模型的文章')))
    assert _find('模型') == ['tg:100:1']


def test_realtime_album_is_indexed_once_under_its_anchor(env):
    """The realtime handler dispatches **one raw message at a time** — telememo's
    `_handle_new_message` groups a single row, so `dm.id` is a sibling id, not the
    album's anchor. Trusting it indexed an album once per photo and, on an edit,
    added a row beside the stale one instead of replacing it."""
    from telememo.types import DisplayMessage

    _init()
    seed_channel(100, 'Chan')
    seed_messages(
        [
            md(100, 10, 0, text=None, grouped_id=777),
            md(100, 11, 0, text=None, grouped_id=777),
            md(100, 12, 0, text='相册的模型说明', grouped_id=777),
        ]
    )
    tg = _tg_manager()
    for mid in (10, 11, 12):
        row = _message_row(100, mid)
        asyncio.run(tg._on_new_message(DisplayMessage(id=mid, channel_id=100, date=BASE, text=row['text'])))

    assert _find('模型') == ['tg:100:10']
    assert search.count() == 1


def test_realtime_album_caption_edit_replaces_the_old_text(env):
    """The same defect's second half: an edit arriving for a sibling must upsert
    the unit's one row, not add a second one that keeps the old text findable."""
    from telememo.types import DisplayMessage

    _init()
    seed_channel(100, 'Chan')
    seed_messages([md(100, 10, 0, text=None, grouped_id=777), md(100, 12, 0, text='原始的说明', grouped_id=777)])
    tg = _tg_manager()
    asyncio.run(tg._on_new_message(DisplayMessage(id=12, channel_id=100, date=BASE, text='原始的说明')))
    assert _find('原始') == ['tg:100:10']

    db.tdb.db.execute_sql('UPDATE messages SET text = ? WHERE channel_id = 100 AND id = 12', ('修改的说明',))
    asyncio.run(tg._on_new_message(DisplayMessage(id=12, channel_id=100, date=BASE, text='修改的说明')))
    assert _find('原始') == []
    assert _find('修改') == ['tg:100:10']
    assert search.count() == 1


def test_telegram_edit_makes_the_old_text_unfindable(env):
    """telememo dispatches an edit through the same handler, so the upsert is the
    whole edit story — there is no separate re-index path to forget.

    ``save_message_smart`` updates the row *before* dispatching, which is why the
    seed is rewritten here too: the hook reads the stored unit, not the event."""
    from telememo.types import DisplayMessage

    _init()
    seed_channel(100, 'Chan')
    seed_messages([md(100, 1, 0, text='原始的内容')])
    tg = _tg_manager()
    asyncio.run(tg._on_new_message(DisplayMessage(id=1, channel_id=100, date=BASE, text='原始的内容')))
    assert _find('原始') == ['tg:100:1']

    db.tdb.db.execute_sql('UPDATE messages SET text = ? WHERE channel_id = 100 AND id = 1', ('修改的内容',))
    asyncio.run(tg._on_new_message(DisplayMessage(id=1, channel_id=100, date=BASE, text='修改的内容')))
    assert _find('原始') == []
    assert _find('修改') == ['tg:100:1']


def test_telegram_backfill_indexes_what_it_stores(env):
    from telememo.types import DisplayMessage

    _init()
    seed_channel(100, 'Chan')
    db.add_subscription(100)
    tg = _tg_manager()

    async def fake_backfill(channel, since_days=None, since_date=None, persist=True):
        seed_messages([md(100, 60, 1, text='历史里的模型讨论')])
        yield DisplayMessage(id=60, channel_id=100, date=BASE, text='历史里的模型讨论', raw_message_ids=[60])

    tg.service.backfill = fake_backfill
    asyncio.run(tg._backfill_channel(100))
    assert _find('模型') == ['tg:100:60']


def test_hn_sampling_indexes_title_and_self_post_body(env):
    """A self-post's body is an HTML fragment; the reader searches the words in it,
    not the markup."""
    _init()
    db.insert_hn_story(
        id=500,
        title='Ask HN: anything',
        text='<p>we use <a href="https://x">rust</a> &amp; 编程</p>',
        first_seen_at=BASE.replace(tzinfo=None),
        day=str(BASE.date()),
    )
    search.rebuild()
    assert _find('rust') == ['hn:500']
    assert _find('编程') == ['hn:500']
    assert _find('href') == []  # markup is not content


def test_x_ingest_indexes_a_pushed_tweet(env):
    _init()
    db.add_x_subscription('foryou', name='X For You', config={'kind': 'home'})
    x.ingest_tweets('foryou', [_x_entry(9001, '关于模型的推文')])
    assert _find('模型') == ['x:9001']


def test_x_expanded_urls_are_searchable(env):
    """The card shows the original link (v13 urls), so search must match it — the
    text alone holds only the t.co, and 「haotianzheng」 would find nothing."""
    _init()
    db.add_x_subscription('foryou', name='X For You', config={'kind': 'home'})
    entry = _x_entry(9001, 'https://t.co/qzYxwreb9x')
    entry['urls'] = [
        {
            'url': 'https://t.co/qzYxwreb9x',
            'expandedUrl': 'https://haotianzheng.com/?t=202607291001',
            'displayUrl': 'haotianzheng.com/?t=202607291001',
        }
    ]
    x.ingest_tweets('foryou', [entry])
    assert _find('haotianzheng') == ['x:9001']
    # and the rebuild path reads the same column (TOKENIZER_VERSION bump replays it)
    search.rebuild()
    assert _find('haotianzheng') == ['x:9001']


def test_x_quoted_tweet_urls_are_searchable(env):
    """The quote renders inside the card, links included — same rule as its text."""
    _init()
    db.add_x_subscription('foryou', name='X For You', config={'kind': 'home'})
    entry = _x_entry(9001, 'quoting this')
    entry['quotedTweet'] = {
        'id': '9002',
        'text': 'see https://t.co/q',
        'author': {'username': 'bob', 'name': 'Bob'},
        'urls': [{'url': 'https://t.co/q', 'expandedUrl': 'https://quoted-domain.example/deep'}],
    }
    x.ingest_tweets('foryou', [entry])
    assert _find('quoted-domain') == ['x:9001']


def test_x_ingest_does_not_index_a_body_without_a_feed_row(env):
    """Following's out-of-window thread ancestors are archived but given no feed
    row — they are not cards, so a search hit on one would open onto nothing."""
    _init()
    db.add_x_subscription('following', name='X Following', config={'kind': 'following'})
    db.replace_x_following([{'handle': 'someone', 'user_id': '1', 'name': 'Some One'}], BASE.replace(tzinfo=None))
    old = _x_entry(9002, '一条很旧的祖先推文', created_at='Mon Jan 05 10:00:00 +0000 2026')
    result = x.ingest_tweets('following', [old])
    assert result.filtered_old == 1
    assert db.get_x_tweet(9002) is not None  # the body is archived
    assert _find('祖先') == []  # but it is not a search result


# --- deletion cascade ---------------------------------------------------------


def test_x_retention_sweep_drops_search_rows_it_deleted(env):
    """15-day retention deletes what nobody touched; search coverage follows it
    exactly — recent history plus everything read, labeled, hidden or saved."""
    _init()
    _seed_x_tweet(9001, '旧的未读推文', minutes=0)
    _seed_x_tweet(9002, '旧的已读推文', minutes=0)
    search.rebuild()
    db.mark_read([ItemKey(source='x', ref1=9002)])

    counts = db.sweep_x_retention(feed_cutoff=BASE.replace(tzinfo=None) + timedelta(days=1), embedding_cutoff=None)
    assert counts['feed_items'] == 1 and counts['search_orphaned'] == 1
    assert _find('推文') == ['x:9002']


def test_x_sweep_heals_orphans_it_did_not_create(env):
    """An anti-join, not a list of just-deleted ids — so a row orphaned before this
    cascade existed is cleaned up too."""
    _init()
    _seed_x_tweet(9001, '孤儿推文')
    search.rebuild()
    db.tdb.db.execute_sql('DELETE FROM x_feed_items')
    assert search.sweep_x_orphans() == 1
    assert _find('孤儿') == []


def test_a_story_hn_killed_stops_being_findable(env):
    """The timeline's ranking excludes dead stories, so search must not be the one
    surface still offering them."""
    _init()
    db.insert_hn_story(
        id=500, title='Rust is fast', text=None, first_seen_at=BASE.replace(tzinfo=None), day=str(BASE.date())
    )
    search.rebuild()
    db.mark_hn_story_dead(500)
    assert _find('rust') == []
    # and a rebuild must not resurrect it — the delete is a policy, not a one-off
    search.rebuild()
    assert _find('rust') == []


def test_a_story_that_arrives_dead_is_never_indexed(env):
    """Firebase serves flagged submissions that are still sitting in `topstories`
    with `dead: true`. They are stored (the archive is append-only) but they were
    never showable, so they must not become searchable either."""
    _init()
    db.insert_hn_story(
        id=501,
        title='Rust is fast',
        text=None,
        first_seen_at=BASE.replace(tzinfo=None),
        day=str(BASE.date()),
        is_dead=True,
    )
    search.index_hn_story({'id': 501, 'title': 'Rust is fast', 'text': None, 'first_seen_at': BASE, 'is_dead': True})
    assert _find('rust') == []
    assert search.rebuild()['hn'] == 0


def test_channel_purge_drops_only_that_channels_documents(env):
    _init()
    seed_channel(100, 'A')
    seed_channel(200, 'B')
    seed_messages([md(100, 1, 0, text='频道甲的模型'), md(200, 1, 1, text='频道乙的模型')])
    search.rebuild()
    db.delete_channel_messages(100)
    assert _find('模型') == ['tg:200:1']


# --- harness ------------------------------------------------------------------


def _tg_manager():
    """A TgManager with a stub service — enough to drive the ingest hooks."""
    from unittest.mock import AsyncMock, MagicMock

    from condenser.config import get_settings
    from condenser.tg import TgManager

    manager = TgManager(get_settings())
    manager.service = MagicMock(is_authorized=AsyncMock(return_value=True))
    return manager


def _message_row(channel_id, message_id):
    cur = db.tdb.db.execute_sql(
        'SELECT id, text, grouped_id FROM messages WHERE channel_id = ? AND id = ?', (channel_id, message_id)
    )
    columns = [c[0] for c in cur.description]
    return dict(zip(columns, cur.fetchone()))


def _x_entry(tweet_id, text, created_at='Mon Jun 01 12:00:00 +0000 2026'):
    return {
        'id': str(tweet_id),
        'text': text,
        'createdAt': created_at,
        'authorId': '1',
        'author': {'username': 'someone', 'name': 'Some One'},
    }
