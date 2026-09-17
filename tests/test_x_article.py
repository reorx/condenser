"""Behavior tests for X Article full text (plans 2026-09-16 and 2026-09-17).

The timeline queries X serves the probe carry an article's title and a ~200-char
preview, nothing more; only TweetDetail carries the body. The probe reads that
detail the moment it first sees a long-form post and merges the detail's
``article`` block into the tweet it is about to push, so the body arrives through
the ordinary ingest (plan 2026-09-17 — the end-of-round work order it replaced is
gone, and pinned gone below).

What these tests pin is the part that is easy to break later:

* ingest splits the pushed ``article`` block: the card's pair stays in
  ``article``, the body goes to ``article_detail`` — and only a block with an
  actual body earns one;
* a later push without the body (every round's timeline re-read) keeps the stored
  body — ``ParsedTweet.row()`` leaves the column out instead of writing NULL;
* the list payload says *whether* there is a body (``has_content``) and never
  carries it; the body is ``GET /api/x/tweets/{id}``'s, rendered to HTML, with the
  saved snapshot as its fallback once retention takes the row;
* full text is searchable, and the verdict does not read it (it is billed).

Plans: kb/plans/2026-09-16-x-article-full-content.md,
kb/plans/2026-09-17-x-article-inline-fetch.md
"""

import copy
import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from condenser import db, verdict, x
from condenser.app import create_app

FIXTURES = Path(__file__).parent / 'fixtures' / 'x'

NOW = datetime(2026, 9, 16, 12, 0)

DETAIL = json.loads((FIXTURES / 'article_detail.json').read_text())
ARTICLE_ID = int(DETAIL['id'])
TITLE = DETAIL['article']['title']
PREVIEW = DETAIL['article']['previewText']
DETAIL_KEYS = {'content', 'plainText', 'coverMedia', 'media', 'publishedAt', 'modifiedAt'}
# A phrase that is in the body and nowhere in the title or preview.
BODY_ONLY_PHRASE = '明码标价'


@pytest.fixture
def xa_env(env, monkeypatch):
    """Fixed clock via ``x._now``; the startup cleanup round is kept away from the
    fixtures (the retention sweep reads the real clock)."""
    monkeypatch.setenv('CONDENSER_CLEANUP_ENABLED', 'false')
    from condenser.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(x, '_now', lambda: NOW)
    yield monkeypatch


def timeline_tweet(tweet_id=ARTICLE_ID, title=TITLE, preview=PREVIEW):
    """The article tweet as a timeline query returns it: ``text`` is the title and
    the article block is the upstream pair only."""
    return {
        'id': str(tweet_id),
        'text': title,
        'createdAt': 'Tue Sep 15 03:50:01 +0000 2026',
        'author': DETAIL['author'],
        'authorId': DETAIL['authorId'],
        'article': {'title': title, 'previewText': preview},
    }


def article_tweet(tweet_id=ARTICLE_ID, article=None):
    """What the probe pushes once it read the detail: the timeline tweet — its
    ``text`` still the title — with the detail's ``article`` block merged in."""
    tweet = timeline_tweet(tweet_id)
    tweet['article'] = {**tweet['article'], **copy.deepcopy(article or DETAIL['article'])}
    return tweet


def plain_tweet(tweet_id, text='just a tweet'):
    return {
        'id': str(tweet_id),
        'text': text,
        'createdAt': 'Tue Sep 15 03:50:01 +0000 2026',
        'author': DETAIL['author'],
    }


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def _subscribe(client, channel_id='foryou'):
    r = client.post('/api/sources/x/subscriptions', json={'channel_id': channel_id})
    assert r.status_code == 200, r.text


def _ingest(client, monkeypatch, tweets, at=NOW, channel_id='foryou'):
    monkeypatch.setattr(x, '_now', lambda: at)
    r = client.post('/api/sources/x/ingest', json={'channel_id': channel_id, 'tweets': tweets})
    monkeypatch.setattr(x, '_now', lambda: NOW)
    assert r.status_code == 200, r.text
    return r.json()


def _timeline_x(client):
    r = client.get('/api/timeline', params={'source': 'x', 'limit': 50})
    assert r.status_code == 200, r.text
    return {item['x']['id']: item['x'] for item in r.json()['items']}


