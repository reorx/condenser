"""Keyword matching behavior: boundaries, widening and original-text offsets."""

import os

import pytest
from telememo import db as tdb

from condenser import db, filters
from tests.conftest import md, seed_channel, seed_messages


@pytest.mark.parametrize('pattern,text,expected', [
    ('arc', '我觉得arc是垃圾', True), ('arc', '拥抱 AI 的 Arc 浏览器', True),
    ('arc', 'arc.net #arc arc_browser', True), ('arc', 'archive quietsearch ARChive', False),
    ('arc浏览器', '用arc浏览器', True), ('arc浏览器', 'search浏览器', False),
    ('#ad', '这条是 #ad', True), ('#ad', '#adverts', False),
    ('c++', '学 c++ 的', True), ('c++', 'abc++', False),
    ('iPhone 15', 'iPhone 15 Pro', True), ('iPhone 15', 'iPhone 150', False),
    ('zhihu.com', 'www.zhihu.com/question', True),
    ('起床时间', '今天的起床时间是', True), ('中文', '中文版', True), ('中文', '其中文件', True),
    ('삼성', '삼성은', True), ('日本', '日本語', True),
    ('arc*', 'archives', True), ('arc*', 'quietsearch', False),
    ('*gpt', 'ChatGPT', True), ('*gpt', 'GPTs', False), ('*arc*', 'quietsearch', True),
    ('*中文*', '其中文件', True), ('a*b', 'a*b', True), ('a*b', 'axb', False),
    ('AD', '广告ad促销', True), ('ad', 'https://x/%E8%B3%AD', False),
    ('ad', '%ADad%20', True), ('open ai', 'open  AI\n', True), ('open ai', 'open\nAI', True),
    ('arc', 'éarc arc9', False), ('arc', '😀arc😀', True),
    ('arc', None, False), ('arc', '', False),
])
def test_rule_matching(pattern, text, expected):
    assert filters.text_is_filtered(text, filters.compile_rules([pattern])) is expected


@pytest.mark.parametrize('pattern,expected', [
    ('', None), ('  ', None), ('*', None), ('**', None), (' *  * ', None),
    (' arc ', ('arc', False, False)), ('**arc*', ('arc', True, True)),
    ('a*b', ('a*b', False, False)),
])
def test_parse_rule(pattern, expected):
    assert filters.parse_rule(pattern) == expected


def test_invalid_legacy_rules_are_skipped():
    assert filters.compile_rules(['*', ' ']) is None
    assert not filters.text_is_filtered('anything', None)
    assert filters.text_is_filtered('Arc', filters.compile_rules(['*', 'arc']))


def test_match_spans_preserve_codepoint_offsets():
    text = '😀İ arc archive %AD ad'
    assert filters.match_spans(text, filters.compile_rules(['arc', 'ad'])) == [(3, 6), (19, 21)]
    assert filters.match_spans(None, None) == []
    assert len(filters.prepare(text)) == len(text)


@pytest.mark.parametrize('text,core,start,end,expected', [
    ('archives', 'arc', False, False, ('archives', 'arc*')),
    ('ChatGPT', 'gpt', False, False, ('ChatGPT', '*gpt')),
    ('quietsearch', 'arc', False, False, ('quietsearch', '*arc*')),
    ('xarchives', 'arc', False, True, ('xarchives', '*arc*')),
    ('ChatGPTs', 'gpt', True, False, ('ChatGPTs', '*gpt*')),
    ('%AD', 'ad', False, False, None),
])
def test_near_miss_example(text, core, start, end, expected):
    assert filters.near_miss_example(text, core, start, end) == expected


def test_ensure_materialized_clears_stale_flags_and_records_version(env, monkeypatch):
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    seed_channel(1, 'Paused')
    seed_messages([md(1, 1, 1, text='archive'), md(1, 2, 2, text='Arc')])
    db.add_filter(None, 'arc')
    tdb.db.execute_sql('UPDATE messages SET is_filtered = 1')
    db.AppMeta.delete().where(db.AppMeta.key == filters.MATCHER_META_KEY).execute()
    filters.ensure_materialized()
    assert tdb.db.execute_sql('SELECT is_filtered FROM messages ORDER BY id').fetchall() == [(0,), (1,)]
    assert db.get_meta(filters.MATCHER_META_KEY) == str(filters.MATCHER_VERSION)
    monkeypatch.setattr(filters, 'recompute_channel', lambda cid: pytest.fail('rebuilt unchanged version'))
    db.init_db(os.environ['CONDENSER_DB_PATH'])


def test_global_rule_changes_recompute_paused_and_unsubscribed_channels(env):
    db.init_db(os.environ['CONDENSER_DB_PATH'])
    for cid in (1, 2):
        seed_channel(cid, 'Channel')
        seed_messages([md(cid, 1, 1, text='Arc')])
    db.add_subscription(1)
    db.set_subscription_enabled(1, False)
    rule = db.add_filter(None, 'arc')
    filters.recompute_for_rule_change(None)
    assert tdb.db.execute_sql('SELECT sum(is_filtered) FROM messages').fetchone()[0] == 2
    db.delete_filter(rule.id)
    filters.recompute_for_rule_change(None)
    assert tdb.db.execute_sql('SELECT sum(is_filtered) FROM messages').fetchone()[0] == 0
