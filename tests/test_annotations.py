"""Behavior tests for item notes + text annotations (schema v18).

Plan: kb/plans/2026-08-24-annotations.md

``saved_items`` is promoted from "the bookmarks table" to "the items the reader
acted on": ``is_saved`` becomes one state among three, beside an item-level
``note`` and a JSON list of quote-anchored ``annotations``. The row lifecycle
invariant under test everywhere here: **a row exists iff it is saved, or has a
note, or has annotations** — and a row created for a note/annotation alone still
takes the full ``records.py`` snapshot, because X/RSS retention will eventually
take the source row and the annotation must not dangle.
"""

import json
import os
import sqlite3

from fastapi.testclient import TestClient

from condenser import db
from condenser.app import create_app
from condenser.items import tg_key
from tests.conftest import md, seed_channel, seed_messages

CHANNEL = 100


def _client():
    return TestClient(create_app())


def _login(client):
    assert client.post('/api/auth/login', json={'password': 'pw'}).status_code == 200


def init():
    db.init_db(os.environ['CONDENSER_DB_PATH'])


def seed_tg(mid=1):
    seed_channel(CHANNEL, 'Chan A')
    seed_messages([md(CHANNEL, mid, minutes=mid, text=f'message {mid}')])
    db.add_subscription(CHANNEL)


def timeline_item(client, key):
    r = client.get('/api/timeline')
    assert r.status_code == 200, r.text
    matches = [it for it in r.json()['items'] if it['key'] == key]
    assert matches, f'{key} not on the timeline'
    return matches[0]


def records_list(client):
    r = client.get('/api/records')
    assert r.status_code == 200, r.text
    return r.json()


def annotate(client, key, quote, prefix='', suffix='', block=None, comment=None):
    body = {'key': key, 'quote': quote, 'prefix': prefix, 'suffix': suffix}
    if block is not None:
        body['block'] = block
    if comment is not None:
        body['comment'] = comment
    return client.post('/api/annotations', json=body)


# --- item note ---------------------------------------------------------------


def test_note_on_unsaved_item_creates_row_with_snapshot(env):
    """First note on an item nobody saved: the row appears with ``is_saved=False``
    and a full snapshot — the same promise a bookmark makes, because retention
    does not know the difference."""
    init()
    seed_tg(mid=1)
    key = tg_key(CHANNEL, 1)
    with _client() as client:
        _login(client)
        r = client.post('/api/note', json={'key': key, 'note': 'my thought'})
        assert r.status_code == 200, r.text

        row = db.get_saved_item('telegram', CHANNEL, 1)
        assert row is not None
        assert not row.is_saved
        assert row.note == 'my thought'
        # the snapshot is real, not a stub: it replays the message text
        assert 'message 1' in row.raw_data

        item = timeline_item(client, key)
        assert item['note'] == 'my thought'
        assert item['is_saved'] is False

        # the records view lists the row (an annotated item is findable) but does
        # not claim it is bookmarked
        recs = records_list(client)
        assert [it['key'] for it in recs] == [key]
        assert recs[0]['is_saved'] is False
        assert recs[0]['note'] == 'my thought'


def test_note_overwrite_then_clear_deletes_the_shell(env):
    """POST is overwrite semantics; an empty note on an otherwise-empty row
    removes the row entirely — no empty shells."""
    init()
    seed_tg(mid=1)
    key = tg_key(CHANNEL, 1)
    with _client() as client:
        _login(client)
        client.post('/api/note', json={'key': key, 'note': 'first'})
        client.post('/api/note', json={'key': key, 'note': 'second'})
        assert db.get_saved_item('telegram', CHANNEL, 1).note == 'second'

        r = client.post('/api/note', json={'key': key, 'note': ''})
        assert r.status_code == 200
        assert db.get_saved_item('telegram', CHANNEL, 1) is None
        assert timeline_item(client, key)['note'] is None


def test_clearing_a_note_on_a_saved_row_keeps_the_row(env):
    init()
    seed_tg(mid=1)
    key = tg_key(CHANNEL, 1)
    with _client() as client:
        _login(client)
        assert client.post('/api/records', json={'key': key}).status_code == 200
        client.post('/api/note', json={'key': key, 'note': 'kept?'})
        client.post('/api/note', json={'key': key, 'note': ''})
        row = db.get_saved_item('telegram', CHANNEL, 1)
        assert row is not None and row.is_saved
        assert row.note is None


