"""Behavior tests for X Article full text (plan 2026-09-16).

The timeline queries X serves the probe carry an article's title and a ~200-char
preview, nothing more; only TweetDetail carries the body. So the body arrives in
a second step the server drives: at the end of every round the probe asks for a
**work order** (``GET /api/sources/x/articles/pending``), fetches each tweet's
detail, and pushes back *only the article block* (``POST /api/sources/x/articles``).

What these tests pin is the part that is easy to break later:

* the work order — the 7-day window by first sighting, attempts burned on hand-out
  (so a tweet that kills the probe cannot be handed out forever), newest first;
* the push touches nothing but ``article_detail`` — a detail tweet's ``text`` is
  title + the whole body, and writing it would turn the card into three thousand
  characters;
* the list payload says *whether* there is a body (``has_content``) and never
  carries it; the body is ``GET /api/x/tweets/{id}``'s, rendered to HTML, with the
  saved snapshot as its fallback once retention takes the row;
* full text is searchable, and the verdict does not read it (it is billed).

Plan: kb/plans/2026-09-16-x-article-full-content.md
"""

import copy
import json
import os
from datetime import datetime, timedelta
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


def _pending(client, **params):
    r = client.get('/api/sources/x/articles/pending', params=params)
    assert r.status_code == 200, r.text
    return r.json()['tweet_ids']


def _push(client, articles):
    r = client.post('/api/sources/x/articles', json={'articles': articles})
    assert r.status_code == 200, r.text
    return r.json()


def _push_detail(client, tweet_id=ARTICLE_ID, article=None):
    return _push(client, [{'tweet_id': str(tweet_id), 'article': article or DETAIL['article']}])


def _timeline_x(client):
    r = client.get('/api/timeline', params={'source': 'x', 'limit': 50})
    assert r.status_code == 200, r.text
    return {item['x']['id']: item['x'] for item in r.json()['items']}


# --- the work order ---------------------------------------------------------------


def test_an_article_tweet_without_a_body_is_handed_out(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet(), plain_tweet(1)])
        # ids cross the wire as strings (snowflakes exceed JS's integer range)
        assert _pending(client) == [str(ARTICLE_ID)]


def test_every_hand_out_burns_an_attempt_until_the_cap(xa_env):
    """Counted at hand-out, not on a reported failure: a probe that crashes on a
    tweet never reports anything, and the tweet must still stop coming back."""
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        for _ in range(3):
            assert _pending(client) == [str(ARTICLE_ID)]
        assert _pending(client) == []
    assert db.get_x_tweet(ARTICLE_ID).article_attempts == 3


def test_the_attempt_cap_is_configurable(xa_env):
    xa_env.setenv('CONDENSER_X_ARTICLE_MAX_ATTEMPTS', '1')
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        assert _pending(client) == [str(ARTICLE_ID)]
        assert _pending(client) == []


def test_the_window_is_seven_days_of_first_sighting(xa_env):
    """By ``first_seen_at``, not ``created_at``: For You resurfaces old tweets, and
    what matters is what arrived in this reader recently."""
    inside = ARTICLE_ID + 1
    outside = ARTICLE_ID + 2
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet(inside, title='inside')], at=NOW - timedelta(days=7))
        _ingest(client, xa_env, [timeline_tweet(outside, title='outside')], at=NOW - timedelta(days=7, seconds=1))
        assert _pending(client) == [str(inside)]


def test_an_old_tweet_first_seen_today_is_in_the_window(xa_env):
    old = timeline_tweet()
    old['createdAt'] = 'Wed May 27 10:00:00 +0000 2026'
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [old])
        assert _pending(client) == [str(ARTICLE_ID)]


def test_the_window_is_configurable(xa_env):
    xa_env.setenv('CONDENSER_X_ARTICLE_BACKFILL_DAYS', '1')
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()], at=NOW - timedelta(days=2))
        assert _pending(client) == []


def test_the_order_is_newest_sighting_first_and_the_limit_holds(xa_env):
    ids = [ARTICLE_ID + i for i in range(3)]
    with _client() as client:
        _login(client)
        _subscribe(client)
        for i, tweet_id in enumerate(ids):
            _ingest(client, xa_env, [timeline_tweet(tweet_id, title=f't{i}')], at=NOW - timedelta(hours=3 - i))
        assert _pending(client, limit=2) == [str(ids[2]), str(ids[1])]
    # only what was handed out paid for it
    assert db.get_x_tweet(ids[0]).article_attempts == 0


def test_the_batch_setting_caps_whatever_the_probe_asks_for(xa_env):
    xa_env.setenv('CONDENSER_X_ARTICLE_BATCH', '2')
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet(ARTICLE_ID + i, title=f't{i}') for i in range(4)])
        assert len(_pending(client, limit=50)) == 2
        assert len(_pending(client)) == 2  # no limit = the batch


def test_a_tweet_already_holding_its_body_is_not_handed_out(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        _push_detail(client)
        assert _pending(client) == []


def test_an_article_seen_only_inside_a_quote_is_not_handed_out(xa_env):
    """An embedded quote has no feed row, so no card and no detail to open."""
    quoting = plain_tweet(1, 'look at this')
    quoting['quotedTweet'] = timeline_tweet()
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [quoting])
        assert db.get_x_tweet(ARTICLE_ID) is not None
        assert _pending(client) == []


