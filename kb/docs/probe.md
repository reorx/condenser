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


## Inline article reads (2026-09-17)

X Article bodies ride up **with their tweets**. Timeline endpoints return a long-form post
as its title + a ~200-char preview; the body exists only on TweetDetail
(`client.get_tweet`, which xbird >= 1.3.0 maps with `article_details=True`). So
`runner._run_feed`, after the SeenCache filter and before the ingest, reads every new tweet
whose `article.title` is set through `xsource.fetch_tweet_article` (1s apart,
`ARTICLE_FETCH_DELAY` = the follow crawl's pacing) and merges the detail's `article` block
into the timeline's: `{**article, **detail}`. The server splits it again at parse time
(`x.split_article`: an allowlist — `article` keeps only `title` / `previewText`, every
other key is the body's → `x_tweets.article_detail`). The rules, after the 2026-09-17
review (`kb/reviews/2026-09-17-x-article-inline-fetch-code-review.md`):

* **only the `article` block is merged, never the detail tweet.** A detail tweet's `text`
  is title + the whole body; pushed in place of the timeline's it would turn every card
  into three thousand characters.
* **a read that fails costs the body, never the tweet** — and which kind of failure it
  is decides what happens next (`runner.Read`):
  * `XSourceError` (session, transport, rate limit, a tombstone's "not found" — xbird
    reports remote failures as values and `xsource` raises every one as this) is the
    **retried** kind: the tweet is pushed bodiless but left out of `cache.record`, so the
    next round finds it new and reads it again. That is the retry mechanism —
    structural, like the timeline read's own: no in-round retry.
  * any other exception is xbird failing to map the answer — this one tweet's, and it
    would recur every round: logged at error, **final**, cached, and it leaves the
    breaker alone.
* **the breaker opens on two consecutive failures** (`BREAKER_FAILURES`, one
  `ArticleReader` per round shared by every feed): from then on the round's remaining
  reads are skipped — pushed bodiless, uncached, read next round. Any answer, body or
  not, resets the count. Two rather than one because one tweet whose detail fails for
  its own reasons must not switch the bodies off for everyone behind it, while a dead
  session or a rate limit fails the second read just like the first; the price is one
  extra timeout per round while the session is dead. A feed whose **ingest fails opens
  it too** — the server is what is down, reading more would only lose more — without
  charging any tweet.
* **a body is given up after five real reads** (`ARTICLE_MAX_FAILURES`, counted in
  `cache.ArticleFailures` — `~/.cache/condenser-probe/article-failures.json`, one file
  keyed by tweet id, pruned by the same 24h window; unreadable = empty, unwritable = a
  warning). Only reads that went out and failed count; a read the breaker skipped learned
  nothing. This is what stops a tombstone in a quiet user feed being read every fifteen
  minutes for weeks. `run --no-cache` forgets it along with the seen cache.
* **a detail that answers without a body is final.** `None`, or empty `content` /
  `plainText`, is X's answer rather than a fault: pushed as is, cached, warning logged.

What is observable is deliberately small (plan decision 3): each feed's log line ends in
`articles N fetched, M failed, K abandoned`, a failed read logs at error level, an opened
breaker at warning — and on the reading side a card whose `has_content` is false says
「未获取到正文」. No status row, counter or retry button. Accepted costs: a For You
article whose read failed is usually gone (For You re-samples, so the tweet rarely comes
back); an article that scrolls out of the timeline window before a successful read keeps
its preview; a session dead for more than ~5 rounds (≈75 min) costs the one or two
articles tried first each round their body for good (the failure cap; `run --no-cache`
is the remedy); and **reads the server then throws away** — the probe does not know
what the server will drop, so a Following tweet the age filter turns into a body-only
archive entry, one the ad filter drops (author not followed) and a For You tweet the
language filter drops each still cost a TweetDetail (~4 reads/hour on For You).

This replaced the end-of-round **work order** of 2026-09-16, which never shipped: split off
the push, its failures were invisible behind a healthy `last push`, and charging attempts at
hand-out would have burned a week's backlog in ~6 hours of a dead session. Verified end to
end on 2026-09-17 against a scratch server with the real X session
(`tmp/2026-09-17-x-article-inline/e2e_probe.py`): a real article read inline (7 h2 / 4
figures rendered, body-only phrase searchable, `text` still the title), a nonexistent id's
read failing → pushed bodiless + uncached + breaker opened (one failure opened it then;
since the review it takes two), and the second round reading exactly that one again. Plan `kb/plans/2026-09-17-x-article-inline-fetch.md`.

⚠️ **Deploy order: server first.** A pre-v21 server stores the whole merged block in
`x_tweets.article`, and the list payload would carry the body on the spot. Then `uv sync` in
`probe/` (xbird 1.2.0 → 1.3.0) + `launchctl kickstart`, then **one `condenser-probe run
--no-cache`** so the articles already pushed without a body — everything still in the
timeline window — get read.
