# Condenser Frontend — Agent Guide

React 19 + Vite 6 + TS(strict) + Tailwind v4 + shadcn/ui (new-york) + TanStack Query v5 +
React Router v7, **pnpm**. See the root `CLAUDE.md` for the cross-cutting frontend notes
(auth gate, scroll-to-read, optimistic mutations, theme, etc.). This file is the **component
inventory** and the rules for keeping it accurate.

## ⚠️ Maintenance rule (READ FIRST)

**This file is the source of truth for the component inventory below. Whenever you add,
remove, rename, move, or change the purpose of a component under `src/components/`, update
the matching row in the same change.** Keep it one line per component, purpose-first. A PR
that touches `src/components/` but not this list is incomplete.

Two conventions this list exists to protect:

1. **No inline anonymous components in `.map()` loops.** A loop body must render a *referenced*
   component, never `(x) => ( ...inline JSX... )`. If a loop needs custom markup, extract a
   component first, then reference it.
2. **Reusable / loop-rendered / sizeable modules live in `components/`**, not inline in a page
   or parent. Place feature-specific ones under the matching subfolder (`timeline/`, `filters/`,
   `subscriptions/`); cross-feature ones at the `components/` root. Don't over-abstract:
   purpose-specific siblings (e.g. the several channel-row variants) stay separate rather than
   collapsing into one prop-heavy component.

## Component inventory

### `components/` (shared / top-level)

