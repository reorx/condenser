"""CLI entry point: ``condenser-probe check | run | watch``.

``watch`` is the long-running mode launchd keeps alive: an in-process scheduler
(see scheduler.py) runs For You hourly and the other feeds every 15 minutes, on
staggered minutes. ``run`` stays a single full round for cron-style setups and
manual pushes (e.g. ``run --no-cache`` after a server rollback).
"""

import argparse
import logging
import sys

from .bird import BirdError, check_auth
from .cache import SeenCache
from .client import ProbeClient, ServerError
from .config import ConfigError, load_settings
from .runner import run_round
from .scheduler import TASKS, build_scheduler

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
            config = client.probe_config()
            feeds = config.get('feeds') or []
            log.info('server: ok, %d enabled feed(s): %s', len(feeds), ', '.join(f['channel_id'] for f in feeds))
            if config.get('sync_following'):
                log.info('server: the follow list is stale — the next run will re-crawl it')
        except ServerError as e:
            log.error('server check failed: %s', e)
            failures += 1
    return 1 if failures else 0


def _run_once(settings, cache=None, kinds=None) -> int:
    with ProbeClient(settings.api_base, settings.token, settings.timeout) as client:
        try:
            outcomes = run_round(client, bird_bin=settings.bird_bin, timeout=settings.timeout, cache=cache, kinds=kinds)
        except ServerError as e:
            log.error('could not read probe-config: %s', e)
            return 1
    return 1 if any(not o.ok for o in outcomes) else 0


def _watch(settings, cache=None) -> int:
    def run_task(task):
        log.info('task %s: round for kinds %s', task.name, ','.join(task.kinds))
        _run_once(settings, cache, kinds=set(task.kinds))

    for task in TASKS:
        log.info('schedule: %s (%s) at minutes %s', task.name, ','.join(task.kinds), task.minutes)
    # One full round up front: the process just (re)started — possibly at login —
    # and For You should not wait up to an hour for its first slot.
    _run_once(settings, cache)
    try:
        build_scheduler(run_task).start()
    except KeyboardInterrupt:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog='condenser-probe', description=__doc__)
    parser.add_argument('command', choices=('check', 'run', 'watch'), nargs='?', default='run')
    parser.add_argument('--log-level', default=None)
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='push everything bird returns, ignoring what earlier rounds already sent. '
        "Use it after the server's data was wiped or rolled back — the cache would "
        'otherwise suppress exactly the re-push that restores it.',
    )
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
    cache = None if args.no_cache else SeenCache()
    if args.command == 'watch':
        return _watch(settings, cache)
    return _run_once(settings, cache)


if __name__ == '__main__':
    raise SystemExit(main())
