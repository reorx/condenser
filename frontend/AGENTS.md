# Condenser Frontend — Agent Guide

React 19 + Vite 6 + TS (strict) + Tailwind v4 + shadcn/ui (new-york) + TanStack Query v5 +
React Router v7, pnpm. This file is the **inventory**: one row per component, page, hook
and lib module. Behavior that spans components (auth gate, scroll-to-read, the detail
pane, annotations, cache rules, search, Vibe Reader, PWA) is in `kb/docs/frontend.md`. A
module's reasoning lives in its docstring and inline comments; read them before editing.

## Rules

- **Keep the inventory in sync.** Adding, removing, renaming, moving or repurposing a
  component, hook or lib module updates its row in the same change. One line, purpose
  first; the why goes in the file's docstring, not here.
- **No inline anonymous components in `.map()`.** A loop body renders a referenced
  component; if it needs custom markup, extract one first.
- **Reusable, loop-rendered or sizeable pieces live in `components/`**: feature-specific
  ones in the feature subfolder, cross-feature ones at the root. Purpose-specific siblings
  (the sidebar row types, `Lightbox` vs `XLightbox`) stay separate instead of merging into
  one prop-heavy component.
- `components/ui/` is generated shadcn/ui and is not listed. Import from
  `@/components/ui/<name>`.
- UI copy mixes English and Chinese; the detail pane and its dialogs are deliberately
  Chinese. Match the copy around what you edit.
- Several surfaces have an iOS twin (named in the row). A behavior change there usually
  needs the Swift side too; see `kb/docs/ios.md`.

## Components

### `components/` (cross-feature)

