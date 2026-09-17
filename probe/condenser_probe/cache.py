"""Per-feed "already pushed" cache — the one piece of local state the probe keeps.

Why it exists: the Following timeline is a *stable window*, not a fresh sample
(two consecutive calls overlapped 19/20). At a 15-minute cadence that means
each round re-uploads almost exactly the same 50 tweets, all of which the server
already has. The cache turns a full re-push into the handful of genuinely new
entries.

What it costs, and it is a real cost: the server refreshes a tweet's metrics on
every push, so a tweet we stop re-pushing keeps the like/RT counts it had when it
was first seen — usually near zero, since a 15-minute probe catches tweets minutes
after they are posted. That is the accepted trade (the plan's decision 2); an
on-demand refresh when a tweet's detail view is opened is the follow-up.

It also breaks the probe's original "stateless and configless" promise, so the
failure modes are designed to be dull:

* cache missing or unreadable -> a full re-push, which the server deduplicates
* cache unwritable -> the round still pushes; nothing is lost, only re-sent later
* server data wiped or rolled back -> the cache would suppress the re-push, so
  ``condenser-probe run --no-cache`` exists to force one

Entries are pruned by age rather than by count, so the file stays a few hundred
integers without a policy anyone has to tune.

``ArticleFailures`` (2026-09-17) is the second, smaller piece of state, kept to the
same rules: how many times each long-form post's TweetDetail read went out and
failed. It exists because the article retry is *structural* — a tweet whose read
failed is left out of the seen cache, so the next round reads it again — and a
tweet whose detail fails every time (a tombstone, a shape xbird cannot map) would
otherwise be read every fifteen minutes for as long as it stays in the timeline
window, weeks in a quiet user feed. After ``runner.ARTICLE_MAX_FAILURES`` real
reads the body is given up and the tweet cached like one X answered without a
body. Same failure modes: unreadable = empty, unwritable = a warning, never a
failed round; the same 24h window prunes it.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger('condenser_probe.cache')

DEFAULT_ROOT = Path.home() / '.cache' / 'condenser-probe' / 'seen'
DEFAULT_FAILURES_PATH = DEFAULT_ROOT.parent / 'article-failures.json'
DEFAULT_MAX_AGE_HOURS = 24

_SAFE_NAME = re.compile(r'[^a-z0-9_.-]+')


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SeenCache:
    """Tweet ids this machine has already pushed, per feed."""

    def __init__(self, root: Path = DEFAULT_ROOT, max_age_hours: int = DEFAULT_MAX_AGE_HOURS):
        self.root = Path(root)
        self.max_age = timedelta(hours=max_age_hours)

    def path(self, channel_id: str) -> Path:
        return self.root / f'{_SAFE_NAME.sub("_", channel_id.lower())}.json'

    def load(self, channel_id: str) -> dict[str, str]:
        """id -> first-seen ISO timestamp. A missing or corrupt file reads as empty,
        because "push everything again" is a correct and cheap recovery."""
        path = self.path(channel_id)
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def filter_new(self, channel_id: str, entries: list) -> list:
        """The entries this machine has not pushed yet, in feed order."""
        seen = self.load(channel_id)
        return [e for e in entries if _entry_id(e) not in seen]

    def record(self, channel_id: str, entries: list, now: Optional[datetime] = None) -> None:
        """Remember these ids and prune the window. Call **after** a successful
        push: recording first would lose a tweet permanently on a failed one."""
        now = now or _now()
        stamp = now.isoformat(timespec='seconds')
        seen = self.load(channel_id)
        for entry in entries:
            key = _entry_id(entry)
            if key is not None:
                seen.setdefault(key, stamp)  # keep the *first* sighting, not the latest
        pruned = {k: v for k, v in seen.items() if _within(v, now, self.max_age)}
        try:
            self._write(channel_id, pruned)
        except OSError as e:
            # A round that pushed successfully must not be reported as failed
            # because a cache file could not be written; the cost is a re-push.
            log.warning('%s: could not write the seen cache: %s', channel_id, e)

    def _write(self, channel_id: str, seen: dict) -> None:
        path = self.path(channel_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seen))


class ArticleFailures:
    """Per-tweet count of TweetDetail reads that went out and failed (see the module
    docstring). One file, global rather than per feed — a tweet id is global, and
    the same article reached through Following and its author's feed is one read."""

    def __init__(self, path: Path = DEFAULT_FAILURES_PATH, max_age_hours: int = DEFAULT_MAX_AGE_HOURS):
        self.path = Path(path)
        self.max_age = timedelta(hours=max_age_hours)

    def load(self) -> dict[str, dict]:
        """id -> {n: count, at: last-failure ISO timestamp}. A missing or corrupt
        file reads as empty: forgetting a count costs a few more reads, nothing else."""
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def bump(self, tweet_id, now: Optional[datetime] = None) -> int:
        """Charge one failed read to this tweet and return its total within the window."""
        now = now or _now()
        key = str(tweet_id)
        failures = self.load()
        entry = failures.get(key) if isinstance(failures.get(key), dict) else {}
        count = (entry.get('n') if isinstance(entry.get('n'), int) else 0) + 1
        failures[key] = {'n': count, 'at': now.isoformat(timespec='seconds')}
        pruned = {k: v for k, v in failures.items() if isinstance(v, dict) and _within(v.get('at'), now, self.max_age)}
        try:
            self._write(pruned)
        except OSError as e:
            log.warning('could not write the article failure memory: %s', e)
        return count

    def _write(self, failures: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(failures))


def _entry_id(entry) -> Optional[str]:
    if not isinstance(entry, dict):
        return None
    value = entry.get('id')
    return str(value) if value is not None else None


def _within(stamp: str, now: datetime, max_age: timedelta) -> bool:
    try:
        at = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return now - at < max_age
