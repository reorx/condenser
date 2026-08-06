"""Probe configuration: a server URL + a device token, and that is the point.

Everything about *what* to fetch lives on the server (``/api/sources/x/probe-config``),
so this machine holds no feed list to keep in sync. Values come from the
environment, optionally seeded by a JSON file (``~/.config/condenser-probe/config.json``
or ``$CONDENSER_PROBE_CONFIG``) so a launchd job needs no env plumbing.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG_PATH = Path.home() / '.config' / 'condenser-probe' / 'config.json'

# Env var <- JSON key mapping (JSON keys are the env names, lowercased, sans prefix).
_KEYS = ('server_url', 'token', 'x_timeout_ms', 'timeout', 'log_level')


class ConfigError(RuntimeError):
    pass


@dataclass
class ProbeSettings:
    server_url: str
    token: str
    # Two different clocks: the X API is called through xbird per request (a follow
    # crawl makes ~15 of them), the condenser server through one httpx client.
    x_timeout_ms: int = 20000
    timeout: float = 120.0  # per condenser HTTP request, seconds
    log_level: str = 'INFO'

    @property
    def api_base(self) -> str:
        return self.server_url.rstrip('/')


def _from_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        raise ConfigError(f'{path} is not valid JSON: {e}')
    if not isinstance(data, dict):
        raise ConfigError(f'{path} must contain a JSON object')
    return {k: v for k, v in data.items() if k in _KEYS}


def load_settings(config_path: Optional[Path] = None) -> ProbeSettings:
    """Env wins over the config file; missing server_url/token is fatal."""
    path = config_path or Path(os.environ.get('CONDENSER_PROBE_CONFIG', DEFAULT_CONFIG_PATH))
    values = _from_file(path)
    for key in _KEYS:
        env = os.environ.get(f'CONDENSER_PROBE_{key.upper()}')
        if env:
            values[key] = env

    missing = [k for k in ('server_url', 'token') if not values.get(k)]
    if missing:
        raise ConfigError(
            f'missing {" and ".join(missing)} — set CONDENSER_PROBE_SERVER_URL / '
            f'CONDENSER_PROBE_TOKEN or write them to {path}'
        )
    return ProbeSettings(
        server_url=str(values['server_url']),
        token=str(values['token']),
        x_timeout_ms=int(values.get('x_timeout_ms') or 20000),
        timeout=float(values.get('timeout') or 120.0),
        log_level=str(values.get('log_level') or 'INFO'),
    )