# --- ingest --------------------------------------------------------------------------


def test_ingest_splits_the_body_off_the_cards_pair(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        result = _ingest(client, xa_env, [article_tweet()])
    assert result['stored'] == 1 and result['parse_errors'] == 0

    row = db.get_x_tweet(ARTICLE_ID)
    stored = json.loads(row.article_detail)
    assert set(stored) == DETAIL_KEYS
    assert stored['content'] == DETAIL['article']['content']
    # the card's two fields are exactly the timeline's — the body is not among them
    assert row.text == TITLE
    assert json.loads(row.article) == {'title': TITLE, 'previewText': PREVIEW}
    # ...while the archive keeps what was pushed, body included (re-parse after drift)
    assert json.loads(row.raw)['article']['content'] == DETAIL['article']['content']


def test_a_repush_without_the_body_keeps_it(xa_env):
    """Every round re-reads the timeline, and a tweet that fell out of the probe's
    cache comes back bodiless; ``upsert_x_tweet`` overwrites only what it is given."""
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [article_tweet()])
        _ingest(client, xa_env, [timeline_tweet()])
    row = db.get_x_tweet(ARTICLE_ID)
    assert json.loads(row.article_detail)['content'] == DETAIL['article']['content']
    assert json.loads(row.article) == {'title': TITLE, 'previewText': PREVIEW}


def test_a_later_push_that_carries_a_body_replaces_the_stored_one(xa_env):
    """An edited article, or a ``run --no-cache`` re-push: the newest body wins."""
    edited = {**DETAIL['article'], 'content': '## 改过了\n\n新的正文', 'plainText': '改过了 新的正文'}
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [article_tweet()])
        _ingest(client, xa_env, [article_tweet(article=edited)])
    assert json.loads(db.get_x_tweet(ARTICLE_ID).article_detail)['content'] == '## 改过了\n\n新的正文'


def test_a_bodiless_detail_block_stores_no_body(xa_env):
    """X answering the detail with an empty body is X's answer, not a body."""
    empty = {**DETAIL['article'], 'content': '  ', 'plainText': ''}
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [article_tweet(article=empty)])
        listed = _timeline_x(client)[str(ARTICLE_ID)]
    row = db.get_x_tweet(ARTICLE_ID)
    assert row.article_detail is None
    # and the detail keys still stay out of the card's pair
    assert json.loads(row.article) == {'title': TITLE, 'previewText': PREVIEW}
    assert listed['article'] == {'title': TITLE, 'previewText': PREVIEW, 'has_content': False}


def test_an_unknown_detail_key_never_reaches_the_list(xa_env):
    """``split_article`` keeps an allowlist, not a denylist (review 2026-09-17
    finding 8): the card's pair is all ``article`` ever holds, so a body-ish key
    xbird adds later (``contentState``, say) lands in the body, not the list."""
    grown = {**DETAIL['article'], 'contentState': {'blocks': ['...']}}
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [article_tweet(article=grown)])
        listed = _timeline_x(client)[str(ARTICLE_ID)]
    row = db.get_x_tweet(ARTICLE_ID)
    assert json.loads(row.article) == {'title': TITLE, 'previewText': PREVIEW}
    assert listed['article'] == {'title': TITLE, 'previewText': PREVIEW, 'has_content': True}
    assert json.loads(row.article_detail)['contentState'] == {'blocks': ['...']}


def test_split_article_keeps_only_the_cards_pair():
    assert x.split_article({'title': 't', 'previewText': 'p', 'contentState': 'x'}) == ({'title': 't', 'previewText': 'p'}, None)
    assert x.split_article({'title': 't', 'content': 'body', 'extra': 1}) == ({'title': 't'}, {'content': 'body', 'extra': 1})
    assert x.split_article({'previewText': 'p', 'content': None}) == ({'previewText': 'p'}, None)
    assert x.split_article({}) == ({}, None)
    assert x.split_article('nope') == (None, None)


