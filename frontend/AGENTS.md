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
| `CalendarPopover` | Date-filter popover; calendar limited to days that have content, with a Clear action |
| `ChannelAvatar` | Channel avatar from `/api/channels/{id}/avatar`; falls back to a colored initial (`letterOnly` forces the initial) |
| `ChannelFilter` + `AllChannelsHidden` | Dropdown to toggle per-channel visibility in multi-channel views; `AllChannelsHidden` is the all-filtered-out empty state |
| `ChannelFilterOption` | One row inside the `ChannelFilter` dropdown (avatar + name + message count) |
| `ConfirmDialog` | Generic confirm/cancel modal (destructive variant + pending state) |
| `PageHeader` + `IconBadge` | Unified reading-view top bar (leading icon + title + meta + right-aligned actions); `IconBadge` wraps a lucide icon in a muted circle |
| `SegmentedOption` | One icon-over-label button in a segmented control; shared by `SettingsDialog`'s theme + unread pickers |
| `SettingsDialog` | Settings modal: Telegram account, theme, unread-indicator mode, lock app |
| `Sidebar` | Left navigation: nav links, channel list, browse/add-by-handle, settings |
| `SidebarChannelLink` + `navLinkClass` | One channel link in the sidebar; also exports the shared nav-row className used by the top-level links |
| `Spinner` + `FullScreenSpinner` | Loading spinner (inline + full-screen) |
| `UnreadBadge` | Unread-count pill; renders nothing at 0, caps display at `999+` |

### `components/timeline/`

| Component | Purpose |
|---|---|
| `Timeline` | Presentational timeline list: day groups + infinite scroll + new-content banner + loading/error/empty states |
| `TimelineDayGroup` | One calendar day's messages under a static date divider |
| `TimelineSkeleton` | Loading placeholder rows for the timeline |
| `MessageCard` | A single message: header (avatar/name/time/edited/save), text, media, webpage preview, forward box |
| `MessageMedia` | Media layout (single image vs 2/3-col grid) + lightbox trigger |
| `MediaThumb` | One media thumbnail: skeleton + aspect-ratio transition + file-chip fallback when no preview image |
| `WebPagePreview` | Telegram-style link preview card (thumbnail + site/title/description) |
| `Lightbox` | Fullscreen media viewer with prev/next navigation |
| `SavedMessageItem` | One saved message in the Saved view (full date line + `MessageCard`) |

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
| `BrowseChannelsDialog` | "Browse my channels" modal: search + multi-select + batch add |
| `BrowseChannelRow` | One selectable channel row in `BrowseChannelsDialog` |
| `SubscriptionRow` | One channel row on the Manage channels page: enable switch + actions menu + confirm dialogs |

> `components/ui/` holds generated shadcn/ui (new-york) primitives — intentionally **excluded**
> from this inventory. Don't list them here. Import `Button` from `@/components/ui/button`.

## Where things live (non-components)

- `pages/` — route screens (`TimelineView`, `RecordsView`, `FiltersView`, `SubscriptionsView`,
  `AppShell`, `AppLogin`, `TgLogin`).
- `hooks/` — data + behavior hooks (`useTimeline`, `useSubscriptions`, `useChannelFilter`,
  `useScrollToRead`, `useNewContent`, `useRefresh`, mutations, …).
- `lib/` — `api.ts` (typed fetch client), `types.ts` (backend JSON mirror), `format.ts`,
  `linkify.tsx`, `theme.tsx`, `unreadIndicator.tsx`, `queryClient.ts`, `utils.ts`.