| Component | Purpose |
|---|---|
| `Sidebar` | Nav links (`/` = Unread, `/?all=1` = All, Saved, Forwards, Search, Filters, Subscriptions), one `SidebarSourceGroup` per source from `GET /api/sources`, settings |
| `SidebarSourceGroup` | Collapsible source section (`useCollapsedSources`): header links to `/s/:source`; rows dispatched per source by the private `SidebarSubLink` |
| `SidebarChannelLink` + `navLinkClass` | A Telegram channel row; also exports the shared nav-row className |
| `SidebarHnFeedLink` | The HN row → `/s/hn` (single feed) |
| `SidebarXFeedLink` | An X feed row → `/s/x/:feed`: `XGlyph` for For You / Following, `XAvatar` for an account. The only place a feed shows in full; the aggregate admits per `XAggregateMenu` |
| `SidebarRssFeedLink` | An RSS feed row → `/s/rss/:feed`, where `feed` is the percent-encoded feed URL (the URL is the key) |
| `PageHeader` + `IconBadge` | Reading-view top bar (icon, title, meta, actions); `IconBadge` is a lucide icon in a muted circle |
| `CalendarPopover` | Date filter; only days with content (channel-, source- or feed-scoped) are selectable |
| `ChannelFilter` + `AllChannelsHidden` | Per-channel visibility dropdown on multi-channel views; the all-hidden empty state |
| `ChannelFilterOption` | One row in `ChannelFilter` |
| `ChannelAvatar` / `XAvatar` | Avatars through the backend proxies, falling back to a colored initial |
| `HnGlyph` / `TgGlyph` / `XGlyph` / `RssGlyph` | Source marks in colored squares, a size-matched set (`RssGlyph` sizes in `em`) |
| `HnFeedRulesMenu` | The HN front feed's three **admission** rules (day quota, score floor, peak-rank gate) in one dropdown. PATCHes one key at a time because the server merges; rules affect future rounds only |
| `SettingsDialog` | Telegram account, theme, unread mode, 语言 (the global language list), forward channel, Vibe Reader switch, devices, lock. Its **Connect Telegram** link to `/connect-telegram` is the only way into the Telegram login once the gate lets a multi-source install through |
| `LanguageOption` | One pill in Settings' 语言 list; a toggle PATCHes the whole list |
| `SegmentedOption` | One icon-over-label segment (Settings' theme and unread pickers) |
| `DeviceList` | Authorized device tokens in Settings: list + revoke |
| `ConfirmDialog` | Generic confirm modal (destructive variant, pending state) |
| `VibeReaderPrompt` | Renders nothing; raises the one-time 「开启联动？」 toast when the extension says hello with the link off. Its dismissal is the only link state condenser stores |
| `VibeReaderDot` | Dot on the Settings row: green = linked, grey = bridge present but unlinked, absent = no bridge |
| `UnreadBadge` | Unread pill; nothing at 0, caps at `999+` |
| `Spinner` + `FullScreenSpinner` | Inline and full-screen spinners |

### `components/timeline/`

| Component | Purpose |
|---|---|
| `Timeline` | Presentational list: day groups, infinite scroll, new-content banner, loading / error / empty |
| `TimelineDayGroup` | One day's items under a static divider, dispatched by source |
| `TimelineSkeleton` | Loading placeholder rows |
| `DatedItemRow` | One item under its own date line, dispatched by source; for Saved, Search and Forwards, which jump across days |
| `MessageCard` | Telegram item (`item.telegram`): header, text, media, webpage preview, the forwarded-in box |
| `HnCard` | HN story: title link, AI summary, admission-slot badge (`hn.day_rank`, the stored `qualified_rank`), meta, prefetched `LinkPreviewCard`, clamped self-post HTML. Links carry `hnLinkAttrs` for Vibe Reader |
| `RssCard` | Feed entry: feed name, title link, then the AI summary or else the server's plain-text excerpt (lists carry no HTML). 「查看全文」 opens the detail pane |
| `XCard` | Tweet: author as subject, linkified body (RT caption; a long-form post shows its article card), `XMedia`, `XQuoteCard`, and a footer `XVerdictBadge` · metrics · `XFeedbackButtons` that always renders |
| `XQuoteCard` | Quoted tweet at depth 1, in the forward-box visual language |
| `MessageMedia` / `MediaThumb` | Telegram media layout (single vs 2/3-col grid) / one thumbnail with skeleton, reserved aspect and file-chip fallback |
| `XMedia` / `XMediaThumb` | Tweet media layout / one thumbnail (video play badge; images via `/api/preview/image`) |
| `Lightbox` / `XLightbox` | Fullscreen viewers: Telegram's message-scoped proxy paths / X's proxied origin URLs, where video links out |
| `WebPagePreview` | Telegram's own inline link preview |
| `LinkPreviewCard` | A self-fetched link preview; used by the pane and `HnCard` |
| `AiSummaryBlock` + `displaySummary` | The AI-summary quote block on every surface (twin of iOS `AiSummaryBlock`). `displaySummary` is the "has a summary" rule for callers that branch on it |
| `XFeedbackButtons` | 👍 / 👎 on the tweet footer (`useFeedback`); clicking the lit side clears. A 👎 opens a one-shot reason-chip row. See `kb/docs/x-feedback.md` |
| `XVerdictBadge` | The verdict chip on a For You tweet; `neutral` and `null` render nothing. Click opens the pane |
| `XVerdictDetail` | The pane's 判定 row: score, voting neighbours, per-channel votes, model version |
| `ForwardedBadge` | 「我转发过这条」 on every card's time line, from `forwarded_by_me` (**not** `telegram.is_forwarded`, the opposite direction) |
| `AnnotationBadge` | 「我在这条上写过东西」 (note or highlight, `hasNotes`) on the same line |
| `VibeReaderBadge` | Vibe Reader's status for the card's last-touched outbound link (`useVibeReaderStatus`) |
| `ItemDetailPane` | The 条目详情 sheet, mounted once in `AppShell`: info, save / note / forward, annotatable body, link previews, original link, 隐藏. Structure: `kb/docs/frontend.md` |
| `ItemDetailInfo` | The pane's per-source label/value block; the only place some fields show (HN admission time, an X down-reason, the verdict) |
| `ItemDetailBody` | The pane's body inside `AnnotatedText`: TG text, HN self-post, `xBodyText`, or the RSS / X article fetched lazily |
| `MessageStatsRow` + `ReactionChip` | Live TG views, forwards and reactions for the pane (`useMessageStats`, never stored) |
| `ItemNoteDialog` | 条目评论 editor (iOS `ItemNoteSheet`): whole-text overwrite, saving empty deletes. 保存并转发 saves first, then opens `ForwardDialog` prefilled |
| `ForwardDialog` | 转发到我的频道 for any source (`POST /api/forward`). Patches `forwarded_by_me` on success unless the response says `recorded: false` |

### `components/annotations/`

| Component | Purpose |
|---|---|
| `AnnotatedText` | The highlight layer: locates stored quotes in the rendered DOM and paints them with the CSS Custom Highlight API, never touching React's nodes. Selection floats 「高亮」; clicking a highlight opens 评论 / 删除 |
| `AnnotationCommentDialog` | One highlight's comment (iOS `AnnotationCommentSheet`); saving empty deletes the comment, not the highlight |
| `AnnotationOrphans` | 「失效的高亮」: highlights whose quote the text no longer contains, listed rather than dropped |

### `components/search/`

| Component | Purpose |
|---|---|
| `SearchFilters` | The row under the box: scope menu, All / Unread / Saved chips, sort |
| `SearchScopeMenu` + `SearchScopeOption` | Scope picker (all / a source / one subscription, paused ones included) from the `GET /api/sources` tree, one flat menu. Also exports `sourceGlyph` |
| `SearchFilterChip` | One header-scale icon + label chip |
| `SearchResults` | Flat `DatedItemRow`s, offset-paged. Not wired to scroll-to-read; a 422 renders as "nothing searchable" |

### `components/forwards/`

| Component | Purpose |
|---|---|
| `ForwardRecordRow` | One `/forwards` row: the record's time, target channel, comment and actions above the item's `DatedItemRow`, or the metadata alone when there is no snapshot. Delete removes only the local record |

### `components/filters/`

| Component | Purpose |
|---|---|
| `CreateFilterDialog` | Create a keyword filter: scope, channel, keyword, live preview |
| `ScopeOption` | A selectable scope card (Global / Single channel) |
| `ChannelPicker` + `ChannelPickerOption` | Searchable single-channel selector / one row in it |
| `FilterPreviewResult` + `FilterPreviewSample` | Preview panel (loading / error / summary + samples) / one matched sample |
| `HighlightedText` | Wraps case-insensitive keyword hits in `<mark>` |
| `FilterGroupSection` + `FilterGroup` type | One scope section on the Filters page; the type is used by `FiltersView.groupFilters` |
| `FilterKeywordChip` | One removable keyword pill |

### `components/subscriptions/`

| Component | Purpose |
|---|---|
| `TelegramSection` | Telegram tab: browse / add-by-handle actions and the `SubscriptionRow` list |
| `SubscriptionRow` | One channel: enable switch, actions menu, confirm dialogs |
| `AddByHandleDialog` | Subscribe to a public channel by @handle or t.me link |
| `BrowseChannelsDialog` + `BrowseChannelRow` | Multi-select from the account's joined channels / one row |
| `HackerNewsSection` | HN tab: subscribe, sampling pause, `HnFeedRulesMenu`, status line |
| `XSection` | X tab: add For You / Following / an account, the `XSubscriptionRow` list, and the probe status block (last push, parse errors, `XVerdictLine` on why the verdict is quiet) |
| `XSubscriptionRow` | One X feed: archive size, last push, per-feed filter counts, `XLangFilterToggle`, `XAggregateMenu`, pause, unsubscribe |
| `XAggregateMenu` | How much of For You / Following joins the aggregate (`config.aggregate`); Following has no "recommended only", since it is never judged |
| `XLangFilterToggle` | For You obeys the global language list (`config.lang_filter`, ingest-time); warns when no language is picked |
| `RssSection` | RSS tab: add by URL, OPML import (read in the browser), the sorted `RssSubscriptionRow` list, a two-line status (polling, summary pipeline). Adaptive `refetchInterval` and sort tiers: see the file |
| `RssSubscriptionRow` | One feed, Miniflux-style: facts line, verbatim error, Refresh, pause, unsubscribe. Abnormal (yellow, 「异常」), failing (red) and recovered-with-warning (amber) are kept apart |

## Pages (`pages/`)

| Page | Purpose |
|---|---|
| `AppShell` | Layout (desktop sidebar, mobile drawer, content). Mounts `ItemDetailPane` and `VibeReaderPrompt`, calls `installVibeReader(document)` |
| `TimelineView` | Every timeline route: `/`, `/c/:channelId`, `/s/:source`, `/s/:source/:feed`. Owns the timeline query and the channel filter |
| `RecordsView` | `/saved` |
| `ForwardsView` | `/forwards`, the forward log, offset-paged |
| `SearchView` | `/search`: a debounced local draft; the URL holds the committed query and filters |
| `FiltersView` | `/filters`, keyword filters grouped by scope |
| `SubscriptionsView` | `/subscriptions`, one tab per source |
| `AppLogin` / `TgLogin` | App-password unlock / Telegram step login (also at `/connect-telegram`) |
| `AuthorizeView` | The device-authorization page the iOS app loads; needs only the cookie, so `App.tsx` renders it before the Telegram gate |

## Hooks (`hooks/`)

| Hook | Purpose |
|---|---|
| `useTgStatus` | The `tg-status` query, which is the auth gate |
| `useSources` | The `GET /api/sources` tree (sidebar, search scope, the Telegram gate) |
| `useSubscriptions` + `useChannelLabels` | Telegram subscriptions; the channel id → title join timeline items need |
| `useSubscriptionMutations` | Enable / delete a Telegram subscription |
| `useTimeline` / `useTimelineDays` / `useNewContent` / `useBulkRead` | Timeline pages / calendar days / the new-content poll / mark all read. Each takes `source` and `feed` scopes |
| `useInfiniteScrollSentinel` | The shared paged-list tail sentinel (Timeline, SearchResults, ForwardsView) |
| `useScrollToRead` | 看过即读 |
| `useChannelFilter` | Per-channel visibility state for multi-channel views |
| `useRefresh` | Refresh / fetch-older / reset one channel; refresh all |
| `useCollapsedSources` | Sidebar collapse persistence |
| `useSaveToggle` / `useHideItem` + `useUnhideItem` / `useFeedback` / `useNote` | Optimistic item mutations, patched across every item cache through `lib/itemCaches.ts` and rolled back on error |
| `useItemAnnotations` | The pane's highlight model (iOS `ItemAnnotationsModel`) |
| `useForwards` + `useDeleteForward` | The paged `['forwards']` log; delete is not optimistic |
| `useSearch` + `scopeParams` | The paged `['search']` query; `scopeParams` is the one scope → API parameter translation |
| `useRssArticle` / `useXArticle` | An article body for the pane, fetched on demand |
| `useLinkPreviews` + `useUrlPreview` | A Telegram message's previews / one URL's preview |
| `useMessageStats` | Live Telegram stats for the pane (`staleTime: 0`) |
| `useAppMeta` + `useSetForwardChannel` / `useSetLanguages` | Runtime app settings |
| `useAllFilters` + `useCreateFilter` / `useDeleteFilter` | Keyword filter CRUD |
| `useHnFeedRules` | HN admission-rule options, defaults, tooltip summary, one-key PATCH |
| `useXAggregate` | X aggregate-mode options + PATCH |
| `useVibeReader` | The extension bridge's `available` / `linked` / `version` + `setLink` |

## Lib (`lib/`)

| Module | Purpose |
|---|---|
| `api.ts` | Typed fetch client (`ApiError`, `errorMessage`) and proxy URL builders |
| `types.ts` | Backend JSON mirror |
| `queryClient.ts` | Query client and the global 401 handler |
| `itemCaches.ts` | Every cache that holds item envelopes, plus `patchItem` / `removeItem` / `findItem` / `invalidateItemLists` |
| `itemDetailPane.tsx` | Context holding the pane's open envelope |
| `sources.ts` | Source and row labels, URL builders (`hnCommentsUrl`, `xTweetUrl`, …), X synthetic feed keys, `FEEDBACK_REASONS` |
| `xUrls.ts` | t.co expansion and `xBodyText`, the tweet display text `XCard` and the pane share |
| `format.ts` | Date parsing and labels (UTC day keys), `tgMessageUrl`, `channelName`, `compactNumber` |
| `linkify.tsx` / `extractUrls.ts` | Link rendering / URL extraction shared by linkify and the pane |
| `sanitize.ts` | DOMPurify wrapper for HN, RSS and X article HTML; `proxyImages` |
| `annotate.ts` | Highlight quote relocation, a behavior-identical port of Kit's `Annotations.swift`; `selectionContext`, `hasNotes` |
| `domText.ts` | The DOM half of highlights: text index, offset ↔ Range, selection and caret readers |
| `vibeReader.ts` | The Vibe Reader link mode: protocol copy, bridge store, click delegate, per-URL status |
| `theme.tsx` / `unreadIndicator.tsx` | Theme and unread-indicator providers |
| `swUpdate.ts` / `swDenylist.ts` / `pwa.ts` | PWA update prompt / service-worker navigation denylist / standalone window size |
| `utils.ts` | `cn` |

## Verifying UI changes

- **Real app**: `scripts/dev-browser-login.sh [session]` from the repo root logs an
  `agent-browser` profile in, so `http://localhost:5792/...` opens past the unlock screen.
  The dev backend must run with `--reload`, or you verify stale code.
- **Preview harness**, no backend or auth: `/preview.html`, dev server only.
  `src/preview/main.tsx` provides theme, unread indicator and query client;
  `PreviewApp.tsx` adds the detail-pane provider, the gallery and a theme / unread toolbar.
  Add a case there for the state you are checking. `mocks.ts` has `makeMsg`, `makeItem`,
  `makeHnItem`, `makeXItem`, `makeRssItem`. Avatars 404 into initials there, as expected.
- **Vibe Reader without the extension**: the harness listens to the bridge, so posting
  `{ns:'vibe-reader', v:1, type:'vibe-reader:hello', linked:true}` and then
  `vibe-reader:status` messages through `agent-browser eval` lights `VibeReaderBadge`.

```bash
agent-browser --session cond-preview open http://127.0.0.1:5792/preview.html
agent-browser --session cond-preview wait --text "<text on the page>"
agent-browser --session cond-preview screenshot /abs/path/shot.png --full   # --full needs an explicit path
agent-browser --session cond-preview find text "theme:" click               # toggle dark
agent-browser --session cond-preview close
```

Element-scoped screenshots are not supported. For a detail like an 8px dot, crop and
upscale the PNG with Pillow (`uv run --with pillow`).
