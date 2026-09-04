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
| `AppShell` *(in `pages/`)* | App layout: desktop sidebar + mobile drawer + content column. Also where the Vibe Reader link mode is installed (`installVibeReader(document)`: bridge listener + the one click/auxclick delegate covering every new-tab link on every route + the mount-time hello) and where `VibeReaderPrompt` mounts |
| `CalendarPopover` | Date-filter popover; calendar limited to days that have content (channel-, source- or feed-scoped), with a Clear action |
| `ChannelAvatar` | Channel avatar from `/api/channels/{id}/avatar`; falls back to a colored initial (`letterOnly` forces the initial) |
| `ChannelFilter` + `AllChannelsHidden` | Dropdown to toggle per-channel visibility in multi-channel views; `AllChannelsHidden` is the all-filtered-out empty state |
| `ChannelFilterOption` | One row inside the `ChannelFilter` dropdown (avatar + name + message count) |
| `ConfirmDialog` | Generic confirm/cancel modal (destructive variant + pending state) |
| `DeviceList` | Authorized devices (bearer-token clients) in `SettingsDialog`: list + revoke with confirm |
| `HnFeedRulesMenu` | Which HN stories are **let in** to the timeline, in one dropdown with three groups: the day quota (top10/top20/half/all), the score floor and the front-page peak-rank gate → PATCH the front feed's config **one key at a time** (the server merges; a whole-value write would disarm the other two). One trigger rather than three because the header has to fit on a phone, and the quota is the knob you actually change while the floors are set once — so the trigger shows the quota and the tooltip names all three. Since schema v14 these are **admission** rules, not view filters: they decide what future rounds admit, and a story already on the timeline stays there whatever you set — which the copy has to keep saying, because it is the one thing about them a reader can get wrong. The peak-rank gate ships **off** (see `useHnFeedRules`). Used by the `/s/hn` header + `HackerNewsSection` |
| `HnGlyph` | The HN "Y" mark in its orange square (size via className); shared by `HnCard`, the sidebar feed row, the `/s/hn` header, `HackerNewsSection`, the Subscriptions tab bar |
| `TgGlyph` | The Telegram paper-plane mark in its blue square, HnGlyph's size-pair; used by the Subscriptions tab bar |
| `XGlyph` | The X mark in its foreground-colored square (inverts with the theme), HnGlyph/TgGlyph's size-pair; used by the Subscriptions tab bar + X subscription rows |
| `RssGlyph` | The RSS broadcast mark in its amber square, HnGlyph/TgGlyph/XGlyph's size-pair — a lucide icon rather than a letter, because RSS's identity *is* that shape; sized in `em` so it tracks whatever type scale the caller sets. Used by the timeline card, the sidebar feed rows, the `/s/rss` header, the Subscriptions tab bar and the search scope menu |
| `PageHeader` + `IconBadge` | Unified reading-view top bar (leading icon + title + meta + right-aligned actions); `IconBadge` wraps a lucide icon in a muted circle |
| `LanguageOption` | One language checkbox-pill in `SettingsDialog`'s 语言 multi-select (toggle → immediate PATCH of the whole list) |
| `SegmentedOption` | One icon-over-label button in a segmented control; shared by `SettingsDialog`'s theme + unread pickers |
| `SettingsDialog` | Settings modal: Telegram account, theme, unread-indicator mode, 语言 (global language whitelist — X For You's ingest filter reads it), forward channel, **Vibe Reader** (status line + a `Switch` mirroring the extension's own link toggle — disabled without a bridge, and it never flips optimistically: it asks via `setLink`, and `vibe-reader:link` answers; a hello at a foreign protocol version is named as such instead of offering a switch that cannot work), devices, lock app. The Telegram row is status-aware: connected → phone + Disconnect, disconnected → a **Connect Telegram** link to `/connect-telegram`. That link is not decoration — since the gate stopped walling off multi-source installs (see `pages/` below), it is the only remaining entry to the Telegram login |
| `Sidebar` | Left navigation: nav links (Unread first, `/` = Unread, `/?all=1` = All, then Saved / Forwards / Search / Filters / Subscriptions — Forwards sits next to Saved because both are archives of *what I did to an item*, one bookmarked and one published), then one `SidebarSourceGroup` per source from `GET /api/sources`, settings |
| `SidebarSourceGroup` | One collapsible source section (collapse persisted via `useCollapsedSources`): the full-width header row links to `/s/:source` (+ unread badge when collapsed) with the collapse chevron as its own right-edge target, rows = the source's enabled subscriptions, each dispatched to its source's own link component by the private `SidebarSubLink` (four sources address their subscriptions differently — a channel id, a feed key, a feed URL — so the row types stay separate and one function picks between them) |
| `SidebarChannelLink` + `navLinkClass` | One Telegram channel link in a sidebar source group; also exports the shared nav-row className used by the top-level links |
| `SidebarHnFeedLink` | One HN feed link in the sidebar's Hacker News group (routes to `/s/hn` — v1 has a single feed) |
| `SidebarRssFeedLink` | One feed link in the sidebar's RSS group, routing to `/s/rss/:feed`. The feed key is a **URL**, percent-encoded into the path — that leaves no literal slash, so it occupies one route segment. Ugly in the address bar and right everywhere else: the URL *is* this source's key (the reader typed it), and inventing a second id for a prettier route would mean keeping the two in sync forever |
| `SidebarXFeedLink` | One X feed link in the sidebar's X group, routing to `/s/x/:feed` (X has many feeds, unlike HN): `XGlyph` for a whole-timeline feed (For You / Following — no account behind it, so no avatar), the author's `XAvatar` for a followed account. A feed's *full* contents are only ever here — the aggregate shows at most what its `XAggregateMenu` mode admits |
| `XAvatar` | An X author's avatar via `/api/x/avatar/{handle}` (unavatar proxy — bird carries no avatar URL); 404 falls back to a handle-seeded colored initial, ChannelAvatar-style |
| `VibeReaderPrompt` | Renders nothing; raises the one-time「检测到 Vibe Reader，开启联动？」sonner toast when the extension's bridge first says hello with the link off (plan 2026-09-02 §2.2). 开启 only *asks* the extension (`setLink`) — the switch lives there — and 不再提示 writes `condenser-vibe-reader-prompt = dismissed`, the single piece of link state condenser keeps. Once per page load: the sidepanel closing and reopening is not news. Mounted once in `AppShell` |
| `VibeReaderDot` | The 6px dot on the sidebar's Settings row: green = linked, grey = bridge present but the link is off, absent when there is no bridge; `title` spells the state out |
| `Spinner` + `FullScreenSpinner` | Loading spinner (inline + full-screen) |
| `UnreadBadge` | Unread-count pill; renders nothing at 0, caps display at `999+` |

