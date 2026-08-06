"""Behavior tests for the in-process schedule: which task runs what, when.

APScheduler itself is not under test — these pin *our* decisions: the task
table partitions the feed kinds, the minute lanes never collide, and the
scheduler is built so two tasks can never run at the same moment.
"""

from condenser_probe.scheduler import TASKS, build_scheduler


def _minutes(spec: str) -> set[int]:
    return {int(m) for m in spec.split(',')}


def test_every_feed_kind_belongs_to_exactly_one_task():
    """A kind in two tasks would double-fetch; a kind in none would silently
    never run once the scheduler replaces the old run-everything round."""
    seen = [kind for task in TASKS for kind in task.kinds]
    assert sorted(seen) == sorted(set(seen))
    assert set(seen) == {'home', 'following', 'user'}


def test_the_two_cadences_are_staggered():
    """For You is hourly, the rest every 15 minutes — on minute lanes that never
    coincide, so the X calls stay spread out even before serialization."""
    foryou = next(t for t in TASKS if 'home' in t.kinds)
    others = next(t for t in TASKS if 'following' in t.kinds)
    assert _minutes(others.minutes) == {0, 15, 30, 45}
    assert len(_minutes(foryou.minutes)) == 1  # hourly
    assert not _minutes(foryou.minutes) & _minutes(others.minutes)


def test_build_scheduler_registers_one_cron_job_per_task():
    ran = []
    scheduler = build_scheduler(lambda task: ran.append(task.name))
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {task.name for task in TASKS}

    for task in TASKS:
        trigger = jobs[task.name].trigger
        minute_field = next(f for f in trigger.fields if f.name == 'minute')
        assert str(minute_field) == task.minutes

    # The job really invokes our runner with its own task.
    for task in TASKS:
        jobs[task.name].func(*jobs[task.name].args)
    assert sorted(ran) == sorted(task.name for task in TASKS)


def test_tasks_can_never_run_concurrently():
    """Staggering spreads the load; this is the hard guarantee. After a sleep
    both tasks can misfire due at the same instant — a one-worker executor makes
    them queue instead of racing X and the server."""
    scheduler = build_scheduler(lambda task: None)
    executor = scheduler._executors['default']
    assert executor._pool._max_workers == 1


def test_missed_runs_coalesce_into_one_catchup():
    """A laptop that slept three hours owes following twelve rounds; it should
    run one on wake, not twelve."""
    scheduler = build_scheduler(lambda task: None)
    for job in scheduler.get_jobs():
        assert job.coalesce is True
        assert job.misfire_grace_time is None  # late is fine, skipped is not
