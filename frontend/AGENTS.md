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
| `CalendarPopover` | Date-filter popover; calendar limited to days that have content (channel-, source- or feed-scoped), with a Clear action |
| `ChannelAvatar` | Channel avatar from `/api/channels/{id}/avatar`; falls back to a colored initial (`letterOnly` forces the initial) |
| `ChannelFilter` + `AllChannelsHidden` | Dropdown to toggle per-channel visibility in multi-channel views; `AllChannelsHidden` is the all-filtered-out empty state |
| `ChannelFilterOption` | One row inside the `ChannelFilter` dropdown (avatar + name + message count) |
| `ConfirmDialog` | Generic confirm/cancel modal (destructive variant + pending state) |
| `DeviceList` | Authorized devices (bearer-token clients) in `SettingsDialog`: list + revoke with confirm |
| `HnDisplayModeMenu` | Top-N display-mode dropdown (top10/top20/half/all → PATCH the front feed's config); used by the `/s/hn` header + `HackerNewsSection` |
| `HnGlyph` | The HN "Y" mark in its orange square (size via className); shared by `HnCard`, the sidebar feed row, the `/s/hn` header, `HackerNewsSection`, the Subscriptions tab bar |
| `TgGlyph` | The Telegram paper-plane mark in its blue square, HnGlyph's size-pair; used by the Subscriptions tab bar |
| `XGlyph` | The X mark in its foreground-colored square (inverts with the theme), HnGlyph/TgGlyph's size-pair; used by the Subscriptions tab bar + X subscription rows |
| `PageHeader` + `IconBadge` | Unified reading-view top bar (leading icon + title + meta + right-aligned actions); `IconBadge` wraps a lucide icon in a muted circle |
| `SegmentedOption` | One icon-over-label button in a segmented control; shared by `SettingsDialog`'s theme + unread pickers |
| `SettingsDialog` | Settings modal: Telegram account, theme, unread-indicator mode, devices, lock app |
| `Sidebar` | Left navigation: nav links (Unread first, `/` = Unread, `/?all=1` = All), then one `SidebarSourceGroup` per source from `GET /api/sources`, settings |
| `SidebarSourceGroup` | One collapsible source section (collapse persisted via `useCollapsedSources`): the full-width header row links to `/s/:source` (+ unread badge when collapsed) with the collapse chevron as its own right-edge target, rows = the source's enabled subscriptions |
| `SidebarChannelLink` + `navLinkClass` | One Telegram channel link in a sidebar source group; also exports the shared nav-row className used by the top-level links |
| `SidebarHnFeedLink` | One HN feed link in the sidebar's Hacker News group (routes to `/s/hn` — v1 has a single feed) |
| `SidebarXFeedLink` | One X feed link in the sidebar's X group, routing to `/s/x/:feed` (X has many feeds, unlike HN): `XGlyph` for For You, the author's `XAvatar` for a followed account. For You's full feed is only ever here — the aggregate shows at most what its `XAggregateMenu` mode admits |
| `XAvatar` | An X author's avatar via `/api/x/avatar/{handle}` (unavatar proxy — bird carries no avatar URL); 404 falls back to a handle-seeded colored initial, ChannelAvatar-style |
| `Spinner` + `FullScreenSpinner` | Loading spinner (inline + full-screen) |
| `UnreadBadge` | Unread-count pill; renders nothing at 0, caps display at `999+` |

### `components/timeline/`

| Component | Purpose |
|---|---|
| `Timeline` | Presentational timeline list: day groups + infinite scroll + new-content banner + loading/error/empty states |
| `TimelineDayGroup` | One calendar day's items under a static date divider, dispatched by source |
| `TimelineSkeleton` | Loading placeholder rows for the timeline |
| `MessageCard` | A single Telegram item (takes the `TimelineItem` envelope; payload in `item.telegram`): header (avatar/name/time/save), text, media, webpage preview, forward box. The time is a button (full-date `title` tooltip) that opens the `ItemDetailPane` — the unified drawer entry on every message |
| `HnCard` | A Hacker News story card: title link (external URL, or comments page for self-posts), day-rank badge + score/comments/domain meta, an embedded `LinkPreviewCard` when the story carries an ingest-prefetched `hn.preview` with content, sanitized self-post HTML behind a char-threshold "more" clamp, muted job posts, scroll-to-read + save; the submitted-time button opens the `ItemDetailPane` |
| `XCard` | A single tweet: author identity as the subject (For You mixes ~46 authors per 50 tweets, so *who* is the orientation cue), body text (linkified; an `RT @orig:` prefix becomes a Retweeted caption, and a long-form post's `text` — which bird sets to the article title — is dropped in favor of the article card), `XMedia`, an `XQuoteCard`, and a footer line carrying `XVerdictBadge` on the far left, the like/RT/reply numbers next, and `XFeedbackButtons` on the right (the footer renders even when bird sent no metrics, so feedback is always offered). The time opens the `ItemDetailPane`; its tooltip also names the sighting time in For You, where that (not the post time) is the sort position |
| `XFeedbackButtons` | The thumb up/down pair on the tweet footer (`useFeedback`): clicking the highlighted side again clears the label, switching sides corrects it. Phase 3 *only* records the label — nothing is hidden or re-ranked by it; it is the training data the Phase 4 For You verdict learns from, which is why followed accounts are markable too. A down also opens the **reason row** (`为什么？` + the `FEEDBACK_REASONS` chips + a × to skip; the row is `flex-wrap`, so the taxonomy can grow — it did on 2026-07-27 — without overflowing a narrow card): a bare down labels the whole tweet, but the cause is usually one attribute of it, and one embedding averages topic/tone/author into a single point. The row is state about *this click*, not about the card — it closes on pick/skip/undo/side-switch and never re-nags an already-labeled tweet on re-render; skipping costs nothing (the label degrades to the bag-level one). The picked reason shows only in `ItemDetailInfo` |
| `XVerdictBadge` | The machine's read on a For You tweet (Phase 4) on the footer's left, facing `XFeedbackButtons` — "what it thinks" vs "what you think". `neutral` and `null` render **nothing**: neutral is the default answer, not a finding, and badging it would put a chip on every card. Clicking opens the `ItemDetailPane`, where the evidence is; the hover title summarizes it in one line |
| `XVerdictDetail` | The pane's 判定 row: the verdict, its score, the labeled neighbours that voted (author handle + distance, linking to the original), the per-channel 各通道投票 list when the meta carries the ensemble's `channels` block (`XVerdictChannel`: vote + score + C's flags / D's evidence tokens / A's account record — `@ibkr · 你踩过 6 次，赞过 0 次`, a sentence rather than weights, since the author prior reads no text and needs no metric to explain itself; channel B's evidence stays the top-level neighbours) and the `model@dims / algo` version. This trail is why Phase 4 badges instead of hiding — a verdict you can audit is one you can learn to trust, or catch being wrong and correct with a thumb |
| `XQuoteCard` | The quoted tweet embedded at depth 1: a bordered muted sub-card (the forward-box visual language) with its own author, text and media, linking to the original |
| `XMedia` | A tweet's media layout (single image at natural aspect vs 2/3-col square grid) + `XLightbox` trigger |
| `XMediaThumb` | One tweet media thumbnail: skeleton + aspect-ratio transition like `MediaThumb`, a play badge for video, images routed through `/api/preview/image` so reading a tweet never pings X from the reader's IP |
| `XLightbox` | Fullscreen viewer for a tweet's media — a sibling of `Lightbox`, not a generalization: X media are plain (proxied) origin URLs where Telegram's are message-scoped proxy paths, and X video is a link out rather than inline playback |
| `MessageMedia` | Media layout (single image vs 2/3-col grid) + lightbox trigger |
| `MediaThumb` | One media thumbnail: skeleton + aspect-ratio transition + file-chip fallback when no preview image |
| `WebPagePreview` | Telegram-style inline link preview card (thumbnail + site/title/description) |
| `ItemDetailPane` | The 条目详情 right-side slide-out (shadcn `Sheet`, Chinese copy) driven by the `itemDetailPane` context, which holds the open `TimelineItem` envelope. Top → bottom: `ItemDetailInfo` full-info block, the **item action row** right under it — 收藏 (`useSaveToggle`) + 转发 (no configured `forward_channel` → toast pointing to Settings, else opens `ForwardDialog`) on **every** source, with the TG-only `MessageStatsRow` sharing the row's left side. The pane mirrors its own save mutation in local state keyed on the item: the context holds the envelope captured at click time, so `is_saved` is a snapshot — fresh on open, and while open the button is the only writer. The 链接预览 section (TG message links, or a single URL for the other sources — the HN story URL, whose ingest-prefetched `story.preview` renders instantly, or a tweet's first outbound link via `xPreviewUrls`; a live `useUrlPreview` fetch runs only when there is a URL and no prefetched preview), and a footer with the original link (`tgMessageUrl` / HN comments / `xTweetUrl`) + the 隐藏 button (`useHideItem` → optimistic timeline removal, close, toast with 撤销 undo). Mounted once in `AppShell` |
| `ItemDetailInfo` | The pane's top full-info label/value list, source-dispatched: TG = channel (avatar/name/@username), author, publish/edit times, forward origin, media count, item key; HN = source/type, author, submitted + front-page times, score/comments, day + peak rank, domain, item key; X = author (avatar/name/@handle → profile), which feed it came from, publish + probe-fetch times, engagement, RT/quote/reply origin, media count, your 反馈 label when set (with its reason chip — the card shows the reason nowhere, so this is where you check what a past thumbs-down actually meant), verdict (Phase 4), item key |
| `MessageStatsRow` | Live views (Eye) / forwards (Repeat2) / `ReactionChip` list for the pane's TG message via `useMessageStats` (fetched fresh on every pane open, never stored); renders nothing while pending, on error, or when the channel exposes no stats |
| `ReactionChip` | One reaction bucket pill: emoji glyph ('custom'/'other' kinds degrade to a generic icon) + count; `chosen` (own reaction) highlights |
| `ForwardDialog` | "转发到我的频道" modal (deliberately Chinese copy), source-generic since 2026-07-27 — takes the whole `TimelineItem` and posts its key to `POST /api/forward`. Telegram: non-empty comment = quote message (text + t.me link), empty = native forward. Other sources have no Telegram original, so the server renders title + link into a new message and the copy says so ("留空则只发标题和链接…" instead of "留空则原样转发…") — the hint is the only source-conditional bit. Success toast carries an「打开」action opening the landed message |
| `LinkPreviewCard` | One self-fetched link preview (proxied image / Telegram-image fallback + site/title/description; `channelId` optional — absent for HN targets); shared by the pane and `HnCard`'s embedded preview |
| `Lightbox` | Fullscreen media viewer with prev/next navigation |
| `SavedMessageItem` | One saved item in the Saved view: full date line + the source's card (`MessageCard` / `HnCard` / `XCard`) |

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
| `TelegramSection` | The Telegram tab on the Subscriptions page: browse/add-by-handle actions + the `SubscriptionRow` channel list |
| `HackerNewsSection` | The Hacker News tab on the Subscriptions page: Front Page subscribe/unsubscribe, sampling pause switch, display-mode menu, status line (`/api/hn/status`) |
| `XSection` | The X tab on the Subscriptions page: add For You / an account by handle, the `XSubscriptionRow` list, and a two-line `/api/x/status` block — archive size + last probe push + parse errors (the data is pushed by the local probe, so this is where you find out the probe went quiet), plus an `XVerdictLine` explaining why the For You verdict is quiet: not configured, no sqlite-vec, or still counting down how many 👍/👎 remain before the cold-start gate opens |
| `XSubscriptionRow` | One X feed row: For You or a followed account (handle chip only once a real display name has been learned), archive size + last push, `XAggregateMenu` (For You only), pause switch, unsubscribe |
| `XAggregateMenu` | How much of For You joins the aggregate timeline — 不进 / 只进推荐的 / 全部并入 → PATCH the feed's `config.aggregate` (`HnDisplayModeMenu`'s sibling). Only For You gets one: a followed account is a choice already made. A setting rather than a constant because the right answer tracks how good the verdict currently is |

