---
created: 2026-08-21
tags:
  - x
  - probe
  - xbird
  - launchd
---

# Local probe (`probe/`, monorepo)

Independent uv package (`condenser-probe`) that runs on the user's own machine — the X
source's fetch half, since X data only exists inside a logged-in browser session. Each
round: `GET /api/sources/x/probe-config` → one X read per feed → `POST
/api/sources/x/ingest`, plus a follow-list re-crawl (~15 requests) whenever
probe-config's `sync_following` says so — the *server* decides, so the probe keeps
no schedule. That sync runs **before** the feeds: the server drops Following entries whose
author is not in the list, so a first round that ingested first would read its own empty
list.

**The X reads go through the `xbird` library, not the `bird` CLI** (2026-08-07;
`condenser_probe/xsource.py`, formerly `bird.py`). `xbird` is Reorx's own Python rewrite of
`@steipete/bird` and ships a library surface, so the subprocess-and-parse-stdout layer is
gone: `home` → `get_home_timeline`, `--following` → `get_home_latest_timeline`, `user-tweets`
→ `get_user_id_by_username` + `get_user_tweets_paged`, `following --all` → `get_current_user`
+ a paged `get_following` loop, `whoami` → `get_current_user`. Four things did **not** change,
each on purpose:

* **the wire shape.** What is pushed is `xbird.types.to_json(tweet)` — byte-identical to what
  `xbird … --json` prints, because the server parses those camelCase keys and archives every
  entry verbatim as `raw`. Handing it pydantic-native snake_case would orphan every historical
  row. Verified on real data: 25 tweets across all three feed kinds through `condenser.x.parse_tweet`,
  0 unkeyable, 0 warnings (`tmp/2026-08-06-xbird-migration/`).
* **failures are per-feed.** xbird returns remote failures as *values* (`result.success`),
  never exceptions; `xsource` raises `XSourceError` on every one, because a failure that read
  as an empty page would report the round OK and hide a dead X session indefinitely.
* **the follow crawl is all-or-nothing.** A failed page raises rather than returning what it
  collected: the server *replaces* the list wholesale and drops Following tweets by authors
  missing from it, so half a list silently discards the rest as advertising.
* **the 1s page pacing** of the follow crawl, which the CLI's `--all` did. Dropping it would
  be an unannounced change in how hard the probe hits X.

The client is built and closed per call (it owns an httpx pool, and `watch` runs for days);
re-resolving credentials each time is what lets a browser re-login take effect without a
restart. Credentials: `resolve_credentials()` → `AUTH_TOKEN`/`CT0` or browser cookies
(Safari → Chrome → Firefox; reading Chrome's needs `/usr/bin/security`, hence the launchd
plist's PATH). xbird is not on PyPI: `pyproject.toml` points at `ssh://git@github.com/reorx/xbird`
(private repo, hence SSH) on `branch = "master"` with `uv.lock` pinning the commit; co-develop
a local checkout with the telememo-style overlay (`uv pip install -e ../../xbird` +
`UV_NO_SYNC=1`). `bird_bin` is gone from the settings; `x_timeout_ms` (per X API request,
20000) joined `timeout` (per condenser HTTP request).

**Live on the probe machine since 2026-08-07 00:08**, and soaked: **74 unattended rounds in
the first 8 hours, 0 errors, 0 tracebacks, 0 parse errors**, both cadences firing on time.
(Re-measure rather than quote — `grep -c "round done" ~/Library/Logs/condenser-probe.log`.)

Note the probe deploys by **restarting the launchd agent**, not by `git push` — `watch` holds
its code in memory, so editing the source changes nothing until
`launchctl kickstart -k gui/$(id -u)/com.condenser.probe`. This bites in a specific way worth
knowing: edit a file *after* a kickstart and the agent silently keeps running the older code,
with nothing on screen to say so (it happened during this very migration — two cleanup edits
landed 35s after the restart). To check rather than assume, compare the process start time
against the source mtimes: `ps -o lstart -p $(launchctl list | awk '/condenser.probe/{print $1}')`.

Two more things measured before going live, both worth re-checking rather than assuming: the
SSH git dependency resolves with **no `SSH_AUTH_SOCK`** (which launchd does not provide), and
the seen-cache file format is unchanged, so old and new code share it.

**Configless** beyond a server URL + device token (env or
`~/.config/condenser-probe/config.json`): the feed list lives on the server, and the server
dedupes by tweet id, so a probe that crashed or slept has nothing to recover. One feed's
failure never sinks the others (`runner.FeedOutcome`), and neither does the follow sync.
The one piece of local state is `cache.SeenCache`
(`~/.cache/condenser-probe/seen/<feed>.json`, pruned to 24h, opt-out via `--no-cache`):
Following is a stable window, so a 15-minute round would otherwise re-upload almost the same
50 tweets — measured on a real second round, 41 of 50 skipped and a followed account pushed
nothing at all, while For You skipped 0 (it re-samples, which is the control). Two
consequences, both accepted (plan decision 2): a tweet's metrics **freeze at first sighting**
(the server refreshes them per push; an on-demand refresh is the follow-up), and if the
server's data is ever wiped the cache would suppress the restoring re-push — hence
`--no-cache`. Recording happens *after* a successful push, never before. CLI:
`condenser-probe check | run [--no-cache] | watch`; **scheduling is in-process since
2026-07-30** (`scheduler.py`, APScheduler): `watch` is the long-running mode launchd merely
keeps alive (KeepAlive plist example in the package), running For You hourly at :05 and
Following + account feeds at :00/:15/:30/:45 — staggered minute lanes plus a one-worker
executor, so two X crawls never overlap, and missed firings coalesce into one catch-up
round per task at wake. On start `watch` runs one full round; `run` = one full round for
cron-style setups. Tests stub xbird + the server, so `uv run pytest` needs no X account
(`test_xsource.py` = the adapter, `test_probe.py` = orchestration over a stubbed fetch).

