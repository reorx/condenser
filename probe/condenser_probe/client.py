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

    def probe_config(self) -> list[dict]:
        """The feeds to fetch this round (empty when nothing is subscribed/enabled)."""
        return self._request('GET', '/api/sources/x/probe-config').get('feeds', [])

    def ingest(self, channel_id: str, tweets: list) -> dict:
        return self._request('POST', '/api/sources/x/ingest', json={'channel_id': channel_id, 'tweets': tweets})
