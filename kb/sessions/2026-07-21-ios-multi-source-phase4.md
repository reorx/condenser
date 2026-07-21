---
created: 2026-07-21
tags:
  - session
  - ios
  - multi-source
  - hackernews
  - swiftui
---

# iOS 多信源适配（Phase 4）：envelope 契约 + 信源切换 + HN 卡片，多信源计划收官

## 概要

按 `kb/plans/2026-07-19-multi-source-hn.md` 的 Phase 4 完成 iOS 客户端对多信源 breaking API 的适配。CondenserKit 全面 envelope 化：`TimelineItem`（source/key/datetime/is_read/is_saved + `telegram?`/`hn?` payload）取代扁平 `DisplayMessage` 条目，read/save 以 item key（`tg:{cid}:{mid}` / `hn:{sid}`）为 API 出入参，订阅数据源从 `/api/subscriptions` 切换到 `GET /api/sources`。App 侧新增 Timeline 左上角信源切换 Menu（All + 已添加信源，不硬编码）、tab 2「频道」改「订阅」（信源 → 订阅两级结构）、`HnCard`/`HnDetailSheet`（HN story 列表卡与详情）。BDD 流程：先重生成真实 JSON fixtures（dev DB 已有 691 条 HN story）并改写 Kit 测试，再实现到 114 个测试全绿；`make build` 通过后模拟器对接本地后端走查 5 个界面确认无回归。至此多信源计划四个 phase 全部完成，**部署顺序约束解除**（决策 (b)：三端就绪后一起上线）。

## 修改的文件

**CondenserKit（Sources）**

- `Models.swift` — 重写：新增 `TimelineItem` envelope、`HnStory`（含 `commentsURL`/`externalURL`/`primaryURL` 派生、`isJob`）、`LinkPreview`、`SourceGroup`/`SourceSub`/`SubChannelID`（int/string 双形态 `channel_id`）、`SourceID` 常量 + 展示名；`DisplayMessage` 移除 `isRead`/`isSaved`/`ref`/`unitKey`；删除 `Subscription`/`MsgRef`
- `CondenserAPI.swift` / `APIClient.swift` — 协议与实现改为 key 出入参：`markRead(keys:)`、`saveRecord(key:)`、`deleteRecord(key:)`（`DELETE /api/records/{key}`）、`records() -> [TimelineItem]`、新增 `sources()`；timeline/timelineNew 增加 `source` 参数
- `TimelineStore.swift` — items 为 `[TimelineItem]`，新增 `source` 维度；去重/toggleSaved/markLocallyRead 全部按 key
- `RecordsStore.swift` — envelope 化，unsave 按 key
- `ReadReporter.swift` — `readRefs: Set<MsgRef>` → `readKeys: Set<String>`
- `NewContentPoller.swift` — 增加 `source` 参数透传
- `SnapshotCache.swift` — 目录带契约版本号（`condenser-snapshots-v2`），旧契约快照 decode 失败按 miss
- `HnText.swift`（新增）— `hnPlainText(fromHTML:)`：HN self-post HTML 转纯文本（`<p>`/`<br>` 转换、`<a>` 还原完整 href、实体解码）

**CondenserKit（Tests）** — 全套改写至新契约：`ModelsTests`（envelope/HN shapes/sources/records fixture 解码）、`TimelineStoreTests`（共享 `StubAPI`/`makeItem`/`makeHnItem` helper + source 透传、混排保序、HN key save）、`ReadReporterTests`/`RecordsStoreTests`/`NewContentPollerTests`/`APIClientTests`（key 与 source 断言、`sources()` 解码）、`SnapshotCacheTests`（新增旧契约快照 = miss 用例）、`ForwardSourceTests`（构造器适配）、`HnTextTests`（新增）；fixtures 重新生成（`timeline_page` 混合页 / `timeline_page_tg` / `timeline_page_hn` / `hn_shapes` / `sources` / `records`，删除 `subscriptions.json`）

**App（Condenser/）**

