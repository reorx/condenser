---
created: 2026-06-24
tags:
  - frontend
  - timeline
  - components
  - message-card
  - architecture
---

# Timeline message-box components

How a single timeline "message box" is built, which file owns each visual region, and how the
pieces relate. Read this before restyling or restructuring the message card.

The message box itself is **`MessageCard`** (`src/components/timeline/MessageCard.tsx`). It is
shared verbatim between the main timeline and the Saved view — only the surrounding wrapper
differs. ~90% of message-box edits land in `MessageCard.tsx`; you only descend into a
sub-component when changing media, link previews, the avatar, or text-link rendering.

For the flat purpose-per-component list see `frontend/AGENTS.md`. This doc is the **relationships**.

## TL;DR — component tree

```
Route screen
 ├─ TimelineView (pages/)              owns useTimeline + useChannelFilter; builds PageHeader
 │   └─ Timeline (timeline/)           presentational list: infinite scroll, new-content banner, states
 │       └─ TimelineDayGroup           one calendar day: date-divider rule + the day's cards
 │           └─ MessageCard  ◄── THE MESSAGE BOX ────────────────────────────┐
 │                                                                            │
 └─ RecordsView (pages/ "Saved")                                             │
     └─ SavedMessageItem (timeline/)   full date line + the same card        │
         └─ MessageCard  ◄────────────────────────────────────────────────  ┘

MessageCard composes:
 ├─ header
 │   ├─ unread dot            (dot mode; lib/unreadIndicator.tsx)
 │   ├─ ChannelAvatar         (components/ChannelAvatar.tsx)
 │   ├─ channel name · time · edited pencil
 │   └─ save/bookmark button  (hooks/useSaveToggle.ts)
 └─ body  (rendered bare, or inside the forward box)
     ├─ text                  → linkify()  (lib/linkify.tsx)
     ├─ MessageMedia          (timeline/MessageMedia.tsx)
     │   ├─ MediaThumb ×N      (timeline/MediaThumb.tsx)   single image OR 2/3-col grid
     │   └─ Lightbox           (timeline/Lightbox.tsx)     opened on thumb click
     └─ WebPagePreview         (timeline/WebPagePreview.tsx)  link preview card
```

## Render chain (where the data comes from)