| Component | Purpose |
|---|---|
| `AppShell` *(in `pages/`)* | App layout: desktop sidebar + mobile drawer + content column |
| `CalendarPopover` | Date-filter popover; calendar limited to days that have content (channel- or source-scoped), with a Clear action |
| `ChannelAvatar` | Channel avatar from `/api/channels/{id}/avatar`; falls back to a colored initial (`letterOnly` forces the initial) |
| `ChannelFilter` + `AllChannelsHidden` | Dropdown to toggle per-channel visibility in multi-channel views; `AllChannelsHidden` is the all-filtered-out empty state |
| `ChannelFilterOption` | One row inside the `ChannelFilter` dropdown (avatar + name + message count) |
| `ConfirmDialog` | Generic confirm/cancel modal (destructive variant + pending state) |
| `DeviceList` | Authorized devices (bearer-token clients) in `SettingsDialog`: list + revoke with confirm |
| `HnDisplayModeMenu` | Top-N display-mode dropdown (top10/top20/half/all → PATCH the front feed's config); used by the `/s/hn` header + `HackerNewsSection` |
| `HnGlyph` | The HN "Y" mark in its orange square (size via className); shared by `HnCard`, the sidebar feed row, the `/s/hn` header, `HackerNewsSection` |
| `PageHeader` + `IconBadge` | Unified reading-view top bar (leading icon + title + meta + right-aligned actions); `IconBadge` wraps a lucide icon in a muted circle |
| `SegmentedOption` | One icon-over-label button in a segmented control; shared by `SettingsDialog`'s theme + unread pickers |
| `SettingsDialog` | Settings modal: Telegram account, theme, unread-indicator mode, devices, lock app |
| `Sidebar` | Left navigation: nav links (Unread first, `/` = Unread, `/?all=1` = All), then one `SidebarSourceGroup` per source from `GET /api/sources`, browse, settings |
| `SidebarSourceGroup` | One collapsible source section (collapse persisted via `useCollapsedSources`): header row = chevron toggle + label linking to `/s/:source` (+ unread badge when collapsed), rows = the source's enabled subscriptions |
| `SidebarChannelLink` + `navLinkClass` | One Telegram channel link in a sidebar source group; also exports the shared nav-row className used by the top-level links |
| `SidebarHnFeedLink` | One HN feed link in the sidebar's Hacker News group (routes to `/s/hn` — v1 has a single feed) |
| `Spinner` + `FullScreenSpinner` | Loading spinner (inline + full-screen) |
| `UnreadBadge` | Unread-count pill; renders nothing at 0, caps display at `999+` |

### `components/timeline/`

| Component | Purpose |
|---|---|
| `Timeline` | Presentational timeline list: day groups + infinite scroll + new-content banner + loading/error/empty states |
| `TimelineDayGroup` | One calendar day's messages under a static date divider |
| `TimelineSkeleton` | Loading placeholder rows for the timeline |
| `MessageCard` | A single Telegram item (takes the `TimelineItem` envelope; payload in `item.telegram`): header (avatar/name/time/save), text, media, webpage preview, forward box. The time is a button (full-date `title` tooltip) that opens the `LinkPreviewPane` — the unified drawer entry on every message |
| `HnCard` | A Hacker News story card: title link (external URL, or comments page for self-posts), day-rank badge + score/comments/domain meta, an embedded `LinkPreviewCard` when the story carries an ingest-prefetched `hn.preview` with content, sanitized self-post HTML behind a char-threshold "more" clamp, muted job posts, scroll-to-read + save; the submitted-time button opens the `LinkPreviewPane` (HN target) |
| `MessageMedia` | Media layout (single image vs 2/3-col grid) + lightbox trigger |
| `MediaThumb` | One media thumbnail: skeleton + aspect-ratio transition + file-chip fallback when no preview image |
| `WebPagePreview` | Telegram-style inline link preview card (thumbnail + site/title/description) |
| `LinkPreviewPane` | Right-side slide-out (shadcn `Sheet`) driven by the `linkPreviewPane` context's `PaneTarget` union: a TG message's link previews with an "Open original in Telegram" footer (`tgMessageUrl`), or an HN story's URL preview — the envelope's prefetched `story.preview` renders instantly, live `useUrlPreview` fetch only when it's absent — with an "Open comments on Hacker News" footer (self-posts show a placeholder); mounted once in `AppShell` |
| `LinkPreviewCard` | One self-fetched link preview (proxied image / Telegram-image fallback + site/title/description; `channelId` optional — absent for HN targets); shared by the pane and `HnCard`'s embedded preview |
| `Lightbox` | Fullscreen media viewer with prev/next navigation |
| `SavedMessageItem` | One saved item in the Saved view: full date line + the source's card (`MessageCard` / `HnCard`) |

### `components/filters/`

| Component | Purpose |
|---|---|
| `CreateFilterDialog` | Create-keyword-filter modal: scope, channel, keyword input, live preview |
| `ScopeOption` | A selectable scope card (Global / Single channel) |
| `ChannelPicker` | Searchable single-channel selector popover |
| `ChannelPickerOption` | One channel row inside `ChannelPicker` |
| `FilterPreviewResult` | Preview panel: loading / error / summary + matched-sample list |
| `FilterPreviewSample` | One matched-message sample with the keyword highlighted |
| `HighlightedText` | Wraps case-insensitive keyword occurrences in `<mark>` |
| `FilterGroupSection` + `FilterGroup` type | One scope section on the Filters page (Global/channel header + keyword chips); exports the `FilterGroup` type used by `FiltersView.groupFilters` |
| `FilterKeywordChip` | One removable keyword pill (delete button + in-flight spinner) |

### `components/subscriptions/`

| Component | Purpose |
|---|---|
| `AddByHandleDialog` | "Add by handle" modal on the Manage channels page: subscribe to a public channel by @handle / t.me link |
| `BrowseChannelsDialog` | "Browse my channels" modal: search + multi-select + batch add |
| `BrowseChannelRow` | One selectable channel row in `BrowseChannelsDialog` |
| `SubscriptionRow` | One channel row on the Manage channels page: enable switch + actions menu + confirm dialogs |
| `HackerNewsSection` | The Hacker News block on the Subscriptions page: Front Page subscribe/unsubscribe, sampling pause switch, display-mode menu, status line (`/api/hn/status`) |

> `components/ui/` holds generated shadcn/ui (new-york) primitives — intentionally **excluded**
> from this inventory. Don't list them here. Import `Button` from `@/components/ui/button`.

## Where things live (non-components)

- `pages/` — route screens (`TimelineView`, `RecordsView`, `FiltersView`, `SubscriptionsView`,
  `AppShell`, `AppLogin`, `TgLogin`, `AuthorizeView` — the device-authorization page cold-loaded
  by the iOS app; only needs the cookie session, so `App.tsx` renders it before the TG gate).
- `hooks/` — data + behavior hooks (`useTimeline`, `useSources`, `useSubscriptions`,
  `useChannelFilter`, `useScrollToRead`, `useNewContent`, `useRefresh`, `useCollapsedSources`
  (sidebar collapse persistence), `useHnDisplayMode` (mode helpers + PATCH mutation),
  mutations, …). `useTimeline` / `useTimelineDays` / `useNewContent` / `useBulkRead` accept a
  `source` scope (the `/s/:source` views).
- `lib/` — `api.ts` (typed fetch client), `types.ts` (backend JSON mirror), `format.ts`,
  `sources.ts` (source labels, `hnCommentsUrl`, sub-row labels), `sanitize.ts` (DOMPurify
  wrapper for HN self-post HTML), `linkify.tsx`, `extractUrls.ts` (shared URL
  regex/extraction for linkify + the preview pane), `linkPreviewPane.tsx` (the pane's
  `PaneTarget` context: TG message or HN story), `theme.tsx`, `unreadIndicator.tsx`,
  `queryClient.ts`, `utils.ts`.

## Debugging

### Render a component in isolation and screenshot it

To verify a visual change **without a logged-in backend**, use the dev-only preview harness
instead of the real app (which is behind the auth + TG-login gate):

- `preview.html` + `src/preview/` — mounts `PreviewApp` with only the providers the cards need
  (`QueryClientProvider`, `UnreadIndicatorProvider`, `ThemeProvider`); **no router, no auth gate**.
  Vite serves it in dev only at `/preview.html` (not a production build input).
- `src/preview/PreviewApp.tsx` — the gallery + a toolbar (toggle theme / unread-mode). Add a
  case here for the component/state you're verifying.
- `src/preview/mocks.ts` — `makeMsg()` factory + sample `DisplayMessage`s. `ChannelAvatar`'s
  proxy 404s here and falls back to the colored initial (expected, not an error).

Loop (dev server already on `:5792` via `pnpm dev`):

```bash
agent-browser --session cond-preview open http://127.0.0.1:5792/preview.html
agent-browser --session cond-preview wait --text "<some text on the page>"
agent-browser --session cond-preview screenshot /abs/tmp/shot.png --full      # then Read it
agent-browser --session cond-preview find text "theme:" click                 # toggle dark, re-shot
agent-browser --session cond-preview close                                    # when done
```

`--full` needs an explicit output path (the `--screenshot-dir` form mis-parses with `--full`).
Selector-scoped screenshots aren't supported — to inspect fine detail (a 8px dot, a 1px rule),
crop + upscale the PNG instead:

```bash
# left top right bottom [scale] — Pillow via uv, no project dep needed
uv run --with pillow python - "$@" <<'PY'   # or keep a tmp/crop.py helper
import sys; from PIL import Image
src,out,*rest = sys.argv[1:]; box=tuple(map(int,rest[:4])); s=int(rest[4]) if len(rest)>4 else 3
c=Image.open(src).crop(box); c.resize((c.width*s,c.height*s), Image.NEAREST).save(out)
PY
```
