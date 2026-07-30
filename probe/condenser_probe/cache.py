"""Per-feed "already pushed" cache — the one piece of local state the probe keeps.

Why it exists: the Following timeline is a *stable window*, not a fresh sample
(two consecutive bird calls overlapped 19/20). At a 15-minute cadence that means
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
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger('condenser_probe.cache')

DEFAULT_ROOT = Path.home() / '.cache' / 'condenser-probe' / 'seen'
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