1. **`TimelineView`** (`pages/TimelineView.tsx`) owns the data: `useTimeline({channelId, unreadOnly, date})`
   returns the infinite query; `items = pages.flatMap(p => p.items)`. It also owns `useChannelFilter`
   (the header's per-channel toggle) and derives `visible` (post-filter). It builds the `PageHeader`
   and passes `query`/`items`/`visible` down.
2. **`Timeline`** (`timeline/Timeline.tsx`) is **presentational** — no query of its own. It groups
   `visible` into days (`groupByDay`, keyed by UTC `dayKey`), runs infinite-scroll via an
   IntersectionObserver sentinel, shows the new-content banner, and renders loading / error / empty /
   all-filtered states. It maps day groups → `TimelineDayGroup`.
3. **`TimelineDayGroup`** (`timeline/TimelineDayGroup.tsx`) renders the **date divider** (a full-width
   `bg-border` rule with the day label floating on it over a `bg-background` mask) then maps its
   `items` → `MessageCard`, threading `labels` (channel_id → name) and the `observe` scroll-to-read
   callback.
4. **`MessageCard`** renders one `DisplayMessage`.

The Saved view is the same card with a different wrapper: **`RecordsView`** → maps `filter.visible` →
**`SavedMessageItem`** (full date line + `MessageCard`, no `observe` — saved items aren't re-marked read).

## MessageCard anatomy

`MessageCard.tsx` (memoized; the export is `memo(MessageCardImpl)`). Regions, top to bottom:

| Region | Where | Notes |
|---|---|---|
| Outer `<article>` | the box frame | `border-b`, inset `px-4 sm:px-5`; unread + `divider` mode tints the bottom border sky-blue; `ref={attach}` wires scroll-to-read |
| Unread dot | header, first child | only in `dot` mode (`useUnreadIndicator`); fades to transparent once read |
| Avatar + name + time | header | `ChannelAvatar` + `channelLabel` (passed in) + `timeLabel(date)` |
| Edited pencil | header | shown when `msg.is_edited` |
| Save / bookmark button | header, `ml-auto` | always visible (not hover-only); amber when `is_saved`; calls `useSaveToggle` |
| Body | below header | text → `linkify`, then `MessageMedia`, then `WebPagePreview` |
| Forward box | wraps body when `is_forwarded` | `↪ Forwarded` label outside, then a `rounded-lg border bg-muted/30 p-3 ml-8` card; source name from `forwardSourceName()` (`from_channel_name` → `from_user_name` → `post_author`, else just "Forwarded") |

`body` is built once as a fragment and reused — rendered bare for normal messages, or inside the
forward card. Editing the body layout touches both forwarded and non-forwarded messages at once.

### Fields of `DisplayMessage` the card reads

`text`, `media_items[]`, `webpage`, `is_forwarded`, `forward_info`, `is_read`, `is_saved`,
`is_edited`, `date`, `channel_id`, `id`. (Type in `lib/types.ts`.) Telegram message **entities** are
**not** persisted by the backend, so rich formatting isn't available — `linkify` only auto-links bare
URLs (`lib/linkify.tsx`).

## The media sub-tree

- **`MessageMedia`** (`timeline/MessageMedia.tsx`) — filters `media_items` to renderable ones
  (`has_media`, not a `webpage`), then lays them out: 1 item → single image (`max-h-[28rem]`, aspect
  from API `width/height` or `4/3`); 2 → `grid-cols-2`; 3+ → `grid-cols-3` (square cells). Owns the
  `lightboxIndex` state and renders the `Lightbox` when a thumb is clicked.
- **`MediaThumb`** (`timeline/MediaThumb.tsx`) — one thumbnail. Reserves space with inline
  `aspectRatio`, shows a `Skeleton` until `<img>.onLoad`, then fades in; for single images without API
  dims it overwrites the aspect with `naturalWidth/Height`. `lockAspect` keeps grid cells square. On
  image error (audio/doc with no preview) it falls back to a file chip linking to the proxied file
  instead of opening the lightbox.
- **`Lightbox`** (`timeline/Lightbox.tsx`) — fullscreen overlay; arrow keys / on-screen chevrons for
  prev-next, Esc to close, locks body scroll. Inner `LightboxMedia` starts as `<img>` and falls back
  to `<video>` for documents that turn out to be playable (Telegram lumps video into "document").

Image/file URLs come from `lib/api.ts:mediaUrl(channelId, messageId, thumb?)` (thumbnail vs full).

## Shared dependencies (not timeline-specific)

| Dep | File | Role in the card |
|---|---|---|
| `ChannelAvatar` | `components/ChannelAvatar.tsx` | Header avatar; proxy image with a deterministic colored-initial fallback (`letterOnly` skips the network call) |
| `linkify` | `lib/linkify.tsx` | Turns bare URLs in `text` into `<a class="msg-link">`; no rich entities |
| `useUnreadIndicator` | `lib/unreadIndicator.tsx` | Context for `dot` vs `divider` unread style (localStorage-backed; set in Settings) |
| `useSaveToggle` | `hooks/useSaveToggle.ts` | Bookmark mutation with optimistic `is_saved` flip across all `['timeline']` caches + `['records']` invalidation |
| `timeLabel` / `dayLabel` | `lib/format.ts` | Time on the card / day label on the divider (UTC day keys) |

## Editing guide — "I want to change X"

| Change | Edit |
|---|---|
| The card frame, spacing, header layout, forward box, save button, unread styling | `MessageCard.tsx` (one file) |
| Date divider between days | `TimelineDayGroup.tsx` |
| Spacing/empty/error/infinite-scroll/new-content banner around the list | `Timeline.tsx` |
| Saved-view card wrapper (the date line above saved messages) | `SavedMessageItem.tsx` |
| Media grid breakpoints / single-vs-grid layout | `MessageMedia.tsx` |
| Individual thumbnail (skeleton, aspect, file fallback) | `MediaThumb.tsx` |
| Fullscreen viewer | `Lightbox.tsx` |
| Link-preview card | `WebPagePreview.tsx` |
| Header avatar look / fallback | `ChannelAvatar.tsx` |
| How URLs in text render | `lib/linkify.tsx` (+ `.msg-link` in CSS) |

## Verifying changes (no backend needed)

There is a dev-only **preview playbook** for screenshotting real cards with mock data, bypassing the
auth gate — ideal for iterating on the message box. Vite serves `preview.html` at `/preview.html` in
dev only.

- `src/preview/PreviewApp.tsx` — the gallery + a theme / unread-mode toggle; add cases for new states.
- `src/preview/mocks.ts` — `makeMsg()` factory + sample `DisplayMessage`s (avatar 404s → colored
  initial, expected).

```bash
# pnpm dev (serves :5792)
agent-browser --session cond-preview open http://127.0.0.1:5792/preview.html
agent-browser --session cond-preview screenshot /abs/path/shot.png --full   # then Read it
```

See `frontend/AGENTS.md` → "Component preview / playbook" for the full loop.

## Related docs

- `frontend/AGENTS.md` — flat component inventory (one line per component) + the no-inline-in-loops rule.
- [Timeline 阅读视图重构](../sessions/2026-06-18-timeline-reading-view-redesign.md) — how `PageHeader` /
  `useTimeline` lift / presentational `Timeline` came to be.
- [前端组件拆分重构](../sessions/2026-06-23-frontend-component-extraction-refactor.md) — when
  `TimelineDayGroup` / `MediaThumb` / `SavedMessageItem` were extracted out of their parents.
- [媒体 Skeleton + 持久化宽高](../sessions/2026-06-18-media-skeleton-and-dimensions.md) — the
  `MediaThumb` skeleton + aspect-ratio behavior in detail.