def test_the_work_order_endpoints_are_gone(xa_env):
    """Plan 2026-09-17 replaced the end-of-round work order with the inline read."""
    with _client() as client:
        _login(client)
        assert client.get('/api/sources/x/articles/pending').status_code == 404
        # 405 when a built frontend is present: the SPA mount at / takes the unrouted
        # POST and refuses the method — either way no handler is left behind it
        assert client.post('/api/sources/x/articles', json={'articles': []}).status_code in (404, 405)


def test_the_full_text_becomes_searchable(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        before = client.get('/api/search', params={'q': BODY_ONLY_PHRASE}).json()
        _ingest(client, xa_env, [article_tweet()])
        after = client.get('/api/search', params={'q': BODY_ONLY_PHRASE}).json()
    assert before['items'] == []
    assert [item['key'] for item in after['items']] == [f'x:{ARTICLE_ID}']
    # a search hit is a list item: flag, no body
    article = after['items'][0]['x']['article']
    assert article['has_content'] is True and 'content_html' not in article


def test_the_full_text_stays_searchable_after_a_bodiless_repush(xa_env):
    """Every round's timeline re-push re-indexes the tweet; the document must be
    built from the stored body, not from the push that has none."""
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [article_tweet()])
        _ingest(client, xa_env, [timeline_tweet()])
        hits = client.get('/api/search', params={'q': BODY_ONLY_PHRASE}).json()
    assert [item['key'] for item in hits['items']] == [f'x:{ARTICLE_ID}']


def test_the_verdict_still_reads_title_and_preview_only(xa_env):
    """The embedding and the attribute LLM are billed per token and have no
    truncation; a three-thousand-character body must not reach them."""
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        before = verdict.judge_text(db.x_tweet_judge_rows([ARTICLE_ID])[0])
        _ingest(client, xa_env, [article_tweet()])
        after = verdict.judge_text(db.x_tweet_judge_rows([ARTICLE_ID])[0])
    assert before == after == f'{TITLE}\n{PREVIEW}'


# --- the list payload -------------------------------------------------------------


def test_the_list_says_whether_there_is_a_body_and_never_carries_it(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet(), plain_tweet(1)])
        before = _timeline_x(client)
        _ingest(client, xa_env, [article_tweet()])
        after = _timeline_x(client)

    assert before[str(ARTICLE_ID)]['article'] == {'title': TITLE, 'previewText': PREVIEW, 'has_content': False}
    assert after[str(ARTICLE_ID)]['article'] == {'title': TITLE, 'previewText': PREVIEW, 'has_content': True}
    assert after[str(ARTICLE_ID)]['text'] == TITLE
    # a tweet with no article still has none
    assert after['1']['article'] is None


# --- the detail endpoint -----------------------------------------------------------


def test_the_detail_endpoint_returns_the_envelope_with_the_rendered_article(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [article_tweet()])
        r = client.get(f'/api/x/tweets/{ARTICLE_ID}')
    assert r.status_code == 200, r.text
    item = r.json()
    assert item['source'] == 'x' and item['key'] == f'x:{ARTICLE_ID}'
    assert item['is_read'] is False and item['is_saved'] is False
    article = item['x']['article']
    assert article['title'] == TITLE and article['has_content'] is True
    assert article['content_html'].count('<h2>') == 7
    assert 'width="2986" height="1648"' in article['content_html']
    # the tweet itself is the list's tweet — only the article grew
    assert item['x']['text'] == TITLE


def test_the_detail_endpoint_for_an_article_without_a_body(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        item = client.get(f'/api/x/tweets/{ARTICLE_ID}').json()
    assert item['x']['article'] == {'title': TITLE, 'previewText': PREVIEW, 'has_content': False, 'content_html': None}


def test_the_detail_endpoint_reports_live_state(xa_env):
    key = f'x:{ARTICLE_ID}'
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        client.post('/api/read', json={'keys': [key]})
        client.post('/api/records', json={'key': key})
        client.post('/api/feedback', json={'key': key, 'verdict': 'up'})
        item = client.get(f'/api/x/tweets/{ARTICLE_ID}').json()
    assert item['is_read'] is True and item['is_saved'] is True
    assert item['feedback'] == 'up'


def test_a_saved_article_keeps_its_body_after_retention_takes_the_row(xa_env):
    key = f'x:{ARTICLE_ID}'
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [article_tweet()])
        assert client.post('/api/records', json={'key': key}).status_code == 200
        db.XFeedItem.delete().execute()
        db.XTweet.delete().execute()

        records = client.get('/api/records').json()
        r = client.get(f'/api/x/tweets/{ARTICLE_ID}')

    # the records list is a list: the flag, not the body
    assert len(records) == 1
    assert records[0]['x']['article']['has_content'] is True
    assert 'content_html' not in records[0]['x']['article']
    # ...and the body is still one request away, out of the snapshot
    assert r.status_code == 200, r.text
    assert r.json()['is_saved'] is True
    assert r.json()['x']['article']['content_html'].count('<h2>') == 7