def test_clearing_a_note_that_never_existed_is_a_quiet_ok(env):
    """The clear path must not 404 on a missing row: re-saving an empty editor is
    the iOS delete gesture, and it can race a row that was never created."""
    init()
    seed_tg(mid=1)
    with _client() as client:
        _login(client)
        r = client.post('/api/note', json={'key': tg_key(CHANNEL, 1), 'note': ''})
        assert r.status_code == 200
        assert db.get_saved_item('telegram', CHANNEL, 1) is None


def test_note_on_a_missing_item_404s_and_bad_key_422s(env):
    init()
    with _client() as client:
        _login(client)
        assert client.post('/api/note', json={'key': 'tg:1:999', 'note': 'x'}).status_code == 404
        assert client.post('/api/note', json={'key': 'nope', 'note': 'x'}).status_code == 422


# --- annotations -------------------------------------------------------------


def test_annotations_get_per_item_incrementing_ids(env):
    init()
    seed_tg(mid=1)
    key = tg_key(CHANNEL, 1)
    with _client() as client:
        _login(client)
        r1 = annotate(client, key, quote='message', comment='nice phrase')
        assert r1.status_code == 200, r1.text
        ann1 = r1.json()['annotation']
        assert ann1['id'] == 1
        assert ann1['quote'] == 'message'
        assert ann1['comment'] == 'nice phrase'
        assert ann1['created_at']

        r2 = annotate(client, key, quote='1', prefix='message ', block=0)
        ann2 = r2.json()['annotation']
        assert ann2['id'] == 2
        assert ann2['block'] == 0
        assert ann2['comment'] is None

        item = timeline_item(client, key)
        assert [a['id'] for a in item['annotations']] == [1, 2]
        assert item['annotations'][0]['quote'] == 'message'

        # annotation-only row: snapshot taken, not saved
        row = db.get_saved_item('telegram', CHANNEL, 1)
        assert not row.is_saved
        assert 'message 1' in row.raw_data


def test_annotation_on_a_missing_item_404s(env):
    init()
    with _client() as client:
        _login(client)
        assert annotate(client, 'tg:1:999', quote='x').status_code == 404
        assert annotate(client, 'bad-key', quote='x').status_code == 422


def test_unsave_keeps_annotations_and_the_records_row(env):
    """The invariant's whole point: web's unsave click must not take the reader's
    annotations down with the bookmark."""
    init()
    seed_tg(mid=1)
    key = tg_key(CHANNEL, 1)
    with _client() as client:
        _login(client)
        assert client.post('/api/records', json={'key': key}).status_code == 200
        annotate(client, key, quote='message')
        assert client.delete(f'/api/records/{key}').status_code == 200

        row = db.get_saved_item('telegram', CHANNEL, 1)
        assert row is not None
        assert not row.is_saved
        assert len(json.loads(row.annotations)) == 1

        item = timeline_item(client, key)
        assert item['is_saved'] is False
        assert len(item['annotations']) == 1

        recs = records_list(client)
        assert [it['key'] for it in recs] == [key]
        assert recs[0]['is_saved'] is False


def test_unsave_without_notes_deletes_the_row(env):
    init()
    seed_tg(mid=1)
    key = tg_key(CHANNEL, 1)
    with _client() as client:
        _login(client)
        client.post('/api/records', json={'key': key})
        assert client.delete(f'/api/records/{key}').status_code == 200
        assert db.get_saved_item('telegram', CHANNEL, 1) is None


def test_resaving_an_annotated_row_flips_the_flag_and_keeps_everything(env):
    init()
    seed_tg(mid=1)
    key = tg_key(CHANNEL, 1)
    with _client() as client:
        _login(client)
        client.post('/api/note', json={'key': key, 'note': 'kept'})
        assert client.post('/api/records', json={'key': key}).status_code == 200
        row = db.get_saved_item('telegram', CHANNEL, 1)
        assert row.is_saved
        assert row.note == 'kept'
        assert 'message 1' in row.raw_data


