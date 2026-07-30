"""Per-kind cadences: For You hourly, everything else every 15 minutes.

Why the timing moved in-process (it used to be launchd StartCalendarInterval
firing ``run``): the feeds stopped sharing one interval. For You is a firehose
sample — every bird call returns ~n brand-new tweets, so its cadence *is* the
ingest volume and wants to stay low — while Following and the account feeds are
stable windows where a 15-minute round costs almost nothing past the seen cache.
launchd can't express two cadences in one agent, so it now only keeps the
``watch`` process alive and the schedule lives here.

Two guarantees, in order of strength:

* the minute lanes are staggered (:05 vs :00/:15/:30/:45), so the bird calls
  spread out in normal operation;
* the executor has one worker, so even when both tasks come due at the same
  instant — a laptop waking from hours of sleep misfires everything at once —
  they queue instead of racing bird and the server. ``coalesce`` turns those
  hours of missed firings into a single catch-up round per task.
"""

from dataclasses import dataclass
from typing import Callable, Tuple

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger


@dataclass(frozen=True)
class ProbeTask:
    name: str
    kinds: Tuple[str, ...]  # which probe-config feed kinds this task fetches
    minutes: str  # cron minute field, local time


TASKS = (
    ProbeTask('foryou', kinds=('home',), minutes='5'),
    ProbeTask('feeds', kinds=('following', 'user'), minutes='0,15,30,45'),
)


def build_scheduler(run_task: Callable[[ProbeTask], None], tasks=TASKS) -> BlockingScheduler:
    scheduler = BlockingScheduler(executors={'default': ThreadPoolExecutor(max_workers=1)})
    for task in tasks:
        scheduler.add_job(
            run_task,
            CronTrigger(minute=task.minutes),
            args=[task],
            id=task.name,
            name=task.name,
            coalesce=True,
            misfire_grace_time=None,  # late is fine, skipped is not
        )
    return scheduler
