---
created: 2026-06-17
tags:
  - telegram
  - backend
  - ingest
  - backfill
  - sync
---

# Content update / fetch mechanism

How messages get into condenser's SQLite cache, and the manual controls a user has over it.
Source of truth: `condenser/tg.py` (`TgManager`), `condenser/routers/tg.py`, `condenser/db.py`,
and telememo's `telememo/service.py` (`TelegramService.backfill`).

## TL;DR

Messages enter the shared `messages` table through **two automatic paths** and **three manual
triggers**:

| Path | Kind | When | Code |
|---|---|---|---|
| Realtime push | automatic | while connected, per new post | `TgManager.start_listening` / `_on_new_message` |
| Backfill (recent window) | automatic | on new subscription + on startup (pending only) | `TgManager._backfill_channel` |
| Refresh (one channel) | manual, **sync** | user clicks Refresh in a channel timeline / 更新数据 menu | `TgManager.refresh_channel` |
| Refresh all | manual, **background** | user clicks Refresh in the All/Unread timeline | `TgManager.refresh_all` |
| Fetch older (200) | manual, **sync** | 继续向更早获取（200 条）menu | `TgManager.fetch_older` |
| Reset data | manual, **sync**, destructive | 重置数据 menu | `TgManager.reset_channel` |

There is **no periodic polling** of Telegram. Live updates rely on the realtime push; everything
else is one-shot.

## Automatic path 1 — realtime push (not poll)

`start_listening()` registers a Telethon `events.NewMessage` handler scoped to the **currently
enabled** subscriptions (`db.enabled_channel_ids()`), via `service.subscribe(...)`. Telegram pushes
new posts over the persistent MTProto connection; each arrival is persisted (`save_message_smart`)
and `is_filtered` is recomputed in `_on_new_message`.

The listener is re-synced whenever the enabled set changes:
- startup (`startup()` if a stored session is authorized)
- after login (`_on_authorized`)
- subscribe / unsubscribe / enable-toggle (`refresh_subscription()`, called by the subscription
  router endpoints)

## Automatic path 2 — backfill (one-time recent window)

`_backfill_channel(cid)` pulls the most recent `CONDENSER_BACKFILL_DAYS` days (default 7,
`config.py`) newest-first via telememo's `service.backfill(..., since_days=...)`, persists, recomputes
filters, then sets `subscriptions.backfill_done = True`. It runs:
- **on new subscription** — spawned in `_register_subscription`
- **on startup** — for `pending_backfill_channel_ids()` = `enabled AND NOT backfill_done`

**Important gap:** once `backfill_done` is true, a channel is never auto-re-pulled. If the process is
offline for a while, the realtime listener misses posts and backfill won't catch them up — that gap
is permanent unless a manual refresh/reset re-pulls within the window. This is the reason the manual
triggers below exist.

### Shared core — `_backfill_channel` (the recent-window pull)

`_backfill_channel(cid)` is the single fetch primitive. It calls
`service.backfill(cid, since_days=CONDENSER_BACKFILL_DAYS)` — newest-first from `offset_id=0` (top of
feed), stopping once older than the day cutoff — then recomputes `is_filtered` and sets
`backfill_done = True`. **Every recent-window code path funnels through it**, so they all fetch the
*same* thing (last ~7 days, from the top); they differ only in what wraps the call:

| Entry point | Method | How it calls `_backfill_channel` | Extra steps around it |
|---|---|---|---|
| New subscription | `subscribe_channel` / `subscribe_channels` → `_register_subscription` | `self._spawn(...)` (background, fire-and-forget) | resolve handle → `get_or_create_channel` + `add_subscription`, then `refresh_subscription()` |
| Startup pending | `start_listening` | spawned per `pending_backfill_channel_ids()` | — |
| Refresh one channel | `refresh_channel` | `await` (sync) | record `MAX(id)` before, return `count_messages_after` (new count) |
| Refresh all | `refresh_all` | `self._spawn(...)` per enabled channel | returns queued count immediately |
| Reset data | `reset_channel` | `await` (sync) | **wipe** messages/comments/read + watermark→0 + `backfill_done=False` first |

So **new-subscribe, refresh, refresh-all, and reset are identical at the fetch layer** — recent-window
backfill from the top. The only differences are sync vs background and reset's pre-wipe.

**The one exception is `fetch_older`** (next-but-one section): it does *not* go through
`_backfill_channel`. It calls `service.backfill` directly with `offset_id=<oldest stored id>`,
`max_messages=200`, and **no** date cutoff — id-anchored backward cursor paging, a different shape.

## Manual trigger — refresh

- **Per channel (sync):** `refresh_channel(cid)` → records the current `MAX(id)` watermark, re-runs
  `_backfill_channel` (idempotent; smart-save dedupes), then returns `count_messages_after(watermark)`
  so the UI reports *new* messages rather than the whole re-scanned window.
  `POST /api/tg/refresh/{id}` → `{status, new}`.
- **All channels (background):** `refresh_all()` spawns a background `_backfill_channel` task per
  enabled channel and returns immediately with the queued count. Results surface via the 30s
  new-content poll (`useNewContent`). `POST /api/tg/refresh` → `{status:'started', channels}`.

Frontend: a context-aware button in the timeline header (`TimelineView`) — per-channel view triggers
the sync refresh, the All/Unread view triggers the background fan-out.

## Manual trigger — fetch older (the cursor-paging detail)

This is the one worth understanding precisely, because Telegram's API shapes it.

**What Telegram supports / doesn't:**
- ❌ No **ordinal / positional** access. You cannot ask for "messages #200–400 by position" — there is
  no `OFFSET n`-by-count, no random access by index.
