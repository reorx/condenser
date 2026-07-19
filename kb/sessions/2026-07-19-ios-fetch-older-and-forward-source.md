---
created: 2026-07-19
tags:
  - ios
  - swiftui
  - backend
  - timeline
  - fetch-older
  - forward
---

# iOS 底部上拉加载更早消息 + 转发消息以来源为主体

## 概要

本次 session 为 iOS 端新增两个阅读功能，均涉及后端配合。（1）**底部上拉 fetch-older**：
频道时间线本地历史翻完（`next_cursor` 为 null）后，客户端没有游标可以接上
`POST /api/tg/fetch-older/{id}` 新拉回的旧消息——后端给 `/api/timeline` 响应新增了
`end_cursor` 字段（本页最后一个单元的锚点，到底时仍存在）补上这个缺口；iOS 在频道
时间线滚到底后出现 footer，继续上拉越过 70pt 阈值触发 fetch-older，再用 `end_cursor`
续接翻页（拉到超过一页时无限滚动自动恢复；返回 0 条则显示"没有更早的消息了"并
sticky 到下次刷新）。聚合 All/Unread 视图无单频道语义，不启用该手势。（2）**转发消息
主体化**：转发卡片（列表 + 详情 sheet）的头像和标题改为来源频道/用户（`forwardSource`
级联：频道名 → 用户名 → post_author），小字区显示 "Forwarded by 订阅频道名 · 时间"；
来源头像复用 `/api/channels/{id}/avatar` 代理（模拟器实测未订阅公开频道也能加载），
解析不了的陌生频道后端从 500 硬化为 404，iOS 回退首字母头像。全程 BDD：后端 3 个新
测试（69 通过）、Kit 约 16 个新测试（99 通过），模拟器截图验证转发渲染，真实后端 +
真实 Telegram 走通 fetch-older → `end_cursor` 续接全链路（2 条 → 拉回 30 条 → 续接
返回 30 条）。

## 修改的文件

后端：

- `condenser/timeline.py` — `query_timeline` 新增 `end_cursor`：有内容就锚定本页最后
  单元；`next_cursor` 只在 `has_more` 时等于它
- `condenser/routers/channels.py` — 头像代理把 `get_channel_photo` 的解析异常收敛为
  404（转发来源频道 restart 后 bare-id 解析失败的场景）
- `tests/test_backend.py` — 新增 `end_cursor` 续接、`forward_info` 序列化（此前无覆盖）、
  头像 404 硬化三个测试
- `frontend/src/lib/types.ts` — `TimelinePage` 镜像补 `end_cursor`（web 端暂不使用）

iOS Kit（`ios/CondenserKit/`）：

- `Models.swift` — `TimelinePage.endCursor`；新增 `ForwardSource` +
  `DisplayMessage.forwardSource` 级联解析（隐藏来源返回 nil）
- `CondenserAPI.swift` / `APIClient.swift` — 协议与实现新增
  `fetchOlder(channelID:count:) -> Int`（POST fetch-older，解析 `fetched`）
- `TimelineStore.swift` — 新状态 `isFetchingOlder` / `olderExhausted` / 私有 `endCursor`；
  `fetchOlderFromServer()`：fetch-older → 用 `endCursor` 续接 append（列表为空时整页
  替换）；`apply` 重置 `olderExhausted`
- `PullToLoadOlderModel.swift`（新）— 底部 overscroll 手势决策（阈值触发、单手势一次、
  回弹复位、非拖拽不触发）+ `bottomOverscroll` 几何换算（短内容也归零）
- 测试：`TimelineStoreTests`（fetch-older 5 个场景）、`PullToLoadOlderModelTests`、
  `ForwardSourceTests`、`APIClientTests`（fetchOlder 请求）

iOS App（`ios/Condenser/UI/`）：

- `MessageListView.swift` — ScrollView 挂 `onScrollPhaseChange` + `onScrollGeometryChange`
  喂手势模型；`fetchOlderFooter` 三态（可上拉 / 拉取中 / 没有更早）；仅
  `store.channelID != nil` 启用
- `MessageCard.swift` / `MessageDetailSheet.swift` — header 以 `forwardSource` 为主体，
  小字 "Forwarded by X · 时间"；隐藏来源降级为原"转发"标签（删除旧 `forwardLabel`）
- `AuthedAsyncImage.swift` — `ChannelAvatarView.channelID` 改为 `Int?`（nil 不发请求，
  按标题字符稳定取色兜底）

文档：`AGENTS.md`（timeline 模块行 + iOS 段新功能）、`kb/docs/content-update-mechanism.md`
（fetch-older 的客户端接入方式）。

## 注意事项

- **`end_cursor` 的设计**：不改 `next_cursor` 语义（web 的 `useInfiniteQuery` 靠
  `next_cursor == null` 判停，动它会翻页死循环），而是加一个"到底了也存在"的并行锚点。
  客户端续接时新拉的历史严格更旧，天然去重（store 仍按 `unitKey` 防御）。
- **底部手势与 AutoHideBars 的共存**：bars 显隐改 safe-area insets 会反馈进滚动几何
  （2026-07-18 的自激振荡卡死教训）。本次手势路径只发网络请求、不改任何布局状态，且
  触发要求 `isDragging`（tracking/interacting，不含 decelerating——惯性回弹不算意图）。
  多个 `onScrollGeometryChange` / `onScrollPhaseChange` 可以共存于同一 ScrollView。
- **overscroll 几何**：`maxOffset = max(contentHeight + bottomInset - containerHeight,
  -topInset)`，短内容（不满一屏）静止时也归零，否则会误触发。
- **Swift Testing 陷阱**：`#expect(model.mutatingMethod(...))` 编译失败（宏展开里 `$0`
  不可变），mutating 调用要先存变量再断言。
- **转发来源头像**：`fwd_from_channel_id` 直接喂 `/api/channels/{id}/avatar` 即可——
  Telethon ingest 时解析过实体，未订阅公开频道实测能出图；失败路径已 404 化，UI 有
  首字母兜底，所以不需要存 username。
- **模拟器手势无法 CLI 注入**：`simctl` 不支持拖拽，Simulator 窗口不在当前 Space 时
  cliclick 也不可达；手势逻辑靠 Kit 纯逻辑单测锁定 + API 层 curl 走通全链路代替。

## 遗留问题

- 上拉触发的真机手感未验证：70pt 阈值如觉得太灵敏/太钝，调
  `PullToLoadOlderModel(threshold:)`。
- 聚合 All/Unread 视图不支持拉更早：如需支持，后端要加 `refresh_all` 式的多频道后台
  fan-out fetch-older 接口（同步逐频道拉太慢），iOS 侧再放开手势。
- fetch-older 是同步 HTTP，遇 Telegram `FloodWaitError` 会挂住请求（无上限退避，
  既有行为）；iOS 只显示 spinner，无超时提示。

## 相关文档

- [内容更新机制文档](../docs/content-update-mechanism.md) — 本次 session 的实现依据
  （fetch-older 的 id 锚定分页），并更新了客户端接入说明
- [iOS reader app 计划](../plans/2026-07-16-ios-reader-app.md) — iOS 端整体设计背景，参考
