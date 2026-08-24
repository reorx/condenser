"""Forward records: what I republished, and what I wrote at the time.

Forwarding used to be a one-shot side effect — the message landed in
``@reorx_share`` and condenser kept nothing, so neither "did I already forward
this" nor "what did I say about it" was answerable without scrolling the channel.

These tests pin the log it writes now:

* **one row per publish**, never an upsert — the same article forwarded again
  with a different comment is a different thought, and overwriting would delete
  the first one;
* a **snapshot** taken at forward time, so the record still renders after
  retention has taken the source row (``records.py``'s promise, extended);
* and the one inversion of the project's error-handling rule: a bookkeeping
  failure must never turn a message that *was* sent into a 500, because the
  client would retry and the channel would get the message twice.

Telegram stays fully mocked — same ``_armed`` fake as
``tests/test_forward_multi_source.py``, which these reuse.
"""

import json
from datetime import datetime

from fastapi.testclient import TestClient

from condenser import db, forwards, search
from condenser.app import create_app
from tests.conftest import md, seed_channel, seed_messages
from tests.test_forward_multi_source import STORY_ID, TWEET_ID, _armed, _login, seed_story, seed_tweet
from tests.test_multi_source import seed_hn


def _client():
    return TestClient(create_app())


def _records():
    return list(db.ForwardRecord.select().order_by(db.ForwardRecord.id))


# --- the write ---------------------------------------------------------------


def test_a_forward_lands_a_record_with_everything_it_took(env):
    """The row is the receipt: what was said, where it went, and the item itself."""
    with _client() as client:
        _login(client)
        seed_story()
        _armed(client)

        r = client.post('/api/forward', json={'key': f'hn:{STORY_ID}', 'comment': '值得一读'})
        assert r.status_code == 200, r.text
        assert r.json()['recorded'] is True

        (rec,) = _records()
        assert (rec.source, rec.ref1, rec.ref2) == ('hn', STORY_ID, 0)
        assert rec.comment == '值得一读'
        assert rec.mode == 'quote'
        assert rec.target == '@mychannel'
        assert rec.message_id == 999
        assert rec.link == 'https://t.me/mychannel/999'
        assert rec.created_at is not None
        # the snapshot is the envelope payload, exactly as a saved record's is
        assert json.loads(rec.raw_data)['title'] == 'Show HN: A tiny SQLite vector index'


def test_an_empty_comment_is_stored_as_null_not_an_empty_string(env):
    """NULL means "forwarded as-is". An empty string would read as "wrote nothing",
    which is a different (and unreachable) state."""
    with _client() as client:
        _login(client)
        seed_story()
        _armed(client)

        assert client.post('/api/forward', json={'key': f'hn:{STORY_ID}', 'comment': '   '}).status_code == 200

        (rec,) = _records()
        assert rec.comment is None
        assert rec.mode == 'forward'


def test_forwarding_the_same_item_twice_keeps_both_comments(env):
    """A log, not a state: the second forward does not overwrite the first one's
    comment — that comment is the most expensive thing in the record."""
    with _client() as client:
        _login(client)
        seed_story()
        _armed(client)

        client.post('/api/forward', json={'key': f'hn:{STORY_ID}', 'comment': '第一次'})
        client.post('/api/forward', json={'key': f'hn:{STORY_ID}', 'comment': '再看一次，想法变了'})

        assert [r.comment for r in _records()] == ['第一次', '再看一次，想法变了']


def test_the_record_keeps_the_target_that_was_configured_at_the_time(env):
    """``forward_channel`` is mutable; the record is a snapshot of where the
    message actually went, so a later retarget cannot rewrite history."""
    with _client() as client:
        _login(client)
        seed_story()
        _armed(client)
        client.post('/api/forward', json={'key': f'hn:{STORY_ID}'})

        db.set_meta('forward_channel', '@othertarget')
        seed_story(id=STORY_ID + 1)
        client.post('/api/forward', json={'key': f'hn:{STORY_ID + 1}'})

        assert [r.target for r in _records()] == ['@mychannel', '@othertarget']


def test_a_telegram_forward_is_recorded_too(env):
    """The native-forward path has no rendered body, but it is still a publish."""
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        seed_messages([md(5, 100, 1, text='hello')])
        _armed(client)

        assert client.post('/api/forward', json={'key': 'tg:5:100'}).status_code == 200

        (rec,) = _records()
        assert (rec.source, rec.ref1, rec.ref2) == ('telegram', 5, 100)
        assert rec.mode == 'forward'
        assert json.loads(rec.raw_data)['messages'][0]['id'] == 100


def test_the_legacy_tg_endpoint_records_the_same_way(env):
    """Old iOS builds post to the pre-2026-07-27 path; it is the same forward."""
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')
        seed_messages([md(5, 100, 1, text='hello')])
        _armed(client)

        assert client.post('/api/messages/5/100/forward', json={'comment': 'hi'}).status_code == 200

        (rec,) = _records()
        assert (rec.source, rec.ref1, rec.ref2, rec.mode, rec.comment) == ('telegram', 5, 100, 'quote', 'hi')


