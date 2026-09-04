---
created: 2026-08-21
tags:
  - ios
  - swiftui
  - app-store
---

# iOS app (`ios/`, monorepo)

> Written as a running log while this lived inside AGENTS.md — "see the iOS section
> above" style references mean AGENTS.md; commands and build conventions are in
> `ios/AGENTS.md`.

Native SwiftUI read-only client (spec: `kb/plans/2026-07-16-ios-reader-app.md`; device-token
auth spec: `kb/plans/2026-07-16-mobile-client-api-device-token.md`). Pure-CLI workflow —
xcodegen `project.yml` (single source of truth, `.xcodeproj` gitignored) + Makefile
(`make build / test / run / gen / clean`, simulator via `simctl`). Two layers:
`CondenserKit/` local SPM package (pure logic + Swift Testing tests, no UIKit) and
`Condenser/` app target. See `ios/AGENTS.md` for commands and conventions.
Phases 1 (skeleton) + 2 (auth: `AuthFlow`/`TokenStore` in Kit, `AuthSession` + `LoginView`
via SwiftUI `webAuthenticationSession`) + 3 (core reading: Models mirrored from
`frontend/src/lib/types.ts` with real-JSON fixtures, `APIClient` (Bearer, 401 →
`APIError.unauthorized`), `CondenserAPI` protocol for test stubs, `TimelineStore` /
`ReadReporter` / `NewContentPoller` in Kit; app side: `ReaderSession` composition
root wiring 401 → `AuthSession.handleUnauthorized`, `TimelineScreen` with scroll-to-read via
`onGeometryChange`, infinite scroll, pull-to-refresh, new-content capsule, unread toggle,
`MessageCard` / `MessageDetailSheet` / authed `ImageLoader`; debug-token env injection for
simulator, see `ios/AGENTS.md`) + 4 (three-tab `TabView`: Timeline / channels / saved —
`MessageListView` extracted as the reusable list core, `ChannelsScreen` +
`ChannelTimelineScreen` (per-channel `TimelineStore`, no snapshot/poller), `SavedScreen` on
`RecordsStore` (optimistic unsave + positional rollback; records are self-contained via
`message.channel`), `SnapshotCache` (Caches-dir JSON; timeline page 1 + subscriptions render
before network on cold start), fullscreen `ImageViewerScreen` (paged album swipe, UIScrollView
pinch/double-tap zoom, drag-down dismiss), `SettingsScreen` (server/device name, sign-out),
`TokenStore.deviceName`; 79 Kit tests; DEBUG deep-link walkthrough via
`SIMCTL_CHILD_CONDENSER_DEBUG_ROUTE`, see `ios/AGENTS.md`) done. Reading-experience polish
(2026-07-18): default view is **unread** (eye / eye.slash toolbar toggle; both modes snapshot-
cached), Settings is a 4th tab (screen no longer wraps its own NavigationStack), nav + tab bars
auto-hide on scroll-down / reappear on scroll-up (`AutoHideBars` on the ScrollView; decision
logic lives in Kit's `BarsVisibilityModel` — bar toggles change safe-area insets which feed
back into scroll geometry, so direction detection runs only during user scroll phases plus a
post-toggle cooldown, else it self-oscillates into a main-thread relayout freeze), card links
+ photos + webpage cards are directly tappable (shared
`linkified` in `Linkify.swift`, list-level `openURL` env → in-app Safari, photo tap → fullscreen
viewer), 5-line truncated text shows a blue "more" (hidden measuring copy), photo thumbs render
in fixed aspect boxes (`Color.clear.aspectRatio` + overlay + clip — fixes album grid overflow;
tall single photos clamp to 3:4), and `MessageListView.refresh` flushes the ReadReporter queue
first so pull-to-refresh in unread mode actually drops just-read items. Settings has a 4-step
**font-size slider** (小/正常/略大/大 + live mock-card preview): Kit's `FontScale` enum
(ordered presets, stored-value fallback, slider-index clamp) maps to a fixed `DynamicTypeSize`
(small/large/xLarge/xxLarge — overrides system Dynamic Type on reading surfaces only) via
`.readingFontScale()` in `ReadingFontScale.swift`, persisted through
`@AppStorage("condenser.fontScale")` and applied on `MessageListView` / `SavedScreen` /
`MessageDetailSheet`. 2026-07-19: **pull-up-to-fetch-older** — in channel timelines, once
local history is exhausted (`hasMore == false`) a bottom footer appears and continuing to
pull up (overscroll ≥ 70pt while dragging, Kit's `PullToLoadOlderModel` + geometry helper)
triggers `POST /api/tg/fetch-older/{id}` then resumes paging via the new `end_cursor`
field (`TimelineStore.fetchOlderFromServer`; `fetched == 0` → `olderExhausted` sticky until
refresh). Aggregate All/Unread views don't get the gesture (no per-channel semantics).
**Forward-source-as-subject** — forwarded cards/detail render the origin (channel avatar via
`/api/channels/{id}/avatar` — works for unsubscribed public channels, 404 → letter fallback;
name from Kit's `DisplayMessage.forwardSource`: channel → user → post_author cascade) as the
header subject, with "Forwarded by <subscribed channel> · time" as the caption line; hidden
sources (no name) degrade to the old plain "转发" tag. `ChannelAvatarView.channelID` is now
optional (nil → letter avatar, no request). **Multi-source Phase 4 (2026-07-21)**: Kit
models are envelope-based (`TimelineItem` + `HnStory`/`LinkPreview`; `DisplayMessage` lost
its read/saved flags), `CondenserAPI` speaks item keys (`markRead(keys:)`,
`saveRecord(key:)`, `DELETE /api/records/{key}`) + `sources()` (`SourceGroup`/`SourceSub`
with int-or-string `SubChannelID`; `/api/subscriptions` dropped), `TimelineStore`/
`NewContentPoller` take a `source` param, `ReadReporter` queues keys, `SnapshotCache`
dir carries a contract version (`condenser-snapshots-v2`, old snapshots = miss),
`hnPlainText` converts HN self-post HTML in Kit. App: source-switcher Menu top-left of
Timeline (All + added sources from `/api/sources`), tab 2 频道→订阅 (source→subs two-level
list; TG row → channel timeline, HN row → `HnFeedTimelineScreen` = source-scoped store),
`HnCard`/`HnDetailSheet` (title → Safari original / comments for self-posts, meta line,
day-rank, prefetched preview box), Saved/detail dispatch by source, debug routes gained
`hn` + `tab/subs`. Fixtures regenerated as envelopes
(`tmp/make_ios_fixtures.py`: mixed/tg/hn pages, hn_shapes, sources, records incl. a
temp-saved HN record). **Message stats + forward (2026-07-22)**: Kit gains
`ReactionCount` (unknown kind → `.other` forward-compat) / `MessageStats` /
`ForwardResult` / `AppMeta` models and off-protocol `APIClient` methods
(`messageStats`, `forwardMessage` — trims the comment, empty → body without
`comment` = native forward, `appMeta`, `setForwardChannel`); app: stats row in
`MessageDetailSheet` (views/forwards/reaction chips, fetched in the sheet's
`.task` — a `Group { if … }.task` never fires when empty, hence the
presentational `MessageStatsRow`), `ForwardDialog` sheet (preflights
`appMeta` → not-configured guidance / composer / success-with-link states,
error mapping per routers/messages.py), Settings 转发 section
(read/save `forward_channel`), debug route `forward/<cid>/<mid>[/<comment>]`
(auto-submit, real network — walkthrough `tmp/2026-07-22-ios-stats-forward/`).
**Silent refresh + gray toast, no polling (2026-07-22)**: the timeline refreshes by
exactly two paths — the user's pull-to-refresh, and a silent auto-update on cold start /
return-to-foreground after ≥5 min background, which reports itself afterwards via a
**non-interactive gray "N 条新消息" toast** (auto-dismiss 4s, tap = dismiss). The 30s
`/timeline/new` poll loop and its blue tappable capsule were **removed** (user feedback:
interrupting mid-read is annoying) — nothing pops while you read. Kit:
`TimelineStore.loadInitial` returns the new-item count vs the rendered snapshot
(`@discardableResult`) for the cold-start toast; `ForegroundRefreshPolicy` (first-leave
timestamp, threshold check clears state) gates the foreground path; `NewContentPoller`
→ **`NewContentChecker`** (one-shot `check() async -> Int`, no count/reset/start/stop —
failures and missing cursor are 0). App: `MessageListView` owns the whole flow
(`checker:` param, nil for channel/feed views); `TimelineScreen` only flushes reads on
background. Foreground return calls `check()` **first** and only disturbs scroll when
count > 0 (scroll-to-top before refresh, else the new first screen lands above the
viewport and scroll-to-read false-marks it); 0 = reading position untouched. Walkthrough
`tmp/2026-07-22-ios-foreground-toast/`.
**X source (Phase 5, 2026-07-25)**: Kit gains the `XTweet` payload family
(`XMediaItem`/`XMetrics`/`XArticle`/`XQuote`/`XVerdict`+`XVerdictMeta`) plus the
source-generic `ItemFeedback` on the envelope, a `feed` scope on `TimelineStore` /
`NewContentChecker` / the timeline endpoints (X is the first source with *many* feeds),
`setFeedback`/`clearFeedback` on `CondenserAPI` with an optimistic toggle in both stores
(tapping the lit side = undo), and `xAvatarURL`/`proxiedImageURL`. `XTweet` owns the
card's pure logic (`bodyText` strips bird's `RT @orig:` prefix and drops a long-form
post's title-as-text, `displayName`, `tweetURL`/`profileURL`, `photos`). App: `XCard`
(+`XQuoteCard`/`XMediaView`/`XMediaThumb`/`XAvatarView`/`XGlyph`/`XVerdictBadge`/
`XFeedbackButtons`) and `XDetailSheet` (verdict evidence — score + labeled neighbours
with handles + `model@dims` — in Chinese; the card badge keeps web's English),
`XFeedTimelineScreen` reached from the subs tab's X group (**For You's only entry — it is
not in the aggregate timeline**), `ImageViewerItem` generalized to `ViewerPhoto`
(`.telegram(cid,mid)` / `.proxied(url)`), and `TruncatableText` shared with `MessageCard`.
Every image routes through the backend, so reading a tweet never contacts X.
`XVerdict`/`ItemFeedback` decode unknown values to `.other` rather than failing the page.
Debug routes gained `x[/<feed>]`, `detail/x/<feed>[/<id>]` and `tab/subs/<source>`.
161 Kit tests; walkthrough `tmp/2026-07-25-x-phase5-ios/`.
v1 spec complete; remaining polish: end-to-end
`ASWebAuthenticationSession` verify on device, video playback (non-goal).

**RSS source (Phase 6, 2026-08-21)**: the fourth source, and the smallest addition of the
four — no verdict, no feedback, no media, so the envelope only gains `rss` (`RssEntry`)
and nothing else in the Kit's plumbing had to move (`feed` scope, item keys, read/save,
records all came free from the X phase). Kit: `RssEntry` (+`RssBody`, `RssFeed.label`),
`rssPlainText`, `SourceID.rss`. App: `RssCard`/`RssGlyph`, `RssDetailSheet`,
`RssFeedTimelineScreen` + the subs-tab row, `makeRssStore(feed:)`, debug routes
`rss[/<index>]` and `detail/rss[/<id>]`. 223 Kit tests (+24); walkthrough
`tmp/2026-08-21-rss-phase4/`.

Three decisions worth keeping:

- **The body is a two-case enum, not a string.** `RssBody.summary` vs `.excerpt` —
  a summary is a machine's paraphrase, and a card that renders it like the author's own
  prose is lying quietly, so the source travels with the text and the card marks it
  (「AI 摘要」). The detail sheet shows both, summary first: you tap in to read the
  article, not its paraphrase.
- **`rssPlainText` is not a generalization of `hnPlainText`.** HN's `text` is a subset
  small enough to enumerate; RSS is the open web's HTML. Three rules invert: anchor text
  is kept (HN swaps in the href because it truncates its own link text), `<script>` /
  `<style>` are dropped *with* their contents, and source newlines are whitespace — only
  block tags break lines, or a formatted feed hard-wraps mid-sentence. `<pre>` is the one
  exception, lifted out and put back after, so code keeps its indentation.
- **The glyph is amber, not `.orange`.** `HnGlyph` is already pure orange and the two
  squares sit adjacent in one timeline; identical colors mean no source mark at all. Only
  the walkthrough could catch this — an RSS card on its own looks fine.

⚠️ This landed **after** 1.0.0 went to review, so it rides the next build. Until a build
with `RssCard` is on the phone, `CONDENSER_RSS_ENABLED` stays false in production: a
shipped client that meets an unknown `source` renders a blank row (the X Phase 2 lesson).

## 分享图片（2026-08-23，四个源）

四个详情抽屉的 `ItemActionRow` 行尾多一个「分享图片」：把这条内容渲成一张长图，交给系统
分享面板。截屏只截得到一屏，长文分享出去总是半截；而这个 app 连的是自托管实例，链接对外
没有意义——图是唯一能把一条完整内容原样递给别人的形态。计划与 grilling 结论：
`kb/plans/2026-08-23-ios-share-image.md`。

- **不截抽屉，另画卡片。** `ImageRenderer` 不渲染 UIKit 桥接视图，而抽屉正文恰好是
  `SelectableTextView`（`UITextView`）——直接渲染那块是空白。所以卡片是纯 SwiftUI，
  正文 `Text`，图片一律注入预载好的 `UIImage`：`ImageRenderer` 是同步一帧，视图里出现
  任何 async 加载都渲不进去。
- **内容取舍在 Kit（`ShareCard.swift`），不在视图里。** 源无关的模型（头像/标记 + 名称 +
  副标题 + 标题 + 块序列 + 落款），`ShareCard.build(item:channelTitle:articleBlocks:)`
  一个入口分派四个源。这么做是为了让「哪些东西会跟着图发给别人」有测试盯着：X 的判定与
  反馈不进图（断言方式是「同一条推文带不带 verdict，卡片一模一样」——`ShareCard` 是
  `Equatable`）、TG 的实时统计不进图（那是「此刻」的数字，印进一张会传播的图里只会过期）、
  RSS 用详情取回的**全文**而不是列表摘录（全文没到手时按钮按不动）。元信息行是**块**
  不是字段，因为它在四个源里的位置不一样（HN 紧跟标题、X 在正文与引用推之后）。
- **外观定死。** 固定浅色 + 固定字号（`readingFontScale` 刻意不生效：图是给收图的人看的，
  不该继承分享者的主题与字号），颜色全部写常量——`ImageRenderer` 解析 UIKit 动态色走的是
  进程当前的 trait collection，只靠 `\.colorScheme` 环境挡不住深色（深色模拟器上实测）。
  同理信源标记在这里重画了一份，没复用 `HnGlyph`/`XGlyph`/`RssGlyph`（那三个里有
  `Color.primary` 与 `Color(.systemBackground)`）。
- ⚠️ **位图高度超过 8192px 时，渲染不报错，给你一张全黑图。** 逐级实测：800×6526px
  正常，1200×9789px 全黑（`uiImage` 照样返回 UIImage、`pngData()` 返回 nil、JPEG 给出
  一张黑的）。所以是**先量后画**：`render` 只量尺寸不给绘制回调，量到的高度决定 scale
  （≤2730pt 走 scale 3 ≈ 1200px 宽，再长按 8192px 反推，下限 1x），装不下就报「这条内容
  太长了（约 N 屏）」。一篇阮一峰周刊 17555pt ≈ 21 屏正是被挡住的那类——**拒绝而不是切成
  多张**是拍过板的决定。
- **PNG 还是 JPEG 按高度分。** ≤4096px 走 PNG（文字边缘干净），更长走 JPEG q0.9——PNG 对
  照片几乎不压缩，一篇图多的长文能到十几 MB，而这些图是要发出去的。实测 TG 1200×1428
  PNG 532KB、X 1200×3134 PNG 1.6MB、云风博客全文 1005×8191 JPEG 3.1MB。
- **预载每张图 5 秒上限、并发跑**，到点没到的画灰色占位块（沿用后端给的纵横比，版面不塌），
  上限 24 张。一张挂掉的图不该让整次分享失败。
- 分享面板直接从最上层 VC present（`ActivityShare.swift`）：`ShareLink` 要求初始化时就
  持有成品数据，与「点了才生成」相性差；包成 SwiftUI sheet 的根视图则会先弹一张空白 sheet。
  产物落 `FileManager.temporaryDirectory`，面板关闭后删。文件名是 `condenser-<item key>`，
  接收端看到的不是 IMG_0001。
- Info.plist 多了 `NSPhotoLibraryAddUsageDescription`——分享面板里的「存储图像」缺了它会
  直接崩。**下个 build 提审会看到这条新权限声明**，只写入不读取。
- 走查入口：`SIMCTL_CHILD_CONDENSER_DEBUG_SHARE=1` 配合 `detail/...` 路由，抽屉一出现就
  自动按那个按钮（动作行是横向滚动的，分享按钮排在行尾，而模拟器窗口收不到合成手势）。
  它的 `.task` 必须带 `id: card?.key`——RSS 的 card 要等全文到手才从 nil 变出来，而 task
  闭包捕获的是**当时那个** struct 实例的 card（踩过）。

## HN 摘要（2026-09-02，plan Phase C）

服务端给 HN story 写的摘要（schema v19，`hn_summary.py`）在 iOS 上的落点，照 RSS 的样子：
Kit `HnStory.summary: String?`（缺字段解 nil，所以 v19 之前的载荷与旧 build 都不受影响）+
`displaySummary`（`RssEntry` 同款：trim 后非空才算有）。`HnCard` 标题下、元信息行上放
`AiSummaryBlock`（与 RSS 卡同一个视图——机器转述在每张卡上得长一个样）；`HnDetailSheet`
元信息行下、正文 / 预览卡前，`SelectableTextView`，**不可标注**（机器的话，RSS 定的规则）；
分享图 `ShareCard.hn` 元信息块后接 `.summary` 块，与 sheet 同序。与 RSS 卡不同的是 HN
卡本来就没有正文可作参照（外链 story 什么都没有），所以摘要块直接跟在标题下，不存在
「摘要顶掉原文开头」的问题。随下一个 build 走，与 `RssCard` 同一批。验收图
`tmp/2026-09-02-hn-summary-display/`（本地后端 + 手工写入两条摘要，看完已还原）。

**签名与 App Store 就绪（2026-08-12）**: 发布素材已全部就位 —— AppIcon 资产目录
（`Condenser/Assets.xcassets`，1024 单尺寸/不透明/满幅，由 `tmp/make_ios_appicon.py`
按 PWA 同款漏斗+水滴设计生成）、`MARKETING_VERSION`/`CURRENT_PROJECT_VERSION`、
`ITSAppUsesNonExemptEncryption=false`、`PrivacyInfo.xcprivacy`（不追踪不采集，唯一
required-reason API 是 UserDefaults/CA92.1 —— 新增文件时间戳、磁盘容量一类调用要同步补
声明），外加 `make archive`（Release 归档 + `exportArchive`，method `app-store-connect`）。
**Apple 凭据不再硬编码在项目里（2026-08-13）**：唯一权威来源是 `~/Sync/apple-developer/`
（见其 AGENTS.md；secrets.env 用 envops 读）——`ios/Makefile` / `scripts/device.sh` 从
`APPLE_TEAM_ID` 取 Team ID，导出配置由 `scripts/ExportOptions.template.plist` 渲染 teamID
生成；asc CLI 认证已持久化到系统钥匙串（默认 profile `reorx-admin`，Admin 角色，裸跑即可）。
**ASC app record 已创建（2026-08-13）**：`com.reorx.condenser` / SKU `condenser-ios`，
经 `asc web apps create` 无头创建——app id、设备与 API key 等标识不入公开库，见私密 KB
`kb.private/condenser/kb/docs/ios-app-store-release.md`；剩余发布步骤（隐私标签/截图/
文案/定价/demo 账号）见 `ios/AGENTS.md`「App Store 发布」。
~~⚠️ 阻塞点：付费 Team 下一台设备都没注册过~~ —— **已解除（2026-08-13）**：USB 连机跑
`make device`，`-allowProvisioningDeviceRegistration` 把这台 iPhone 自动
注册进了 Team（ASC API 实测可见），签名链路首次真正跑通。当时的安装一步被预告过的一次性
迁移挡住（旧 app 是旧免费 Personal Team 签的，`application-identifier` 前缀不匹配，
iOS 拒绝覆盖）——删旧 app 重装即可，装好后重走 `/authorize` 配对。历史教训与 Wi-Fi 构建
限制见 `ios/AGENTS.md` 的「真机部署」。**`make archive` 已实跑验证（2026-08-13）**：
ipa 落地 `.build/DerivedData/export/Condenser.ipa`，签名 Apple Distribution（云签名
自动补发分发证书），App Store 型 profile 有效期 1 年——发布链路本地部分全通。
**首版素材全部上架（2026-08-15）**：文案 / 分类（NEWS+PRODUCTIVITY）/ 年龄分级（4+）/
版权 / 定价（免费）/ 全 175 地区 / 内容版权声明 / 隐私标签（Data Not Collected，已
publish）/ 3 张 `IPHONE_65` 截图，全部经 asc CLI 无头完成。截图的造法（临时后端 +
只开 HN + debug 路由逐屏截）与 asc 的几个坑记在 `ios/AGENTS.md`「App Store 发布」，
ASC 侧资源 id 在私密 KB。⚠️ 新建的 `PRIVACY.md` 是商店隐私政策 URL 的落点，
**提审前必须已 push 到 master**，否则 404（2026-08-15 已 push）。
**1.0.0 已提交审核，`WAITING_FOR_REVIEW`（2026-08-16 02:40 UTC）**：审核 demo server
（`kb.private/condenser/kb/docs/demo-server.md`，`condenser-demo.reorx.com`，只开 HN 源）
上线并验收，最后一个
`asc validate` 阻塞项由此消除；**build 1.0.0 (2)** 已 archive → upload → VALID → 挂到版本
（build 1 作废——它的 `LoginView` 预填的是作者的生产域名，审核员点下去必然认证失败，
读起来正是 2.1 的形状）；审核详情的 demo 账号与三步英文备注已填，密码是从
`hh-hk-01:/opt/apps/condenser-demo/.env` 现读现填的，所以不可能与服务器漂移；截图 4 张
（设置页那张 2026-08-16 补拍，模拟器直连 demo server，所以地址栏印的就是审核员会输入的域名）；
validate 0 error / 0 warning。提审前先过了一轮 **TestFlight 内部测试**（不需要 beta 审核，
而且这是唯一能在真机上跑提审二进制的途径——App Store 型 profile 没有设备清单），真机验过
demo 登录全流程后由用户拍板提交。⚠️ **审核期内 demo server 必须一直在线**，掉线就是 2.1。
查进度 `asc review status --app <app id>`；`asc review submit` 会报一个无害的自检错误，
处理方式记在私密 KB（别按报错重跑）。提交后又改了两处（价格与发布方式都不属于审核内容，
改了不影响在审的版本）：**定价 免费 → USD 2.00**，**发布方式改为手动**——过审后停在
`PENDING_DEVELOPER_RELEASE` 等人点发布。⚠️ 收费的前置是 ASC → Business 里的
**付费应用协议**（银行 + 税务）生效，这个状态公开 API 查不到，只能人去网页确认；没生效
则过审也上不了架。细节与两个 asc 定价坑见私密 KB。

## Mac Catalyst（2026-09-04）

iOS app 编成 Mac app 的三条路线里选了 Catalyst（plan `kb/plans/2026-09-04-mac-catalyst.md`
§1 有比较：Designed for iPhone 零代码但固定手机窗口，原生 macOS target 要重写 5 个 UIKit
文件）。实验先行：不改一行 Swift 就编过了，之后的适配全是「Mac 上该长什么样」而不是
「Mac 上能不能跑」——侧栏代替底部 tab 栏、阅读列限宽、详情抽屉 `.page` 尺寸 + 关闭钮 +
Esc、外链开系统浏览器、设备名取主机名。四个源的卡片 / 抽屉 / 登录（ASWebAuthenticationSession
→ 默认浏览器 → `condenser://auth` 回调）/ 分享面板在 Mac 上全部实测通过，截图
`tmp/2026-09-04-mac-catalyst/`。

两个真正的发现：**① `.sidebarAdaptable` 的 TabView 在 Mac 上切 tab 丢 Observable 环境**
（Fatal error，修法是每个 tab 内容各挂一次 `.environment(reader)`）；**② Catalyst 走
data-protection keychain**，ad-hoc 签名的构建 `SecItemAdd` 静默 -34018，token 存不住——
`make build-mac` 因此缺省团队签名 + entitlements 里显式写 `keychain-access-groups`
（不写 Xcode 不嵌 profile），`KeychainStore.write` 也从此把失败写进 OSLog。工程细节、
走查的三个坑与商店侧待办见 `ios/AGENTS.md`「Mac Catalyst」。