def test_a_snapshot_saved_before_the_body_existed_replays_without_one(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        client.post('/api/records', json={'key': f'x:{ARTICLE_ID}'})
        db.XFeedItem.delete().execute()
        db.XTweet.delete().execute()
        article = client.get(f'/api/x/tweets/{ARTICLE_ID}').json()['x']['article']
    # not False: a snapshot taken before the body existed does not know whether
    # the live row has one by now, and both clients read null as "say nothing"
    assert article['has_content'] is None and article['content_html'] is None


def test_a_snapshot_taken_before_the_body_does_not_freeze_the_flag(xa_env):
    """Saved on the round the read failed, body read the next round (review
    2026-09-17 finding 4): the saved list must not keep saying 「未获取到正文」
    while the timeline card offers 「查看全文」 — the snapshot's own answer is
    null, and the detail endpoint reads the live row."""
    key = f'x:{ARTICLE_ID}'
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        assert client.post('/api/records', json={'key': key}).status_code == 200
        _ingest(client, xa_env, [article_tweet()])
        saved = client.get('/api/records').json()[0]['x']['article']
        listed = _timeline_x(client)[str(ARTICLE_ID)]['article']
        detail = client.get(f'/api/x/tweets/{ARTICLE_ID}').json()['x']['article']
    assert saved['has_content'] is None and 'content_html' not in saved
    assert listed['has_content'] is True
    assert detail['has_content'] is True and detail['content_html'].count('<h2>') == 7


def test_the_detail_endpoint_404s_on_an_unknown_tweet(xa_env):
    with _client() as client:
        _login(client)
        assert client.get('/api/x/tweets/12345').status_code == 404


def test_the_detail_endpoint_needs_auth(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
    with _client() as client:
        assert client.get(f'/api/x/tweets/{ARTICLE_ID}').status_code == 401


# --- schema ------------------------------------------------------------------------


def test_a_pre_v21_archive_gains_the_column_and_keeps_its_rows(xa_env):
    path = os.environ['CONDENSER_DB_PATH']
    db.init_db(path)
    db.tdb.db.execute_sql('DROP TABLE x_tweets')
    db.tdb.db.execute_sql(
        'CREATE TABLE x_tweets (id INTEGER NOT NULL PRIMARY KEY, author_id INTEGER, author_handle TEXT, '
        'author_name TEXT, text TEXT, created_at DATETIME, media TEXT, metrics TEXT, quote_of INTEGER, '
        'rt_of_handle TEXT, reply_to_id INTEGER, article TEXT, urls TEXT, raw TEXT, fetched_at DATETIME NOT NULL)'
    )
    db.tdb.db.execute_sql(
        "INSERT INTO x_tweets (id, text, article, fetched_at) VALUES (7, 'kept', '{\"title\": \"t\"}', '2026-09-01')"
    )
    db.set_meta('schema_version', '20')
    db.close_db()

    db.init_db(path)

    assert db.get_meta('schema_version') == str(db.SCHEMA_VERSION)
    cols = [r[1] for r in db.tdb.db.execute_sql('PRAGMA table_info(x_tweets)').fetchall()]
    assert 'article_detail' in cols
    # the work order's attempt counter died with it (plan 2026-09-17)
    assert 'article_attempts' not in cols
    row = db.get_x_tweet(7)
    assert row.text == 'kept' and row.article_detail is None
    # and the table still takes writes (the ADD COLUMN ordering trap reports on write)
    db.upsert_x_tweet(x.parse_tweet(article_tweet(8)).row(NOW))
    assert json.loads(db.get_x_tweet(8).article_detail)['content'] == DETAIL['article']['content']
