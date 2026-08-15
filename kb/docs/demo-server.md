---
created: 2026-08-15
tags:
  - ios
  - app-store
  - app-review
  - demo-server
  - deploy
  - hn
---

# Demo server (App Store review)

`https://condenser-demo.reorx.com` — a second condenser instance whose only job is to give
an Apple reviewer something to log into. Condenser is a self-hosted single-user reader, so
without it a reviewer installs the app, sees a "server address" field, and has nowhere to
go: that is a Guideline 2.1 rejection with near-certainty.

Read this before submitting a version, and before touching anything about the demo. The
matching operations record (ansible role, port, Caddy vhost, DNS) is the **Demo 实例**
section of the deploy workspace's `kb/docs/condenser.md`. The **password** and the exact
App Review form fields live in the private KB (`kb.private/condenser/kb/docs/`), because
this repository is public.

## What it is

One extra container on the same host as production, sharing nothing with it:

| | production | demo |
|---|---|---|
| domain | `condenser.reorx.com` | `condenser-demo.reorx.com` |
| directory / port | `/opt/apps/condenser` · 3459 | `/opt/apps/condenser-demo` · 3465 |
| sources | Telegram + HN + X | **Hacker News only** |
| Telegram session | the author's account | **none, ever** |
| deploys | `git push` to master | manual image refresh |
| backups | 6h to OSS | none — the data is regenerable |

Three properties are what make it maintenance-free, and each is a deliberate choice rather
than a shortcut:

* **Hacker News is public data.** No account, no token, nothing to expire. The sampling
  loop keeps the timeline fresh on its own, so a demo left alone for a month still opens
  onto today's front page. Every other source condenser has would need credentials the
  reviewer must not be given.
* **There is no Telegram session, and there must never be one.** A demo carrying the
  author's account would hand a stranger a stranger's private channels. `demo_bootstrap.py`
  checks this on every run and refuses to pass if `/api/tg/status` ever says `authorized`.
  The `.env` pre-fills `TELEGRAM_API_ID=1` / `TELEGRAM_API_HASH=dummy` — the settings model
  demands the fields, but `TgManager.startup()` returns before constructing a client when
  no session is stored, so nothing reaches Telegram.
* **No embedding / attribute API key.** The For You verdict pipeline stays inert without
  one, so the demo cannot spend money. There is no X data here to judge anyway
  (`CONDENSER_X_ENABLED=false`).

**It is deliberately not on hookploy.** Production is push-to-deploy; the demo is not,
because during a review window a bad deploy is a rejection. Its ansible role uses
`pull: missing`, so even a full ansible run leaves the running version alone. Refreshing is
an explicit act — see the checklist below.

## `scripts/demo_bootstrap.py`

Initialization and the pre-submission health check are the same command, which is why it
lives in `scripts/` rather than `tmp/`:

```bash
envops read-value hh-hk-01:/opt/apps/condenser-demo/.env -K CONDENSER_APP_PASSWORD --unsafe |
  uv run python scripts/demo_bootstrap.py --url https://condenser-demo.reorx.com --password-stdin
```

It logs in, subscribes to the HN front page if needed (re-running takes the re-enable path
and is harmless), waits for stories to appear, and then asserts what a reviewer would
actually see. A non-zero exit means the reviewer would have been shown an empty app.

Two details worth knowing before reading its output:

* **It polls `/api/timeline`, not the archive count.** Since schema v14 a story is archived
  long before it is *admitted* to the timeline, so `stories_total` rising proves nothing
  about what is on screen.
* **A first run reports one day and says so.** The hckrnews history backfill is throttled to
  ~4s per imported day, so 7 days of history takes a few minutes to land. Re-run to confirm;
  a healthy demo reports 7 days and 130-ish stories.

The password can also come from `CONDENSER_DEMO_PASSWORD` in the environment. It is never
accepted as an argument — that is what puts a secret into shell history and agent transcripts.

## Submitting for review

In App Store Connect → the version → **App Review Information**:

* **Sign-In Required**: Yes
* **User Name**: `https://condenser-demo.reorx.com` (the app has no username; the server
  address is what the reviewer must type, so putting it here makes it hard to miss)
* **Password**: the demo app password (private KB)
* **Notes**: the text below, with the password substituted

> Condenser is a self-hosted, single-user feed reader. Each user runs their own server
> instance; this app is a read-only client for it, and there is no public sign-up. For
> review, please use our demo server:
>
> 1. On the first screen, enter this server address (the field starts empty):
>    https://condenser-demo.reorx.com
> 2. Tap the login button. A web authorization page opens. Enter the app password:
>    <password>
> 3. Tap "Authorize". The app pairs with the server and shows the reading timeline.
>
> All content is public Hacker News front-page data, refreshed automatically. The demo
> server is kept online for the whole review period.

The login screen's server field ships **empty** on purpose (`ios/Condenser/UI/LoginView.swift`).
It used to be pre-filled with the production domain, which meant a reviewer who tapped login
without editing would authenticate against the author's own server, where the demo password
is rejected — a failure that reads as "the demo credentials do not work".

## Checklist before every submission

1. **Is it alive and populated?** Run `demo_bootstrap.py` (above). Exit 0 and ≥7 days of
   stories is the pass.
2. **Does the password in the review notes still match the server?**
   `envops show hh-hk-01:/opt/apps/condenser-demo/.env` — masked, but enough to spot that
   somebody rotated it.
3. **Refresh the image?** Only if the version under review needs a server-side change. It is
   not automatic:
   ```bash
   ssh hh-hk-01 'cd /opt/apps/condenser-demo && docker compose pull && docker compose up -d'
   ```
   Then re-run `demo_bootstrap.py`. Prefer *not* doing this mid-review.
4. **Optional — reset the reviewer's tracks.** Previous reviewers leave read/saved state
   behind. It does not matter (the timeline defaults to unread and refills daily), but to
   start clean:
   ```bash
   ssh hh-hk-01 'cd /opt/apps/condenser-demo && docker compose down && rm -rf data/* && docker compose up -d'
   ```
   then re-run `demo_bootstrap.py` and wait for the backfill.

## Operating notes

* **It must stay up for the whole review period**, including any resubmission. hh-hk-01 has
  a history of dying without warning (2026-07-03) — that risk is accepted for production and
  inherited here. If the demo is down when a reviewer looks, the rejection is a 2.1 and the
  fix is: bring it back, re-run the bootstrap, resubmit.
* **Do not delete the instance between versions.** Every future submission reuses the same
  server, password and notes.
* Moving it to another host is a `playbook.yml` role move plus a Caddy vhost and a DNS
  record; nothing in the role is hh-specific.
