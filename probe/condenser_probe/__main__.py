"""CLI entry point: ``condenser-probe check | run | watch``.

Timing is intentionally external (launchd / cron calling ``run``) so a laptop that
sleeps just misses rounds instead of drifting; ``watch`` exists for a foreground
run while setting things up.
"""

import argparse
import logging
import sys
import time

from .bird import BirdError, check_auth
from .client import ProbeClient, ServerError
from .config import ConfigError, load_settings
from .runner import run_round

log = logging.getLogger('condenser_probe')


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='%(asctime)s %(levelname)-7s %(name)s: %(message)s',
        stream=sys.stderr,
    )


def _check(settings) -> int:
    """Verify both halves of the setup: bird's X session and the server token."""
    failures = 0
    try:
        log.info('bird: %s', check_auth(settings.bird_bin) or 'authenticated')
    except BirdError as e:
        log.error('bird check failed: %s', e)
        failures += 1
    with ProbeClient(settings.api_base, settings.token, settings.timeout) as client:
        try:
            feeds = client.probe_config()
            log.info('server: ok, %d enabled feed(s): %s', len(feeds), ', '.join(f['channel_id'] for f in feeds))
        except ServerError as e:
            log.error('server check failed: %s', e)
            failures += 1
    return 1 if failures else 0


def _run_once(settings) -> int:
    with ProbeClient(settings.api_base, settings.token, settings.timeout) as client:
        try:
            outcomes = run_round(client, bird_bin=settings.bird_bin, timeout=settings.timeout)
        except ServerError as e:
            log.error('could not read probe-config: %s', e)
            return 1
    return 1 if any(not o.ok for o in outcomes) else 0


def _watch(settings, interval: int) -> int:
    while True:
        _run_once(settings)
        log.info('sleeping %ds', interval)
        time.sleep(interval)


def main() -> int:
    parser = argparse.ArgumentParser(prog='condenser-probe', description=__doc__)
    parser.add_argument('command', choices=('check', 'run', 'watch'), nargs='?', default='run')
    parser.add_argument('--interval', type=int, default=3600, help='seconds between rounds in watch mode')
    parser.add_argument('--log-level', default=None)
    args = parser.parse_args()

    try:
        settings = load_settings()
    except ConfigError as e:
        _configure_logging('INFO')
        log.error('%s', e)
        return 2
    _configure_logging(args.log_level or settings.log_level)

    if args.command == 'check':
        return _check(settings)
    if args.command == 'watch':
        return _watch(settings, args.interval)
    return _run_once(settings)


if __name__ == '__main__':
    raise SystemExit(main())
