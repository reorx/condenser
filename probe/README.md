# condenser-probe

Pushes X (Twitter) data into a condenser server from **your own machine**.

X data only exists inside a logged-in browser session, so unlike the Telegram and
Hacker News sources the server cannot fetch it: this probe runs locally, reads the
timeline through the [bird](https://github.com/steipete/bird) CLI (which borrows
your browser's X cookies), and pushes the raw JSON to the server, which parses and
archives it.

The probe is **stateless** and holds **no feed list**: each round it asks the
server what to fetch (`/api/sources/x/probe-config`, driven by your subscriptions
in the web UI) and pushes back the most recent N tweets per feed. The server
deduplicates by tweet id, so a probe that crashed, slept for a week, or was
reinstalled just resumes — nothing to recover.

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
uv run condenser-probe run        # one round (what launchd/cron should call)
uv run condenser-probe watch --interval 1800   # foreground loop, for setup
```

Subscribe to feeds on the server's Subscriptions page (X block): **For You**
(`foryou`) and/or individual accounts by handle. `probe-config` reflects that
immediately — no probe restart, no local config.

## Scheduling (launchd)

`run` is a single round that exits, which is what you want on a laptop: sleeping
just misses rounds. Suggested cadence: For You every 30–60 min.

```bash
cp com.condenser.probe.plist.example ~/Library/LaunchAgents/com.condenser.probe.plist
# edit the paths inside, then:
launchctl load ~/Library/LaunchAgents/com.condenser.probe.plist
tail -f ~/Library/Logs/condenser-probe.log
```

cron works equally well: `*/30 * * * * cd /path/to/probe && uv run condenser-probe run >> ~/condenser-probe.log 2>&1`

## Tests

```bash
uv run pytest      # bird + server are stubbed; no network, no X account needed
```
