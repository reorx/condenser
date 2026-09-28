---
created: 2026-09-28
tags:
  - frontend
  - react
  - architecture
  - scroll-to-read
  - vibe-reader
---

# Frontend — cross-cutting behavior

How the web frontend behaves across views: the auth gate, reading state, the reading-view
shell, cache mutation rules and the per-source surfaces. Moved out of the root `AGENTS.md`
on 2026-09-28; this is the behavior half, and `frontend/AGENTS.md` is the inventory half
(one row per component, plus `hooks/` and `lib/`). Read this before changing a behavior
that spans more than one component.

Stack: React 19 + Vite 6 + TS (strict) + Tailwind v4 + shadcn/ui (new-york) + TanStack
Query v5 + React Router v7, pnpm. The backend serves `frontend/dist` at `/` when it exists.
`lib/api.ts` is the typed fetch client (`ApiError`), `lib/types.ts` mirrors the backend JSON.

## Auth gate

The gate is the `tg-status` query (`App.tsx`, `useTgStatus`): a 401 renders `AppLogin`,
anything else lets `status` decide between `TgLogin` and the app.

- The global 401 handler in `lib/queryClient.ts` re-runs `tg-status` when any *other*
  query gets a 401. It must skip `tg-status` itself, or the gate refetch-loops.
- The Telegram login is a wall only for a Telegram-only install. If `GET /api/sources`
  reports any non-Telegram subscription, an unauthorized Telegram session does not block
  the app: an HN- or X-only install has content to show. The App Store review demo server
  is exactly that shape.
- Three details hold this up. The gate waits for the sources query instead of deciding
  early, or the wall flashes at an install that has other sources. A failed sources
  request falls back to walling. `/connect-telegram` renders `TgLogin` from inside the
  app, and `SettingsDialog`'s Telegram row links there when disconnected — it is the only
  way to reach the Telegram login.
- `useSources` is `enabled`-gated in the gate so it never fires behind `AppLogin`.

## Scroll-to-read（看过即读）

`useScrollToRead` marks items read through an IntersectionObserver and a debounced batch
`POST /api/read`. The window is the scroll container, so the IO root is the viewport. iOS
mirrors the same semantics (Kit `ScrollReadModel` + `ReadReporter.unsyncedKeys`).

- A card is judged read once the user has scrolled in the view (armed) and the card's
  bottom edge is at or above the viewport bottom: fully seen, not scrolled away.
- Three states: unread = sky dot, pending sync = emerald dot (`pendingKeys`, also the
  divider-mode border colors), read = none.
- The cache flip and the badge decrement run only on server confirmation. A failed batch
  stays green and retries at debounce × 5; the lit green dot is the "sync is stuck" signal.
- Arming does a one-shot `getBoundingClientRect` sweep of observed elements, because the
  IO does not re-fire without an intersection change.
- The IO uses a dense threshold ladder (0 → 1 in steps of 0.05) so a card taller than the
  viewport still fires when its bottom edge crosses.
- `disarm()` re-gates after `jumpToNewest`. A page unload drops the unsynced queue, and
  those items reload as unread.
- Search results are deliberately not wired to it: scrolling past an old message while
  hunting for another is not reading it.

## Reading-view shell

- `PageHeader` is the top bar of `TimelineView` and `RecordsView`: leading icon
  (`ChannelAvatar` for a channel, an `IconBadge`-wrapped lucide icon for All / Unread /
  Saved), title and unread-count line on the left, icon-only actions on the right. The
  actions use native `title` tooltips rather than the shadcn Tooltip, which would nest
  Radix `asChild` on the Popover triggers.
- The timeline `useInfiniteQuery` lives in `useTimeline`, lifted to `TimelineView`, so the
  header can build the channel filter from loaded items. `useChannelFilter` is owned by
  `TimelineView`; `Timeline` is presentational.
- Unread count is `sub.unread` for a channel, or the sum over enabled subscriptions for
  All / Unread. The backend does not expose a total message count.
- `Timeline` renders a static day label between day groups, not a sticky bar. The channel
  filter sits in `PageHeader` on multi-channel views only.
- ⚠️ Never put a whole query object in an effect's dependency list. It is a new reference
  every render and rebuilds the IntersectionObserver each time; list the fields used, as
  `useInfiniteScrollSentinel` does.
- Timeline items carry only `channel_id`; titles are joined client-side (`useChannelLabels`).
- Saved and Search use `DatedItemRow`, where each item states its own date, because those
  views jump across days and sources.

## Dates and media

- Backend datetimes are UTC. `lib/format.ts:parseDate` accepts both tz-aware (`+00:00`)
  and naive strings, appending `Z` to the naive ones. Day grouping and the calendar use
  the UTC day key.
- Telegram media tries the thumbnail first; `<img onError>` falls back to a file chip
  (video and file both report `media_type='document'`). Thumbnails open `Lightbox`.
  Message entities are not rendered, because the backend does not persist them.
- `MediaThumb` reserves space with an inline `aspectRatio`: exact when the API sent
  `width` / `height`, else 4/3 for a single image and 1/1 in a grid. It shows a `Skeleton`
  until `<img>.onLoad`, then fades the image in. A single image without API dimensions
  takes its natural aspect after load; `lockAspect` keeps grid cells square.
  `WebPagePreview` thumbs use the same skeleton and fade at a fixed size.