def test_article_fetching_can_be_switched_off(xa_env):
    xa_env.setenv('CONDENSER_X_ARTICLE_ENABLED', 'false')
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        assert _pending(client) == []
    assert db.get_x_tweet(ARTICLE_ID).article_attempts == 0


def test_both_probe_endpoints_are_refused_while_the_source_is_off(xa_env):
    xa_env.setenv('CONDENSER_X_ENABLED', 'false')
    with _client() as client:
        _login(client)
        assert client.get('/api/sources/x/articles/pending').status_code == 503
        assert client.post('/api/sources/x/articles', json={'articles': []}).status_code == 503


# --- the push -------------------------------------------------------------------


def test_the_push_stores_the_detail_and_nothing_else(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        result = _push_detail(client)
    assert result == {'received': 1, 'stored': 1, 'skipped': 0}

    row = db.get_x_tweet(ARTICLE_ID)
    stored = json.loads(row.article_detail)
    assert set(stored) == {'content', 'plainText', 'coverMedia', 'media', 'publishedAt', 'modifiedAt'}
    assert stored['content'] == DETAIL['article']['content']
    # the card's two fields are exactly what the timeline pushed
    assert row.text == TITLE
    assert json.loads(row.article) == {'title': TITLE, 'previewText': PREVIEW}


def test_a_repush_from_the_timeline_keeps_the_body(xa_env):
    """``upsert_x_tweet`` overwrites the columns it is given; the detail is not one."""
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        _pending(client)
        _push_detail(client)
        _ingest(client, xa_env, [timeline_tweet()])
    row = db.get_x_tweet(ARTICLE_ID)
    assert row.article_detail is not None
    assert row.article_attempts == 1


def test_a_push_without_a_body_stores_nothing(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        _pending(client)
        result = _push_detail(client, article={'title': TITLE, 'previewText': PREVIEW, 'content': '  '})
        assert result == {'received': 1, 'stored': 0, 'skipped': 1}
        # the attempt it was handed out on stays spent
        assert db.get_x_tweet(ARTICLE_ID).article_attempts == 1
        assert _pending(client) == [str(ARTICLE_ID)]
    assert db.get_x_tweet(ARTICLE_ID).article_detail is None


def test_a_push_for_an_unknown_or_malformed_entry_is_skipped_not_rejected(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        result = _push(
            client,
            [
                {'tweet_id': '999', 'article': DETAIL['article']},
                {'tweet_id': 'nope', 'article': DETAIL['article']},
                {'tweet_id': str(ARTICLE_ID), 'article': 'not an object'},
                {'tweet_id': str(ARTICLE_ID), 'article': DETAIL['article']},
            ],
        )
    assert result == {'received': 4, 'stored': 1, 'skipped': 3}


def test_the_full_text_becomes_searchable(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        before = client.get('/api/search', params={'q': BODY_ONLY_PHRASE}).json()
        _push_detail(client)
        after = client.get('/api/search', params={'q': BODY_ONLY_PHRASE}).json()
    assert before['items'] == []
    assert [item['key'] for item in after['items']] == [f'x:{ARTICLE_ID}']
    # a search hit is a list item: flag, no body
    article = after['items'][0]['x']['article']
    assert article['has_content'] is True and 'content_html' not in article


def test_the_verdict_still_reads_title_and_preview_only(xa_env):
    """The embedding and the attribute LLM are billed per token and have no
    truncation; a three-thousand-character body must not reach them."""
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet()])
        before = verdict.judge_text(db.x_tweet_judge_rows([ARTICLE_ID])[0])
        _push_detail(client)
        after = verdict.judge_text(db.x_tweet_judge_rows([ARTICLE_ID])[0])
    assert before == after == f'{TITLE}\n{PREVIEW}'


# --- the list payload -------------------------------------------------------------


def test_the_list_says_whether_there_is_a_body_and_never_carries_it(xa_env):
    with _client() as client:
        _login(client)
        _subscribe(client)
        _ingest(client, xa_env, [timeline_tweet(), plain_tweet(1)])
        before = _timeline_x(client)
        _push_detail(client)
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
        _ingest(client, xa_env, [timeline_tweet()])
        _push_detail(client)
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


def test_the_detail_endpoint_before_the_body_arrives(xa_env):
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
        _ingest(client, xa_env, [timeline_tweet()])
        _push_detail(client)
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
    assert article['has_content'] is False and article['content_html'] is None


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


def test_a_pre_v21_archive_gains_the_columns_and_keeps_its_rows(xa_env):
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
    row = db.get_x_tweet(7)
    assert row.text == 'kept' and row.article_detail is None and row.article_attempts == 0
    # and the table still takes writes (the ADD COLUMN ordering trap reports on write)
    db.upsert_x_tweet(x.parse_tweet(copy.deepcopy(timeline_tweet(8))).row(NOW))
    assert db.get_x_tweet(8).article_attempts == 0
