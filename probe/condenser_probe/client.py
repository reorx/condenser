"""HTTP client for the condenser server's probe endpoints.

The probe authenticates with a device Bearer token — the same kind the iOS app
gets from the web ``/authorize`` page — so the server needed no new auth path.
"""

import logging

import httpx

log = logging.getLogger('condenser_probe.client')


class ServerError(RuntimeError):
    pass


class ProbeClient:
    def __init__(self, api_base: str, token: str, timeout: float = 120.0):
        self._client = httpx.Client(
            base_url=api_base,
            headers={'Authorization': f'Bearer {token}'},
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> 'ProbeClient':
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise ServerError(f'{method} {path} failed: {e}')
        if resp.status_code >= 400:
            raise ServerError(f'{method} {path} -> {resp.status_code}: {resp.text[:300]}')
        return resp.json()

    def probe_config(self) -> dict:
        """What to do this round: ``feeds`` to fetch + whether to re-crawl the
        follow list. The server owns both decisions, so the probe stays stateless."""
        return self._request('GET', '/api/sources/x/probe-config')

    def ingest(self, channel_id: str, tweets: list) -> dict:
        return self._request('POST', '/api/sources/x/ingest', json={'channel_id': channel_id, 'tweets': tweets})

    def push_following(self, users: list) -> dict:
        """Replace the server's followed-accounts list (whole-list semantics)."""
        return self._request('POST', '/api/sources/x/following', json={'users': users})
