# condenser-probe

Pushes X (Twitter) data into a condenser server from **your own machine**.

X data only exists inside a logged-in browser session, so unlike the Telegram and
Hacker News sources the server cannot fetch it: this probe runs locally, reads the
timeline through the [bird](https://github.com/steipete/bird) CLI (which borrows
your browser's X cookies), and pushes the raw JSON to the server, which parses and
archives it.

The probe holds **no feed list**: each round it asks the server what to fetch
(`/api/sources/x/probe-config`, driven by your subscriptions in the web UI) and
pushes back the most recent N tweets per feed. The server deduplicates by tweet
id, so a probe that crashed, slept for a week, or was reinstalled just resumes.

The one piece of local state is a **seen cache**
(`~/.cache/condenser-probe/seen/<feed>.json`, pruned to 24h). The Following
timeline is a stable window rather than a fresh sample — two consecutive bird
calls overlapped 19/20 — so without it a 15-minute round re-uploads almost the
same 50 tweets every time. It only decides what to *skip*, so its failure modes
are dull: a missing or unreadable cache means a full re-push (which the server
deduplicates), and an unwritable one costs a re-push later but never a round.

Two consequences worth knowing:

- A tweet's like/RT/reply counts are **frozen at first sighting**, because the
  server refreshes metrics on every push and the cache stops the re-pushes. At a
  15-minute cadence that is usually near zero.
- If the server's data is ever **wiped or rolled back**, the cache would suppress
  exactly the re-push that would restore it. Run one round with
  `condenser-probe run --no-cache`.

> ⚠️ Automated reading of X is against its ToS and X enforces more aggressively
> than Telegram does. Keep the interval low-frequency, use one account, and accept
> the risk — this is a self-hosted, single-user tool.

## Setup

```bash
# 1. bird, logged in via your browser's cookies
brew install steipete/tap/bird     # or: npm i -g @steipete/bird
bird whoami                        # must print your account

# 2. the probe itself
cd probe && uv sync
```

Create a device token in condenser's web UI (Settings → Devices → add one named
e.g. `x-probe`; the token is shown exactly once), then either export the two
settings or write them to `~/.config/condenser-probe/config.json`:

```json
{
  "server_url": "https://condenser.example.com",
  "token": "<device token>"
}
```

Env equivalents (they win over the file): `CONDENSER_PROBE_SERVER_URL`,
`CONDENSER_PROBE_TOKEN`, plus optional `CONDENSER_PROBE_BIRD_BIN`,
`CONDENSER_PROBE_TIMEOUT`, `CONDENSER_PROBE_LOG_LEVEL`, `CONDENSER_PROBE_CONFIG`
(alternate config path).

## Use

```bash
uv run condenser-probe check      # verify bird's session + the server token
uv run condenser-probe run        # one full round (all feeds), then exit
uv run condenser-probe run --no-cache   # ignore the seen cache, push everything
uv run condenser-probe watch      # long-running scheduler (what launchd keeps alive)
```

Subscribe to feeds on the server's Subscriptions page (X block): **For You**
(`foryou`), **Following** (the chronological "accounts you follow" timeline)
and/or individual accounts by handle. `probe-config` reflects that immediately —
no probe restart, no local config.

When the server says so, a round also re-crawls your followed-accounts list
(`bird following --all`, ~15 requests) and pushes it. The server needs it as the
Following feed's ad filter: X injects promoted tweets there with no structural
marker at all, and "is this author someone I follow" is the only reliable test.
The list is refreshed about once a day; the server decides, so nothing schedules
it here.

## Scheduling (launchd + in-process)

The feeds don't share one cadence, so `watch` schedules them itself (APScheduler)
and launchd only keeps the process alive:

| task | feeds | when |
|---|---|---|
| `foryou` | For You (`home`) | hourly at :05 — every call is ~n brand-new tweets, so the cadence *is* the ingest volume |
| `feeds` | Following + accounts | every 15 min at :00/:15/:30/:45 — stable windows, the seen cache makes a quiet round nearly free |

The minute lanes are staggered, and a one-worker executor serializes the tasks,
so two bird calls never run at the same time — including right after wake, when
the missed firings coalesce into one catch-up round per task. On start, `watch`
runs one full round so For You doesn't wait for its first :05.

```bash
cp com.condenser.probe.plist.example ~/Library/LaunchAgents/com.condenser.probe.plist
# edit the paths inside, then:
launchctl load ~/Library/LaunchAgents/com.condenser.probe.plist
tail -f ~/Library/Logs/condenser-probe.log
```

`run` is still a single full round that exits, for cron-style setups:
`*/15 * * * * cd /path/to/probe && uv run condenser-probe run >> ~/condenser-probe.log 2>&1`

## Tests

```bash
uv run pytest      # bird + server are stubbed; no network, no X account needed
```