- `Services/ReaderSession.swift` — 以 `/api/sources` 为唯一订阅数据源（`sources`/`loadSources` + 快照）；`selectedSource` + `setSource` 重建 timeline/poller；快照 key 按 `(source, unread)` 组合；新增 `makeHnStore()`
- `UI/MessageListView.swift` — 按 `item.source` 分发卡片与详情 sheet；scroll-to-read 上报 key；查看器/fetch-older 保持 TG 专属
- `UI/MessageCard.swift` / `UI/MessageDetailSheet.swift` — 接收 `item + message`，已读/收藏态取自 envelope
- `UI/HnCard.swift`（新增）— `HnGlyph` Y 徽标 + 标题（点击开原文，self-post 回落评论页）+ score/评论数/域名/当日排名 meta，job 弱化
- `UI/HnDetailSheet.swift`（新增）— 标题/提交信息/self-post 正文（`hnPlainText`）/预取 preview 卡/打开原文与 HN 评论按钮
- `UI/ChannelsScreen.swift` → `UI/SubscriptionsScreen.swift`（重命名+重写）— 信源分 section 的订阅列表，`SubDestination` 路由到 `ChannelTimelineScreen`（改收 `SourceSub`）/ `HnFeedTimelineScreen`（新增）
- `UI/TimelineScreen.swift` — 左上角信源切换 Menu（Picker in Menu），标题跟随信源；`loadSources` 取代 `loadSubscriptions`
- `UI/SavedScreen.swift` — envelope 化 + 按 source 分发卡片/详情
- `UI/MainView.swift` — tab「频道」→「订阅」（icon `square.stack`）；debug 路由新增 `hn`、`tab/subs`，`detail`/`viewer` 按 key 查找

**文档 / 工具**

- `AGENTS.md`（根）— iOS 段落追加 Phase 4 详述；状态段「Do NOT deploy until Phase 4」改为约束解除
- `ios/AGENTS.md` — 顶部追加多信源契约说明；debug route 列表更新
- `tmp/make_ios_fixtures.py`（gitignore，不入库）— 重写为 envelope fixture 生成器；HN record fixture 用「临时 save → 渲染 → 删除」保证 dev DB 零残留

## 注意事项

- **SnapshotCache 的版本策略**：breaking 契约变更靠换目录（`condenser-snapshots-v2`）而不是清文件——`load` 本来就 `try?` 容错，旧快照自然 miss；以后再 break 契约只需 bump `contractVersion`
- **`SubChannelID` 双形态**：`subscriptions.channel_id` 是 SQLite BareField（TG=int，HN=str），Swift 侧用 enum + 单值容器先试 Int 再 String，别用 `String` 硬吞（会丢掉 TG 频道 id 的数值语义）
- **HN HTML 正则的坑**：`<p[^>]*>` 会误伤 `<pre>`，必须写 `<p(\s[^>]*)?>`；实体解码 `&amp;` 必须放最后，否则 `&amp;lt;` 被二次解码成 `<`
- **fixture 生成的净零副作用模式**：需要一条 HN saved record 的真实渲染 JSON 时，在脚本里 `save_item → render → delete_saved_item`，避免污染 dev DB
- **未知信源的前向兼容**：`TimelineItem.source` 用 String 而非 enum，新信源上线时旧 app 解码不炸、卡片分发处静默跳过
- SourceKit 的 diagnostics 在大规模重构中长期滞后（报 stale 错误、"No such module"），以 `swift test` / `make build` 为准

## 遗留问题

- 信源切换 Menu 的展开态未截图验证（模拟器窗口不在当前 Space，点不到）；切换逻辑本身有 Kit 测试覆盖（source 透传、poller 重建），后续真机使用时顺手确认即可
- 真机端到端 `ASWebAuthenticationSession` 验证仍未做（Phase 3 遗留，与本次无关）
- 部署时需同步给真机重装新版 app（`make device`），旧 app 撞新后端会解析失败——这是既定决策 (b) 的一部分

## 相关文档

- [多信源架构 + Hacker News 信源计划](../plans/2026-07-19-multi-source-hn.md) — 本次 session 按此计划的 Phase 4 实施，至此全计划完成
- [iOS 阅读客户端设计](../plans/2026-07-16-ios-reader-app.md) — 参考（工程分层与测试约定的出处）