def test_bookkeeping_failure_never_costs_a_second_message(env, monkeypatch):
    """The regression guard for the whole feature.

    The message is already in Telegram when the record is written; an exception
    escaping here would 500 the request, the client would report a failure, the
    user would press the button again — and the channel would carry the same post
    twice. Losing the row is the cheaper failure, so the write swallows.
    """
    with _client() as client:
        _login(client)
        seed_story()
        send_message, _ = _armed(client)

        def boom(*a, **kw):
            raise RuntimeError('disk on fire')

        monkeypatch.setattr(db, 'add_forward_record', boom)

        r = client.post('/api/forward', json={'key': f'hn:{STORY_ID}', 'comment': 'hi'})
        assert r.status_code == 200
        assert r.json()['link'] == 'https://t.me/mychannel/999'
        # …but the loss is *named*: a client that lit the forwarded badge here
        # would watch it silently go out on the next fetch, with the comment gone.
        assert r.json()['recorded'] is False
        assert send_message.await_count == 1
        assert _records() == []


def test_a_numeric_target_gets_a_valid_private_link(env):
    """A forward target configured as a bot-api-style ``-100…`` id must not leak
    its marker prefix into the ``/c/`` link — since v17 that link is frozen into
    the record, so a wrong one here is a dead 「打开」 button forever."""
    with _client() as client:
        _login(client)
        seed_story()
        _armed(client)
        db.set_meta('forward_channel', '-1001234567890')

        r = client.post('/api/forward', json={'key': f'hn:{STORY_ID}'})
        assert r.status_code == 200, r.text
        assert r.json()['link'] == 'https://t.me/c/1234567890/999'

        # a bare short id (no marker) passes through as-is
        db.set_meta('forward_channel', '1234567890')
        seed_story(id=STORY_ID + 1)
        r = client.post('/api/forward', json={'key': f'hn:{STORY_ID + 1}'})
        assert r.json()['link'] == 'https://t.me/c/1234567890/999'

        assert [rec.link for rec in _records()] == ['https://t.me/c/1234567890/999'] * 2


def test_a_snapshotless_item_is_still_recorded(env):
    """A TG native forward reads no source table, so a message we never archived
    can be published — and the record of it is worth keeping without the item."""
    with _client() as client:
        _login(client)
        seed_channel(5, 'TechNews', 'technews')  # no message rows
        _armed(client)

        assert client.post('/api/forward', json={'key': 'tg:5:100'}).status_code == 200

        (rec,) = _records()
        assert rec.raw_data is None

        item = client.get('/api/forwards').json()['items'][0]
        assert item['item'] is None
        assert item['record']['link'] == 'https://t.me/mychannel/999'


# --- the read ----------------------------------------------------------------


def test_the_record_still_renders_after_the_source_row_is_gone(env):
    """Retention deletes archive rows; a record is a user asset and outlives them."""
    with _client() as client:
        _login(client)
        seed_story()
        _armed(client)
        client.post('/api/forward', json={'key': f'hn:{STORY_ID}', 'comment': '存档'})

        db.HNStory.delete().execute()

        body = client.get('/api/forwards').json()
        assert body['has_more'] is False
        (entry,) = body['items']
        assert entry['record']['comment'] == '存档'
        assert entry['item']['key'] == f'hn:{STORY_ID}'
        assert entry['item']['hn']['title'] == 'Show HN: A tiny SQLite vector index'


def test_forwards_are_listed_newest_first_and_page_by_offset(env):
    with _client() as client:
        _login(client)
        _armed(client)
        for i in range(3):
            seed_story(id=STORY_ID + i, title=f'story {i}')
            client.post('/api/forward', json={'key': f'hn:{STORY_ID + i}', 'comment': f'c{i}'})

        first = client.get('/api/forwards', params={'limit': 2}).json()
        assert [e['record']['comment'] for e in first['items']] == ['c2', 'c1']
        assert first['has_more'] is True

        second = client.get('/api/forwards', params={'limit': 2, 'offset': 2}).json()
        assert [e['record']['comment'] for e in second['items']] == ['c0']
        assert second['has_more'] is False


def test_a_forwarded_item_does_not_pretend_to_be_saved(env):
    """``render_item`` hard-coded ``is_saved=True`` for the saved view; a forward
    record borrowing it would light the bookmark on every card here."""
    with _client() as client:
        _login(client)
        seed_story()
        _armed(client)
        client.post('/api/forward', json={'key': f'hn:{STORY_ID}'})

        (entry,) = client.get('/api/forwards').json()['items']
        assert entry['item']['is_saved'] is False

        assert client.post('/api/records', json={'key': f'hn:{STORY_ID}'}).status_code == 200
        (entry,) = client.get('/api/forwards').json()['items']
        assert entry['item']['is_saved'] is True


