"""Behavior tests: device-token (Bearer) auth + SPA fallback.

Spec: kb/plans/2026-07-16-mobile-client-api-device-token.md
"""

import hashlib

from fastapi.testclient import TestClient

from condenser import db
from condenser.app import create_app


def _client():
    return TestClient(create_app())


def _login(client):
    r = client.post('/api/auth/login', json={'password': 'pw'})
    assert r.status_code == 200


def _create_device(client, name='Test iPhone'):
    r = client.post('/api/auth/device', json={'name': name})
    assert r.status_code == 200
    return r.json()


# --- device issuance ---------------------------------------------------------


def test_device_create_returns_token_and_stores_hash_only(env):
    with _client() as client:
        _login(client)
        data = _create_device(client)
        assert data['name'] == 'Test iPhone'
        token = data['token']
        assert token  # raw token shown exactly once

        # DB stores the sha256 hash, never the raw token
        device = db.Device.get_by_id(data['id'])
        assert device.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert device.token_hash != token


def test_device_create_requires_cookie_not_bearer(env):
    """A stolen device token must not be able to mint new tokens."""
    with _client() as client:
        _login(client)
        token = _create_device(client)['token']
        client.cookies.clear()
        r = client.post('/api/auth/device', json={'name': 'evil'}, headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 401


# --- bearer auth on business endpoints ---------------------------------------


def test_bearer_token_authenticates_api(env):
    with _client() as client:
        _login(client)
        token = _create_device(client)['token']
        client.cookies.clear()

        assert client.get('/api/subscriptions').status_code == 401
        r = client.get('/api/subscriptions', headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 200


def test_bad_bearer_token_rejected_even_with_valid_cookie(env):
    """A present-but-invalid Bearer header must 401 (no silent cookie fallback)."""
    with _client() as client:
        _login(client)
        assert client.get('/api/subscriptions').status_code == 200  # cookie path intact
        r = client.get('/api/subscriptions', headers={'Authorization': 'Bearer wrong-token'})
        assert r.status_code == 401


# --- device management -------------------------------------------------------


def test_devices_list_exposes_metadata_not_hash(env):
    with _client() as client:
        _login(client)
        _create_device(client, name='iPhone A')
        devices = client.get('/api/auth/devices').json()
        assert len(devices) == 1
        d = devices[0]
        assert d['name'] == 'iPhone A'
        assert 'created_at' in d and 'last_seen_at' in d
        assert 'token_hash' not in d and 'token' not in d


def test_revoked_device_token_stops_working(env):
    with _client() as client:
        _login(client)
        data = _create_device(client)
        token = data['token']
        headers = {'Authorization': f'Bearer {token}'}
        client.cookies.clear()
        assert client.get('/api/subscriptions', headers=headers).status_code == 200

        _login(client)
        assert client.delete(f'/api/auth/devices/{data["id"]}').status_code == 200
        assert client.delete(f'/api/auth/devices/{data["id"]}').status_code == 404
        client.cookies.clear()
        assert client.get('/api/subscriptions', headers=headers).status_code == 401


def test_last_seen_updates_once_then_throttles(env):
    with _client() as client:
        _login(client)
        data = _create_device(client)
        headers = {'Authorization': f'Bearer {data["token"]}'}
        assert db.Device.get_by_id(data['id']).last_seen_at is None

        client.get('/api/subscriptions', headers=headers)
        first_seen = db.Device.get_by_id(data['id']).last_seen_at
        assert first_seen is not None

        # an immediate second request is inside the throttle window: no write
        client.get('/api/subscriptions', headers=headers)
        assert db.Device.get_by_id(data['id']).last_seen_at == first_seen


# --- SPA fallback (prerequisite for the /authorize cold-load) -----------------


def test_spa_fallback_serves_index_for_client_routes(env, tmp_path, monkeypatch):
    static = tmp_path / 'dist'
    (static / 'assets').mkdir(parents=True)
    (static / 'index.html').write_text('<html>SPA</html>')
    (static / 'assets' / 'app.js').write_text('console.log(1)')
    monkeypatch.setenv('CONDENSER_STATIC_DIR', str(static))

    with _client() as client:
        # real files are served as-is
        assert client.get('/index.html').text == '<html>SPA</html>'
        assert client.get('/assets/app.js').text == 'console.log(1)'
        # client-side routes cold-load to index.html (the /authorize flow depends on this)
        for path in ('/authorize?device_name=iPhone', '/saved', '/filters'):
            r = client.get(path)
            assert r.status_code == 200
            assert r.text == '<html>SPA</html>'
        # unknown /api paths still 404, never index.html
        assert client.get('/api/nonexistent').status_code == 404