> `components/ui/` holds generated shadcn/ui (new-york) primitives — intentionally **excluded**
> from this inventory. Don't list them here. Import `Button` from `@/components/ui/button`.

## Where things live (non-components)

- `pages/` — route screens (`TimelineView`, `RecordsView`, `FiltersView`, `SubscriptionsView`,
  `AppShell`, `AppLogin`, `TgLogin`, `AuthorizeView` — the device-authorization page cold-loaded
  by the iOS app; only needs the cookie session, so `App.tsx` renders it before the TG gate).
- `hooks/` — data + behavior hooks (`useTimeline`, `useSources`, `useSubscriptions`,
  `useChannelFilter`, `useScrollToRead`, `useNewContent`, `useRefresh`, `useCollapsedSources`
  (sidebar collapse persistence), `useHnDisplayMode` (mode helpers + PATCH mutation),
  `useXAggregate` (For You's aggregate-mode labels + PATCH mutation; invalidates the
  timeline, the calendar and both unread badges, since the admitted set is computed at
  query time on the backend),
  `useMessageStats` (live pane stats, staleTime 0), `useAppMeta` + `useSetForwardChannel`
  (runtime app settings incl. the forward target channel), `useHideItem` + `useUnhideItem`
  (hide an item from every timeline via `POST /api/hidden`; optimistic removal + undo),
  `useFeedback` (up/down/clear an item's label via `/api/feedback`; optimistic in-place
  swap across the timeline *and* `['records']` caches, rolled back from the pre-click value.
  Verdict + reason move as one `Label` — the reason belongs to the verdict it explains, so
  they are cached, rolled back and cleared together and a correction can't strand a stale one),
  mutations, …). `useTimeline` / `useTimelineDays` / `useNewContent` / `useBulkRead` accept a
  `source` scope (the `/s/:source` views) plus a `feed` scope for multi-feed sources
  (the `/s/:source/:feed` route — X's For You / one followed account).
- `lib/` — `api.ts` (typed fetch client), `types.ts` (backend JSON mirror), `format.ts`,
  `sources.ts` (source labels, `hnCommentsUrl`, `xTweetUrl` / `xProfileUrl` / `xPreviewUrls`,
  `X_FORYOU_FEED`, sub-row labels, `FEEDBACK_REASONS` + `FEEDBACK_REASON_LABELS` — shared by
  the card that asks and the pane that reports the answer, so the two can't drift),
  `sanitize.ts` (DOMPurify
  wrapper for HN self-post HTML), `linkify.tsx`, `extractUrls.ts` (shared URL
  regex/extraction for linkify + the detail pane), `itemDetailPane.tsx` (the detail pane's
  context: the open `TimelineItem` envelope), `theme.tsx`, `unreadIndicator.tsx`,
  `queryClient.ts`, `utils.ts`.

## Debugging

### Walk through the real app (behind the auth gate)

For anything the harness below can't show — real data, routing, mutations hitting the
backend — run `scripts/dev-browser-login.sh [session]` from the repo root. It injects a
logged-in cookie into an `agent-browser` profile without the app password ever touching a
command line, so `agent-browser --session <session> open http://localhost:5792/...` lands
on the timeline instead of the unlock screen. See the `scripts/` table in the root
`AGENTS.md`; note the dev backend must be running with `--reload` or you verify stale code.

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