def test_annotation_comment_patch_and_clear(env):
    init()
    seed_tg(mid=1)
    key = tg_key(CHANNEL, 1)
    with _client() as client:
        _login(client)
        ann = annotate(client, key, quote='message').json()['annotation']
        r = client.patch(f'/api/annotations/{key}/{ann["id"]}', json={'comment': 'a thought'})
        assert r.status_code == 200
        assert timeline_item(client, key)['annotations'][0]['comment'] == 'a thought'

        # clearing the comment keeps the highlight
        r = client.patch(f'/api/annotations/{key}/{ann["id"]}', json={'comment': ''})
        assert r.status_code == 200
        item = timeline_item(client, key)
        assert item['annotations'][0]['comment'] is None
        assert item['annotations'][0]['quote'] == 'message'

        assert client.patch(f'/api/annotations/{key}/99', json={'comment': 'x'}).status_code == 404
        assert client.patch(f'/api/annotations/tg:1:999/1', json={'comment': 'x'}).status_code == 404


def test_deleting_the_last_annotation_removes_the_shell(env):
    init()
    seed_tg(mid=1)
    key = tg_key(CHANNEL, 1)
    with _client() as client:
        _login(client)
        ann = annotate(client, key, quote='message').json()['annotation']
        assert client.delete(f'/api/annotations/{key}/{ann["id"]}').status_code == 200
        assert db.get_saved_item('telegram', CHANNEL, 1) is None
        # idempotent, like the feedback delete
        assert client.delete(f'/api/annotations/{key}/{ann["id"]}').status_code == 200


def test_deleting_an_annotation_keeps_a_row_that_still_has_a_reason_to_exist(env):
    init()
    seed_tg(mid=1)
    key = tg_key(CHANNEL, 1)
    with _client() as client:
        _login(client)
        client.post('/api/note', json={'key': key, 'note': 'still here'})
        a1 = annotate(client, key, quote='message').json()['annotation']
        a2 = annotate(client, key, quote='1', prefix='message ').json()['annotation']
        client.delete(f'/api/annotations/{key}/{a1["id"]}')
        row = db.get_saved_item('telegram', CHANNEL, 1)
        assert row is not None
        assert [a['id'] for a in json.loads(row.annotations)] == [a2['id']]
        client.delete(f'/api/annotations/{key}/{a2["id"]}')
        # note still holds the row up
        assert db.get_saved_item('telegram', CHANNEL, 1) is not None


# --- migration ---------------------------------------------------------------


def test_v18_migration_upgrades_a_pre_annotation_table(env):
    """A production file whose saved_items predates v18: the columns appear and
    every existing row reads as saved — the semantic the table had all along."""
    path = os.environ['CONDENSER_DB_PATH']
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE saved_items ('
        'source VARCHAR(255) NOT NULL, ref1 INTEGER NOT NULL, ref2 INTEGER NOT NULL, '
        'raw_data TEXT NOT NULL, created_at DATETIME NOT NULL, '
        'PRIMARY KEY (source, ref1, ref2))'
    )
    conn.execute(
        'INSERT INTO saved_items VALUES (?, ?, ?, ?, ?)',
        ('hn', 42, 0, '{"id": 42}', '2026-08-01 00:00:00'),
    )
    conn.commit()
    conn.close()

    init()
    row = db.get_saved_item('hn', 42, 0)
    assert row is not None
    assert bool(row.is_saved) is True
    assert row.note is None
    assert row.annotations is None


# --- is_saved semantics ripple ------------------------------------------------


def test_note_only_rows_are_not_verdict_training_positives(env):
    """``x_labeled_samples`` reads a saved row as a positive label. A row that
    exists only to hold an annotation is not an endorsement — the note may well
    say "this is wrong" — so only ``is_saved`` rows count."""
    init()
    db.SavedItem.create(source='x', ref1=1, ref2=0, raw_data='{}', is_saved=False, note='hmm')
    db.SavedItem.create(source='x', ref1=2, ref2=0, raw_data='{}', is_saved=True)
    assert db.x_labeled_samples() == {2: 'save'}