def test_deleting_a_record_leaves_the_published_message_alone(env):
    """The dialog says so, and this is what makes it true: nothing here touches
    Telegram — ``delete_messages`` is never called."""
    with _client() as client:
        _login(client)
        seed_story()
        _armed(client)
        client.app.state.tg.service.client.delete_messages.assert_not_called()
        client.post('/api/forward', json={'key': f'hn:{STORY_ID}'})

        (rec,) = _records()
        assert client.delete(f'/api/forwards/{rec.id}').status_code == 200
        assert _records() == []
        client.app.state.tg.service.client.delete_messages.assert_not_called()

        assert client.delete(f'/api/forwards/{rec.id}').status_code == 404


# --- the stamp ---------------------------------------------------------------


def test_the_timeline_marks_the_items_i_forwarded(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1, text='forwarded'), md(1, 11, 2, text='untouched')])
        db.add_subscription(1)
        _armed(client)

        items = client.get('/api/timeline').json()['items']
        assert [it['forwarded_by_me'] for it in items] == [False, False]

        assert client.post('/api/forward', json={'key': 'tg:1:10'}).status_code == 200

        by_key = {it['key']: it for it in client.get('/api/timeline').json()['items']}
        assert by_key['tg:1:10']['forwarded_by_me'] is True
        assert by_key['tg:1:11']['forwarded_by_me'] is False


def test_the_stamp_never_collides_with_telegrams_own_is_forwarded(env):
    """``telegram.is_forwarded`` means "this post was forwarded *into* the channel"
    — the opposite direction. The two live side by side and must stay distinct."""
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1, text='reposted', is_forwarded=True, fwd_from_channel_name='Elsewhere')])
        db.add_subscription(1)
        _armed(client)

        (item,) = client.get('/api/timeline').json()['items']
        assert item['telegram']['is_forwarded'] is True
        assert item['forwarded_by_me'] is False


def test_the_new_content_poll_carries_the_stamp(env):
    with _client() as client:
        _login(client)
        seed_channel(1, 'Tech', 'tech')
        seed_messages([md(1, 10, 1)])
        db.add_subscription(1)
        _armed(client)
        head = client.get('/api/timeline').json()['head_cursor']

        seed_messages([md(1, 11, 5)])
        client.post('/api/forward', json={'key': 'tg:1:11'})

        (item,) = client.get('/api/timeline/new', params={'after': head}).json()['items']
        assert item['key'] == 'tg:1:11'
        assert item['forwarded_by_me'] is True


def test_saved_records_and_search_carry_the_stamp_too(env):
    with _client() as client:
        _login(client)
        seed_hn(4242, 1, title='sqlite vector index')
        search.rebuild()
        _armed(client)
        client.post('/api/records', json={'key': 'hn:4242'})
        client.post('/api/forward', json={'key': 'hn:4242'})

        (saved,) = client.get('/api/records').json()
        assert saved['forwarded_by_me'] is True

        (hit,) = client.get('/api/search', params={'q': 'sqlite'}).json()['items']
        assert hit['forwarded_by_me'] is True


def test_the_forward_log_itself_carries_the_stamp(env):
    """`/forwards` is made of forwarded items by definition — but the flag must
    still be present on its envelopes, or the one view where every card was
    forwarded shows no badge while Saved and Search show it on the same item."""
    with _client() as client:
        _login(client)
        seed_story()
        _armed(client)
        client.post('/api/forward', json={'key': f'hn:{STORY_ID}'})

        (entry,) = client.get('/api/forwards').json()['items']
        assert entry['item']['forwarded_by_me'] is True


def test_x_items_keep_their_string_key_when_stamped(env):
    """X ids cross the API as strings while the record stores an int; the stamp
    compares rendered keys, so the two forms must still meet."""
    with _client() as client:
        _login(client)
        seed_tweet()
        _armed(client)
        assert client.post('/api/forward', json={'key': f'x:{TWEET_ID}'}).status_code == 200

        (stamped,) = forwards.stamp([{'source': 'x', 'key': f'x:{TWEET_ID}'}])
        assert stamped['forwarded_by_me'] is True
        assert forwards.stamp([{'source': 'x', 'key': 'x:1'}])[0]['forwarded_by_me'] is False


def test_an_rss_records_snapshot_carries_the_article(env):
    """Same reason the saved snapshot does: the list payload stopped shipping the
    body on 2026-08-23, and a record has to render without ``rss_entries``."""
    with _client() as client:
        _login(client)
        db.RssFeed.create(url='https://blog.example/feed', title='Example')
        entry = db.RssEntry.create(
            feed_url='https://blog.example/feed',
            guid='g1',
            title='On indexes',
            link='https://blog.example/1',
            content='<p>the whole article body</p>',
            content_excerpt='the whole article body',
            published_at=datetime(2026, 8, 20, 9, 0),
            first_seen_at=datetime(2026, 8, 20, 9, 5),
        )
        _armed(client)
        assert client.post('/api/forward', json={'key': f'rss:{entry.id}'}).status_code == 200

        db.RssEntry.delete().execute()

        (rendered,) = client.get('/api/forwards').json()['items']
        assert rendered['item']['rss']['title'] == 'On indexes'
        assert json.loads(_records()[0].raw_data)['content'] == '<p>the whole article body</p>'