### `components/timeline/`

| Component | Purpose |
|---|---|
| `Timeline` | Presentational timeline list: day groups + infinite scroll + new-content banner + loading/error/empty states |
| `TimelineDayGroup` | One calendar day's items under a static date divider, dispatched by source |
| `TimelineSkeleton` | Loading placeholder rows for the timeline |
| `MessageCard` | A single Telegram item (takes the `TimelineItem` envelope; payload in `item.telegram`): header (avatar/name/time/save), text, media, webpage preview, forward box. The time is a button (full-date `title` tooltip) that opens the `ItemDetailPane` — the unified drawer entry on every message |
| `HnCard` | A Hacker News story card: title link (external URL, or comments page for self-posts) — both it and the comments link carry `hnLinkAttrs` (`data-vr-hn-*`, plan 2026-09-02 §2.3) so the Vibe Reader delegate can hand the extension the story instead of an Algolia search; attributes only, no handlers — the **AI summary** under it when the server wrote one (schema v19 `hn.summary`: 2-3 sentences on the article + 1-2 on the thread — `RssCard`'s exact paragraph + 「AI 摘要」 chip, so machine words look the same on every card; under it the embedded preview **drops its description**, which the summary was written from, and a preview that had nothing else is not drawn at all), admission-slot badge (`hn.day_rank` — the wire keeps the pre-v14 name, but since v14 it is the stored `qualified_rank` and no longer jumps between two refreshes) + score/comments/domain meta, an embedded `LinkPreviewCard` when the story carries an ingest-prefetched `hn.preview` with content, sanitized self-post HTML behind a char-threshold "more" clamp, muted job posts, scroll-to-read + save; the submitted-time button opens the `ItemDetailPane` |
| `RssCard` | One feed entry: the feed name as the header subject (falling back to the URL, scheme stripped — with 100 feeds a row is told apart by host), the title as the main act linking to the article, and a body that is the **LLM summary when there is one** and the article's plain-text excerpt when there is not (plan §0.4). Which of the two you are reading is marked with a small 「AI 摘要」 chip, because a summary is a machine's paraphrase and a card that hides that is lying quietly. Since 2026-08-23 the list payload carries **no HTML at all** — a ~500-char `content_excerpt` instead (feed bodies averaged 13.9KB and topped out at 7.1MB, thirty per page) — so the card renders prose the backend already stripped. Since 2026-08-24 the article does **not** expand in place: 「查看全文」 opens the `ItemDetailPane`, which fetches and renders it (`ItemDetailBody`) — the iOS arrangement (detail = the sheet, card = the scan surface), and the pane is where highlighting lives, so there is exactly one rendering of the article to annotate. The button appears on the server's `content_truncated` (only the cutting side knows what was left behind) — or always under a summary, which hides the excerpt entirely and would otherwise leave no path from the card to the source text. Time opens the `ItemDetailPane`; its tooltip names the sort position too whenever the feed's declared time was not believed. An entry with no link renders a plain title |
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
| `ItemDetailPane` | The 条目详情 right-side slide-out (shadcn `Sheet` widened to `sm:max-w-xl` — since the RSS article moved in here it is a reading surface, Chinese copy) driven by the `itemDetailPane` context, which holds the open `TimelineItem` envelope. Top → bottom: `ItemDetailInfo` full-info block, the **item action row** right under it — 收藏 (`useSaveToggle`) + 评论 (opens `ItemNoteDialog`; indigo-filled when a note exists) + 转发 (no configured `forward_channel` → toast pointing to Settings, else opens `ForwardDialog`) on **every** source, with the TG-only `MessageStatsRow` sharing the row's left side. The pane mirrors its own save and note mutations in local state keyed on the item **object**: the context holds the envelope captured at click time, so `is_saved`/`note` are snapshots — fresh on open, and while open these buttons are the only writers; a reopen hands over a different object and the overrides drop on identity. Then the scrollable middle: the annotatable body (`ItemDetailBody` + `useItemAnnotations`) followed by the 链接预览 section (TG message links, or a single URL for the other sources — the HN story URL, whose ingest-prefetched `story.preview` renders instantly, or a tweet's first outbound link via `xPreviewUrls`; a live `useUrlPreview` fetch runs only when there is a URL and no prefetched preview), and a footer with the original link (`tgMessageUrl` / HN comments / `xTweetUrl`) + the 隐藏 button (`useHideItem` → optimistic timeline removal, close, toast with 撤销 undo). The note dialog's 保存并转发 chains into `ForwardDialog` with the just-saved note prefilled. Mounted once in `AppShell` |
| `ItemDetailInfo` | The pane's top full-info label/value list, source-dispatched: TG = channel (avatar/name/@username), author, publish/edit times, forward origin, media count, item key; HN = source/type, author, submitted / front-page (上榜) / **admission (入选)** times — the gap between the last two is what the story spent earning its slot, and the pane is the only place a reader can see it; a story that was never admitted (search reaches those) has no 入选时间 row at all — score/comments (the comments link carries `hnLinkAttrs`, like the pane's footer link), 当日入选第 N 条 + peak rank, domain, the AI 摘要 row when the story has one, item key; X = author (avatar/name/@handle → profile), which feed it came from, publish + probe-fetch times, engagement, RT/quote/reply origin, media count, your 反馈 label when set (with its reason chip — the card shows the reason nowhere, so this is where you check what a past thumbs-down actually meant), verdict (Phase 4), item key |
| `MessageStatsRow` | Live views (Eye) / forwards (Repeat2) / `ReactionChip` list for the pane's TG message via `useMessageStats` (fetched fresh on every pane open, never stored); renders nothing while pending, on error, or when the channel exposes no stats |
| `ReactionChip` | One reaction bucket pill: emoji glyph ('custom'/'other' kinds degrade to a generic icon) + count; `chosen` (own reaction) highlights |
| `ForwardDialog` | "转发到我的频道" modal (deliberately Chinese copy), source-generic since 2026-07-27 — takes the whole `TimelineItem` and posts its key to `POST /api/forward`. Telegram: non-empty comment = quote message (text + t.me link), empty = native forward. Other sources have no Telegram original, so the server renders title + link into a new message and the copy says so ("留空则只发标题和链接…" instead of "留空则原样转发…") — the hint is the only source-conditional bit. Success toast carries an「打开」action opening the landed message. Since 2026-08-23 a forward is also *recorded* server-side (schema v17), so success patches `forwarded_by_me: true` across the item caches and invalidates `['forwards']` — the badge lights without a refetch. Unless the response says `recorded: false` (the message went out but the server lost the record write): then a warning toast says so and nothing is patched, because a badge lit on a lost record silently un-lights on the next fetch. `initialComment` prefills the box (the note dialog's 保存并转发 chain); editing it changes only the outgoing message, never the stored note |
| `ForwardedBadge` | The 「我转发过这条」 mark on the time line of all four cards: a small `Repeat2` (`MessageStatsRow`'s icon for forward *counts* — same vocabulary, other direction) with a native `title`. Reads `item.forwarded_by_me`, **not** `telegram.is_forwarded` — that one means "this post was forwarded *into* the channel I read", the opposite direction, and the two sit on the same card |
| `LinkPreviewCard` | One self-fetched link preview (proxied image / Telegram-image fallback + site/title/description; `channelId` optional — absent for HN targets); shared by the pane and `HnCard`'s embedded preview |
| `Lightbox` | Fullscreen media viewer with prev/next navigation |
| `ItemDetailBody` | The pane's body section — the item's own text rendered **annotatable** (wrapped in `AnnotatedText`), the web counterpart of iOS's four detail sheets growing highlights. Per source, mirroring iOS's choices: TG = the message text (linkified), HN = the sanitized self-post HTML (an external-link story has none), X = the derived display text (`xBodyText` — the same derivation `XCard` prints, so quotes relocate across surfaces and platforms), RSS = the full article, fetched lazily (`useRssArticle`; a saved snapshot's inline `content` skips the fetch) with the AI summary block above it (indigo, deliberately **not** annotatable — machine words; iOS's rule). While the article is not in hand the excerpt keeps the section honest and highlighting stays off (a quote made against the excerpt would relocate against different text); a failed fetch keeps the excerpt + 「正文加载失败」. Renders nothing only when there is no body *and* nothing was ever highlighted — with annotations but no body the layer still mounts so the orphan list can say so |
| `ItemNoteDialog` | 条目评论 editor (iOS `ItemNoteSheet`'s counterpart): whole-text overwrite semantics — every save sends the full trimmed text, clearing and saving **is** the delete, no separate button (the placeholder says so on an existing note). `useNote` persists + patches every item cache. 保存并转发 saves **first** and only then chains into `ForwardDialog` with the note prefilled — text that went to Telegram but not into the notebook is the surprise this ordering exists to prevent; disabled on an empty note (nothing to prefill) |
| `AnnotationBadge` | The 「我在这条上写过东西」 mark (note **or** highlight, `hasNotes`) on the time line of all four cards — `ForwardedBadge`'s indigo sibling (`MessageSquareText`, native `title`). A mark, not a button: reading/editing happens in the detail pane, matching iOS |
| `DatedItemRow` | One item under a full date line, dispatched by source (`MessageCard` / `HnCard` / `XCard` / `RssCard`). The row shape for the two views that are *not* a timeline — Saved and Search — both of which jump across days and sources, so each item states its own date instead of sitting under a shared day divider |

### `components/annotations/`

| Component | Purpose |
|---|---|
| `AnnotatedText` | The highlight layer (schema v18): renders its children untouched, then works on the DOM — `buildTextIndex` flattens the rendered text nodes, `locateAnnotation` (the iOS relocation port) finds each stored quote, and the CSS Custom Highlight API paints them (`::highlight(condenser-annotation)` in `index.css`) **without mutating nodes React owns**. Selecting text floats a 「高亮」 button (the web's stand-in for iOS's edit-menu entry) → `selectionContext` captures quote + ~30 units of prefix/suffix → `onCreate`; clicking a painted highlight opens a 评论/删除 menu (hit-testing via `caretPositionFromPoint`, shortest-range-wins for overlaps — iOS's rule). Orphans — quotes the text no longer contains — are listed below the body, never silently dropped. On a browser without the Highlight API the layer degrades: creating works, orphans list, located highlights just aren't painted |
| `AnnotationCommentDialog` | One highlight's comment editor (iOS `AnnotationCommentSheet`): the quote block on top as the reminder of what is being commented, whole-text overwrite — clearing and saving deletes the comment while the highlight stays (deleting the highlight is the menu's other action) |
| `AnnotationOrphans` | The 「失效的高亮」 list under the body: quote (in the highlight's own soft yellow) + comment + delete per row. Exists so a re-derived body (upstream edit, pipeline change) demotes highlights visibly instead of eating them |

### `components/search/`

| Component | Purpose |
|---|---|
| `SearchScopeMenu` | Where to search: All sources / one source / one subscription inside it, built from the same `GET /api/sources` tree the sidebar draws. A picked subscription travels as `source` **plus** `feed` for both multi-feed sources — the two key on different things (an X handle, an RSS feed URL), so the server 422s a `feed` that arrives without one of them named. Two levels in one **flat** menu rather than nested submenus — the whole list is a handful of rows, and a submenu hides the channel you are reaching for behind a hover. A paused subscription is offered too: search reads the archive, and pausing a channel does not unread what it already collected. Also exports `sourceGlyph` |
| `SearchScopeOption` | One row inside `SearchScopeMenu` (check + glyph + name, indented for a subscription) |
| `SearchFilters` | The row under the search box: `SearchScopeMenu`, the All/Unread/Saved status chips, and the sort toggle. All three live in the URL, which is what makes a search a link. Status defaults to **All**, unlike the timeline's unread-first default — you search for something you remember reading at least as often as for something you haven't |
| `SearchFilterChip` | One small icon+label button in that row. Header-scale, unlike `SegmentedOption` (a settings-sized card), so the row does not wrap to a second line on a phone |
| `SearchResults` | The result list: flat `DatedItemRow`s + offset infinite scroll + the four states (loading / error / empty / results). Deliberately **not** wired to `useScrollToRead` — scrolling past a five-year-old message while hunting for a different one is not reading it. Every other card interaction (save, hide, feedback, the detail pane) works as it does elsewhere. A 422 renders as "nothing searchable", not as a failure: it means the box holds only punctuation or emoji |

### `components/forwards/`

| Component | Purpose |
|---|---|
| `ForwardRecordRow` | One row of the `/forwards` log: **the record's own metadata above the item it published** — time, the target channel *as configured at the time*, the comment verbatim (or 「原样转发，没有写评论」), an open-in-Telegram link and a delete button. The comment is drawn outside the card on purpose: it belongs to the forward, not to the item, and the same article can be forwarded twice with two different comments. The `item` half is a plain `DatedItemRow`; a record with **no snapshot** (a native TG forward reads no archive row, so it can publish a message we never stored) renders the metadata alone and says so. The delete `ConfirmDialog` states that only the local record goes — the message stays in the channel — because that is the one thing a reader could reasonably assume otherwise |

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
| `HackerNewsSection` | The Hacker News tab on the Subscriptions page: Front Page subscribe/unsubscribe, sampling pause switch, `HnFeedRulesMenu`, status line (`/api/hn/status`) |
| `XSection` | The X tab on the Subscriptions page: add Following / For You / an account by handle, the `XSubscriptionRow` list, and a two-line `/api/x/status` block — archive size + last probe push + parse errors (the data is pushed by the local probe, so this is where you find out the probe went quiet), plus an `XVerdictLine` explaining why the For You verdict is quiet: not configured, no sqlite-vec, or still counting down how many 👍/👎 remain before the cold-start gate opens |
| `XSubscriptionRow` | One X feed row: For You, Following or a followed account (handle chip only once a real display name has been learned), archive size + last push, plus the per-feed filter counts (Following: ads dropped + out-of-window entries archived only; For You: foreign-language tweets dropped — a 0 where you expected some means a filter stopped working), `XLangFilterToggle` (For You only), `XAggregateMenu` (whole-timeline feeds only), pause switch, unsubscribe |
| `RssSection` | The RSS tab on the Subscriptions page: add a feed by URL, bulk-import an OPML export (the file is read **in the browser** and posted as text, so an import goes through the same path a manual add does and cannot create a subscription typing one could not), the `RssSubscriptionRow` list, and a polling status line. Its `refetchInterval` is a **function**, not a constant (`rssRefetchInterval`, exported for its test): 5s while a feed still has no verdict, 60s once every one of them does. Right after an import that is the whole list and the first round lands within seconds — without it the rows sit on "waiting for the first fetch" until the reader reloads, which reads as a feed that never ran. "No verdict" is all three of `enabled && !fetched_at && error_count === 0`, not `fetched_at` alone: a failed round leaves `fetched_at` NULL on purpose, so a broken feed (or one paused before its first round) used to hold the page at 5s for as long as it stayed open. Rows are ordered by `sortRssSubscriptions`: **failing feeds first** (`error_count > 0`), everything else left in the server's `added_at desc` order, stably — nothing is auto-unsubscribed or backed off, so surfacing the broken ones *is* the whole mechanism, and an unstable order would reshuffle 77 rows under the reader's cursor on every refetch. The import toast always states all three counts, since "added 40" alone hides that 12 were unusable. The status block is **two lines**: polling state, then the summary pipeline (`AI 摘要 <model> · 已生成 N · 待处理 N`, or the "no key configured" sentence with the count it *would* work through) — the only place a reader can tell a server with no summary key apart from entries too short to need one |
| `RssSubscriptionRow` | One feed row: name (the URL until a fetch teaches us the title), fetch state, pause switch, unsubscribe. The status line's job is to explain a feed that has gone quiet, and it keeps two states apart that look alike: `error_count > 0` is **broken and retrying** (red), while a `last_error` with a zero count is a complaint about malformed XML we recovered entries from anyway — a warning (amber), not a failure |
| `XAggregateMenu` | How much of a whole-timeline X feed joins the aggregate → PATCH the feed's `config.aggregate` (`HnDisplayModeMenu`'s sibling). Only For You and Following get one, and not with the same options: For You offers 不进 / 只进推荐的 / 全部并入, Following only 不进 / 全部并入 — it is never judged, so a recommended-only mode would silently hide the whole feed. A setting rather than a constant because the right answer tracks how good the verdict currently is |
| `XLangFilterToggle` | For You's 「按全局语言过滤」 toggle (+ its `useSetXLangFilter` mutation) → PATCH `config.lang_filter`. The language list is global (Settings → 语言); this only says For You obeys it. Filtering is at ingest (drop whole, the ad filter's path), so flipping it changes future pushes, not history — and with the switch on but no languages picked the button itself shows 「先在设置中选择语言」, because the fail-open filter is silently inert in that state |

> `components/ui/` holds generated shadcn/ui (new-york) primitives — intentionally **excluded**
> from this inventory. Don't list them here. Import `Button` from `@/components/ui/button`.

## Where things live (non-components)

- `pages/` — route screens (`TimelineView`, `RecordsView`, `ForwardsView` — the `/forwards`
  publish log, offset-paged like search, no channel filter because a row belongs to one
  act of forwarding rather than to a channel — `SearchView`, `FiltersView`,
  `SubscriptionsView`, `AppShell`, `AppLogin`, `TgLogin`, `AuthorizeView` — the
  device-authorization page cold-loaded by the iOS app; only needs the cookie session, so
  `App.tsx` renders it before the TG gate). **The TG gate is a wall only for a
  Telegram-only install** (2026-08-15): if `GET /api/sources` reports any non-Telegram
  subscription, an unauthorized Telegram session no longer blocks the app — since the
  reader went multi-source, an HN- or X-only install has content to show and a
  phone-number form in front of it is a lock, not onboarding (a review/demo server is
  exactly that shape). Three details make it safe: the gate **waits** for the sources
  query rather than deciding early (else the wall flashes at an install that has other
  sources), a failed sources request falls back to walling (the pre-multi-source
  behavior), and `/connect-telegram` renders `TgLogin` from *inside* the app so the login
  stays reachable — `SettingsDialog` links there, and the route redirects home once
  connected. `useSources` is `enabled`-gated here so it never fires behind `AppLogin`.
  `SearchView` owns the box (local draft state,
  300ms debounce) while the **URL owns the committed query** and every filter, written with
  `replace` — so a search is shareable and Back leaves the page rather than un-typing a word.
- `hooks/` — data + behavior hooks (`useTimeline`, `useSources`, `useSubscriptions`,
  `useChannelFilter`, `useScrollToRead` (armed "看过即读" judgement + `pendingKeys` green
  sync state + confirm-then-flip cache writes — see the root AGENTS.md bullet),
  `useNewContent`, `useRefresh`, `useCollapsedSources`
  (sidebar collapse persistence), `useHnFeedRules` (the front feed's three admission rules —
  option lists, the coercion that fills a pre-floors config with the server's defaults, the
  tooltip summary, and the one-key PATCH mutation),
  `useXAggregate` (a whole-timeline X feed's aggregate-mode options + PATCH mutation; invalidates the
  timeline, the calendar and both unread badges, since the admitted set is computed at
  query time on the backend),
  `useRssArticle` (one feed entry's article body, idle until the detail pane asks
  for it — the list payload carries only an excerpt; `staleTime: Infinity`, a
  published document does not change under us),
  `useNote` (set/overwrite an item's 条目评论 via `POST /api/note`, '' clears = the
  delete; optimistic patch across every item cache rolled back from the pre-click
  value, `['records']` invalidated because a first note creates the saved-items row
  and clearing the last writing drops it — schema v18's row-exists ⟺ saved ∨ note ∨
  annotations invariant),
  `useItemAnnotations` (the detail pane's highlight model, iOS `ItemAnnotationsModel`'s
  sibling: local mirror keyed on the envelope object + `patchItem` to every cache;
  `add` deliberately not optimistic — the server assigns the id, so there is nothing
  coherent to render until it answers; remove/comment optimistic with whole-list rollback),
  `useForwards` + `useDeleteForward` (the offset-paged `['forwards']` log and its delete;
  the delete is deliberately **not** optimistic and deliberately does **not** clear the
  card's `forwarded_by_me` locally — a second record of the same item may still exist, and
  only the server knows, so it invalidates every item list and lets the server restate the
  flag),
  `useInfiniteScrollSentinel` (the one paged-list tail sentinel — rootMargin + in-flight
  guard — shared by Timeline / SearchResults / ForwardsView so the tuning can't drift),
  `useMessageStats` (live pane stats, staleTime 0), `useAppMeta` + `useSetForwardChannel`
  (runtime app settings incl. the forward target channel), `useHideItem` + `useUnhideItem`
  (hide an item from every timeline via `POST /api/hidden`; optimistic removal + undo),
  `useFeedback` (up/down/clear an item's label via `/api/feedback`; optimistic in-place
  swap across every item cache, rolled back from the pre-click value.
  Verdict + reason move as one `Label` — the reason belongs to the verdict it explains, so
  they are cached, rolled back and cleared together and a correction can't strand a stale one),
  `useSearch` (the offset-paged `['search']` infinite query, idle until the box has content;
  also exports `scopeParams` — the one place the picker's source+sub is translated into the
  API's `source` / `channel_id` / `feed`),
  `useVibeReader` (the extension bridge's mirrored `available` / `linked` / `version` +
  `setLink`, over `lib/vibeReader`'s `useSyncExternalStore` store),
  mutations, …). `useTimeline` / `useTimelineDays` / `useNewContent` / `useBulkRead` accept a
  `source` scope (the `/s/:source` views) plus a `feed` scope for multi-feed sources
  (the `/s/:source/:feed` route — X's For You / one followed account).
- `lib/` — `api.ts` (typed fetch client), `types.ts` (backend JSON mirror), `format.ts`,
  `sources.ts` (source labels, `hnCommentsUrl`, `xTweetUrl` / `xProfileUrl` / `xPreviewUrls`, `rssFeedLabel` + `subRowLabel` — the source-aware row name, since RSS is the one source whose key is a full URL and the generic fallback would print it whole,
  `X_FORYOU_FEED` / `X_FOLLOWING_FEED` + `isXSyntheticFeed` / `xFeedLabel`, sub-row labels,
  `FEEDBACK_REASONS` + `FEEDBACK_REASON_LABELS` — shared by
  the card that asks and the pane that reports the answer, so the two can't drift),
  `sanitize.ts` (DOMPurify
  wrapper for HN self-post + RSS article HTML),
  `annotate.ts` (quote relocation for highlights — the behavior-identical port of
  CondenserKit's `Annotations.swift`, pinned by the same test cases: exact search →
  whitespace-folded fallback → prefix/suffix context scoring ×2 with the `block`
  hint only ever breaking a tie; plus `selectionContext` — surrogate-safe ~30-unit
  context capture — and `hasNotes`),
  `domText.ts` (the DOM half: flat text index over a container's text nodes,
  offset ↔ Range/position maps, selection + caret-from-point readers; never mutates
  the DOM — highlights paint via the CSS Custom Highlight API),
  `linkify.tsx`, `extractUrls.ts` (shared URL
  regex/extraction for linkify + the detail pane), `itemDetailPane.tsx` (the detail pane's
  context: the open `TimelineItem` envelope), `theme.tsx`, `unreadIndicator.tsx`,
  `itemCaches.ts` (the caches that hold item envelopes — the paged timelines,
  the paged search results, the flat saved list, and the `['forwards']` log whose
  pages hold `{record, item}` **entries** rather than bare items (its own accessors,
  never appended to the paged-keys list) — plus `patchItem` / `removeItem` /
  `findItem` over all of them. Listed in one place because the same card can be on
  screen in two of them at once, and patching only the timeline is how one copy ends up
  showing a filled bookmark while its twin shows an empty one. `removeItem` deliberately
  skips the saved list *and* the forward log: both are archives of the reader's own acts,
  so a hide leaves them alone),
  `vibeReader.ts` (the condenser half of the **Vibe Reader link mode**, plan
  2026-09-02 §1–2: the message contract's copy on this side — `PROTOCOL_VERSION`, the
  `condenser:*` / `vibe-reader:*` shapes, pinned by its test; a module-level store the
  bridge's hello / link / bye messages write and `useVibeReader` reads; `setLink`, which
  only *asks* — the extension is the switch's truth and `linked` flips on its answer;
  `announceOpen`, silent unless linked; `shouldAnnounce` + `NO_ARTICLE_HOSTS` — x.com /
  twitter.com / t.me / HN user pages carry nothing to extract, HN *item* pages do; the
  document-level click + auxclick delegate that turns every new-tab link into a
  `condenser:open` without ever `preventDefault`ing; and `hnLinkAttrs`, the `data-vr-*`
  a story's links wear. Transport is `window.postMessage` on our own origin, accepted only
  from `event.source === window` under the bridge's namespace — no `externally_connectable`,
  so condenser never learns the extension id. The `<meta name="application-name">` in
  `index.html` is how the extension recognizes a condenser tab),
  `queryClient.ts`, `utils.ts`, `pwa.ts` (standalone-window resize), `swUpdate.ts`
  (PWA background-update flow: vite-plugin-pwa prompt mode — the SW precaches the app
  shell so the installed app opens instantly from local cache, a new build found in the
  background raises a persistent「发现新版本」toast, and confirming activates + reloads;
  update checks run hourly and on visibilitychange. Wired in `main.tsx` via
  `virtual:pwa-register`; the SW only exists in production builds, dev is a no-op. The
  workbox config in `vite.config.ts` denylists `/api` from the SPA navigation fallback).

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