- Avatars, tweet media and link-preview images all go through backend proxies
  (`/api/channels/{id}/avatar`, `/api/x/avatar/{handle}`, `/api/preview/image`), so
  reading never contacts Telegram or X from the browser. A failed avatar falls back to a
  colored initial.

## Item detail pane and link previews

Clicking a card's time opens `ItemDetailPane`, a shadcn `Sheet` mounted once in `AppShell`
that covers every list view. It holds the full-info block, the save / note / forward
actions, the annotatable body and the link-preview section; `frontend/AGENTS.md` describes
each part. Telegram message previews come from `GET /api/messages/{cid}/{mid}/previews`,
a single URL from `GET /api/preview`. `lib/extractUrls.ts` is the URL source shared by
linkify and the pane. Preview thumbnails are proxied unless
`CONDENSER_PREVIEW_IMAGE_PROXY` is off, falling back to the media proxy for images that
came with the Telegram message.

## Forwards

- A message forwarded *into* a channel (`telegram.is_forwarded`) renders a `Forwarded`
  label above an indented soft-background box, with the source name as the box's first
  line. `forwardSourceName(msg)` picks `from_channel_name`, then `from_user_name`, then
  `post_author`; null means the label alone (private source, cache miss or unresolvable
  peer).
- An item the reader forwarded *out* carries `forwarded_by_me`, drawn by `ForwardedBadge`
  on the time line of all four cards. The two flags point in opposite directions and can
  sit on the same card.
- `/forwards` (`ForwardsView`, `useForwards`, `ForwardRecordRow`) lists the publish log
  with the record's own metadata above the item, because the comment belongs to the
  forward and one item can be forwarded twice. Deleting a record leaves the Telegram
  message in place, and the dialog says so.
- On success `ForwardDialog` patches `forwarded_by_me` across the item caches and
  invalidates `['forwards']`. When the response says `recorded: false` it patches nothing
  and warns instead.

## Cache mutation rules

- Item envelopes live in several caches at once: the paged timelines, search results, the
  saved list and the forwards log. Patch them through `lib/itemCaches.ts` (`patchItem` /
  `removeItem` / `findItem`), never through one query key, or two copies of a card drift
  apart.
- Optimistic updates are timeline-wide via `setQueriesData({queryKey: ['timeline']})` and
  use `setQueryData(['subscriptions'])` for subscriptions.
- Keyword filter CRUD invalidates `['filters-all']`, `['timeline']` and
  `['subscriptions']`, because the backend recomputes `is_filtered`.
- Errors surface as `sonner` toasts through `api.errorMessage`.
- shadcn primitives in `components/ui/` use the individual `@radix-ui/react-*` packages,
  not the unified `radix-ui`.

## Theme and new-content poll

- `lib/theme.tsx` provides light / dark / system (default system), stored in localStorage
  under `condenser-theme`. An inline script in `index.html` sets the class before mount
  to avoid a flash.
- `useNewContent` polls `/api/timeline/new?after=<head_cursor>` every 30s, paused while
  the tab is hidden. A hit shows a floating banner; clicking it refetches and scrolls to
  the top.

## Vibe Reader link mode

Pairs with the `../vibe-reader-hn` browser extension and involves no backend. The full
contract is in `lib/vibeReader.ts` and its row in `frontend/AGENTS.md`; the plan is
`kb/plans/2026-09-02-vibe-reader-link-mode-and-hn-summary.md`.

- Transport is `window.postMessage` on our own origin, accepted only from
  `event.source === window` under the `vibe-reader` namespace, `v: 1`, pinned by a test.
- `index.html`'s `<meta name="application-name" content="condenser">` is how the
  extension recognizes a tab and injects its bridge. The bridge's presence means the
  sidepanel is open; there is no heartbeat, and `bye` arrives when the port drops.
- The link switch's truth lives in the extension. `setLink` only asks, and `linked` flips
  on the extension's answer, never optimistically.
- Only announced clicks are processed. One click / auxclick delegate on the document
  posts `condenser:open` for each new-tab http(s) link while linked, skipping
  `NO_ARTICLE_HOSTS`, and never calls `preventDefault`.
- Per-URL status (`vibe-reader:status`) is keyed by the `new URL().href` form and drawn by
  `VibeReaderBadge` for the card's last-touched link. It is never persisted and never in
  React Query.

## X surfaces

- Each X feed has its own view at `/s/:source/:feed`, with a `SidebarXFeedLink` row.
  `feed` threads through `useTimeline` / `useTimelineDays` / `useNewContent` /
  `useBulkRead` and the matching endpoints.
- For You joins the aggregate timeline only as far as its `aggregate` mode admits
  (`XAggregateMenu`); its sidebar row is the way to the full feed.
- The Subscriptions page's X block (`XSection`, `XSubscriptionRow`) shows `last push` and
  `parse errors`, so a silent feed can be traced to the probe rather than the server.
  A user feed's `name` stays NULL until the first push teaches the display name, and the
  row shows `@handle` until then.
- Feedback (thumbs and down-reason chips) is documented in `kb/docs/x-feedback.md`.
