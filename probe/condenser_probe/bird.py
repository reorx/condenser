"""Thin wrapper around the bird CLI (https://github.com/steipete/bird).

bird reads the browser's logged-in X cookies, so it only works on the user's own
machine — which is the whole reason the probe exists. Output is passed through to
the server untouched: bird's JSON tracks X's internal API, and the server archives
the raw entries so a format drift can be re-parsed rather than lost.
"""

import json
import logging
import subprocess
from typing import Optional

log = logging.getLogger('condenser_probe.bird')


class BirdError(RuntimeError):
    pass


def build_command(feed: dict, bird_bin: str = 'bird') -> list[str]:
    """The bird invocation for one probe-config feed entry."""
    n = str(feed.get('n') or 20)
    kind = feed.get('kind')
    if kind == 'home':
        return [bird_bin, 'home', '-n', n, '--json']
    if kind == 'user':
        handle = feed.get('handle') or feed.get('channel_id')
        if not handle:
            raise BirdError(f'user feed without a handle: {feed!r}')
        return [bird_bin, 'user-tweets', str(handle), '-n', n, '--json']
    raise BirdError(f'unknown feed kind: {kind!r}')


def _run(cmd: list[str], timeout: float) -> str:
    log.debug('running %s', ' '.join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise BirdError(f'{cmd[0]} not found — install bird and/or set bird_bin')
    except subprocess.TimeoutExpired:
        raise BirdError(f'{" ".join(cmd)} timed out after {timeout}s')
    if proc.returncode != 0:
        raise BirdError(f'{" ".join(cmd)} exited {proc.returncode}: {(proc.stderr or "").strip()[:500]}')
    return proc.stdout


def fetch_feed(feed: dict, bird_bin: str = 'bird', timeout: float = 120.0) -> list:
    """Fetch one feed's recent tweets as bird's raw JSON list."""
    out = _run(build_command(feed, bird_bin), timeout)
    try:
        data = json.loads(out)
    except ValueError as e:
        raise BirdError(f'bird did not return JSON ({e}); first bytes: {out[:200]!r}')
    if not isinstance(data, list):
        raise BirdError(f'bird returned {type(data).__name__}, expected a list of tweets')
    return data


def check_auth(bird_bin: str = 'bird', timeout: float = 60.0) -> Optional[str]:
    """``bird whoami`` — returns the logged-in account line, raises BirdError if unusable."""
    return _run([bird_bin, 'whoami'], timeout).strip() or None