- ✅ **id-anchored cursor paging.** MTProto `messages.getHistory`, wrapped by Telethon's
  `iter_messages(entity, offset_id=X)`, returns messages with **id strictly smaller (older) than X**,
  newest-first. Per channel, **message ids are monotonically increasing**, so "older" == "smaller id".
  That invariant is the basis of the whole design.

**Implementation (`TgManager.fetch_older`, `condenser/tg.py`):**
1. **Anchor:** `oldest = db.channel_min_message_id(cid)` = `SELECT MIN(id) FROM messages WHERE channel_id=?`
   — the oldest row we already have.
2. **Page back:** `service.backfill(cid, offset_id=oldest, max_messages=200, persist=True)` →
   `iter_messages(entity, offset_id=oldest)` streams strictly-older messages.
3. **Count cap is client-side:** the "200" is **not** a Telegram parameter. `_iter_backfill` counts
   yielded messages (`yielded += 1`) and `return`s once `yielded >= max_messages`
   (`telememo/service.py`). So it's a streaming truncation, not a server offset.
4. **No date cutoff:** `since_days`/`since_date` are both `None` on this path, so it can walk
   arbitrarily far back, bounded only by the count.
5. Recompute `is_filtered` for the fetched ids; return `len(set(ids))` (`raw_message_ids` expands
   albums, then de-duped). Since these are strictly older and weren't stored, the count ≈ genuinely new.

`POST /api/tg/fetch-older/{id}?count=200` → `{status, fetched}`.

**Clients:** web exposes it as the 继续向更早获取 menu action (`useFetchOlder`); iOS triggers it
by pulling up past the bottom of an exhausted channel timeline, then resumes cursor paging with
the timeline response's `end_cursor` (the last-unit anchor that stays present even when
`next_cursor` is null — added 2026-07-19 for exactly this hand-off).

**Repeatability:** each click's `MIN(id)` is lower than the last (the previous fetch persisted older
rows), so the anchor keeps walking backward, one 200-chunk at a time.

**Empty-cache fallback:** with nothing stored, `MIN(id)` → 0, and Telethon treats `offset_id=0` as
"from the newest", so it pulls the 200 newest. Sensible.

**Sync-watermark guard (critical):** a backward fetch's `max_id` is *lower* than the channel's current
`last_sync_message_id`. `backfill` only advances the watermark on a top-of-feed pull — the guard is
`if persist and max_id and not offset_id:` (`telememo/service.py`). A backward (offset_id-set) fetch
must never downgrade the watermark.

## Manual trigger — reset data (destructive)

`reset_channel(cid)` (`condenser/tg.py`): deletes the channel's cached `messages` + `comments` +
`read_messages` (`db.delete_channel_messages`), resets the sync watermark to 0, sets
`backfill_done = False`, then re-runs `_backfill_channel`. Returns `{deleted, fetched}`.
`POST /api/tg/reset/{id}`.

**Preserved (not cache):** saved records (`telegram_records`, source-decoupled) and keyword filters.
The subscription row itself stays. UI gates it behind a red destructive confirm dialog.

## Related: the enable/disable toggle (pause, not delete)

The Manage-channels toggle flips `subscriptions.enabled`. The timeline query, day counts, and unread
counts all `JOIN subscriptions ... AND s.enabled = 1` (`condenser/timeline.py`), and the realtime
listener watches only `enabled_channel_ids()`. So disabling = soft, reversible pause: messages are
hidden from the timeline + sidebar and realtime ingest stops, but the subscription, already-ingested
messages, saved records, and filters all stay. Re-enabling brings everything back.

Escalating destructiveness: **toggle off** (pause, nothing deleted) < **reset** (keep subscription,
wipe cached messages, re-sync) < **unsubscribe** (drop subscription; historical messages stay in the
DB but are no longer tracked).

## API endpoints (all under the app-password cookie gate; 503 if Telegram not authorized)

| Method + path | Effect | Returns |
|---|---|---|
| `POST /api/tg/refresh` | background backfill for all enabled channels | `{status:'started', channels}` |
| `POST /api/tg/refresh/{id}` | sync re-pull one channel's recent window | `{status:'ok', new}` |
| `POST /api/tg/fetch-older/{id}?count=200` | sync page back into history | `{status:'ok', fetched}` |
| `POST /api/tg/reset/{id}` | sync wipe + re-sync (destructive) | `{status:'ok', deleted, fetched}` |

Frontend client methods live in `frontend/src/lib/api.ts`; mutation hooks in
`frontend/src/hooks/useRefresh.ts`.

## Invariants & gotchas

- **Monotonic per-channel ids** — "older" == "smaller id"; basis for MIN/MAX watermark logic and
  cursor paging.
- **Idempotent re-pulls** — telememo's smart batch save de-dupes, so re-running backfill / refresh is
  safe; `is_filtered` survives (extension-column contract — native columns only on write paths).
- **Sync watermark only advances on top-of-feed pulls** — backward fetches use the `not offset_id`
  guard so they can't downgrade `last_sync_message_id`.
- **FloodWait backoff is unbounded** — `_iter_backfill` sleeps `e.seconds + 1` and retries from the
  last `offset_id` with no upper cap, so a sync refresh/fetch-older could hang the HTTP request on a
  large FloodWait. Pre-existing behavior; rarely hit in practice.
- **"new"/"fetched" counts approximate new messages** via id watermarks; albums are counted as raw
  rows (one album of N images = N), so the number is slightly cosmetic, not exact display-units.
