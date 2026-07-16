---
created: 2026-07-16
tags:
  - ios
  - swiftui
  - mobile
  - timeline
---

# iOS Phase 3：核心阅读（APIClient + Models + TimelineStore + Timeline UI）

按 [2026-07-16-ios-reader-app.md](../plans/2026-07-16-ios-reader-app.md) 实施阶段 3，
BDD 全程先测后写。CondenserKit 共 **47 个测试全绿**；模拟器用真实数据截图验证了
timeline 渲染（含相册网格、转发标记、未读点、realtime 新消息进入）。

## CondenserKit 新模块

- **`Models.swift`** — 对照 `frontend/src/lib/types.ts` 翻译（snake_case → CodingKeys）：
  `DisplayMessage`（`unitKey = "\(channelID)/\(id)"` 作跨频道稳定 key、`ref` 便捷属性）、
  `MediaItem` / `ForwardInfo` / `ChannelRef` / `WebPagePreview` / `Subscription` /
  `TimelinePage` / `TimelineNew` / `MsgRef`。`parseAPIDate` 兼容 `Z` / `+00:00` /
  小数秒 / naive（补 Z）；`JSONDecoder.condenserAPI` 工厂。
  **fixture 是真实后端 JSON**：`tmp/make_ios_fixtures.py` 直接调 `query_timeline`
  读 `tmp/condenser.db` 生成（绕开服务器/认证），存
  `Tests/CondenserKitTests/Fixtures/`（timeline_page / message_shapes /
  subscriptions / timeline_new）。
- **`APIClient.swift`** — URLSession + Codable；Bearer header；`APIError`：`.unauthorized`
  （401 专属判别）/ `.http(status, detail)`（解析 FastAPI `{detail}`）/ `.invalidResponse`；
  端点：timeline / timelineNew / subscriptions / markRead / records / save/deleteRecord；
  `mediaURL`（`?thumb=1`）/ `avatarURL` / `authedRequest`（图片加载带 header 用）。
- **`CondenserAPI.swift`** — 协议抽象（APIClient 直接 conform），Store 测试注入
  `StubAPI`，不必绕 URLProtocol。
- **`TimelineStore.swift`** — `@MainActor @Observable` 游标分页状态机：
  loadInitial / refresh（重载第一页并替换）/ loadMore（按 unitKey 去重、
  `next_cursor=nil` 停）；`headCursor` 供轮询；`toggleSaved` 乐观 + 失败回滚；
  `markLocallyRead`；错误收敛：401 → `onUnauthorized` 回调，其余进 `error` 文案且保留内容。
- **`ReadReporter.swift`** — 入队即乐观置 `readRefs`；debounce（默认 2s，可注入）合并
  批量 `POST /api/read`；失败重回队列、5× debounce 退避重试；`flushNow()` 供进后台时用。
- **`NewContentPoller.swift`** — `start()` 立即查一次再按 interval（默认 30s）循环；
  `headCursor` 闭包取当前 store 的游标；失败静默保留旧计数；`reset()` 清胶囊。
- 测试基建：`MockURLProtocol`（静态 handler，APIClient 套件 `.serialized`；
  httpBodyStream 读回便于断言 POST body）、`StubAPI`、`makeMsg` 工厂。

## App 层

- **`ReaderSession`** — 登录后组合根：持有 APIClient + 三 store，统一接 401 →
  `AuthSession.handleUnauthorized`（phase 2 的钩子正式接线）。`setUnreadOnly` 重建
  timeline + poller（**两者 unread 过滤必须一致**，见 `timeline.py:query_new` 注释）。
  subscriptions 供频道名 join（timeline item 只带 channel_id）。
- **`TimelineScreen`** — 无限滚动（倒数第 5 项预取）+ `.refreshable` 下拉刷新 +
  新消息胶囊（点击刷新 + 滚回顶 + `poller.reset()`）+ 未读过滤开关 + 登出菜单；
  **滚动即已读**：每张卡 `.onGeometryChange` 检测 `frame(in: .scrollView).maxY < 0`
  （滚出视口顶）→ `readReporter.enqueue`；scenePhase 离开 active → `flushNow()` + 停轮询。
- **`MessageCard`** — 头像 + 频道名 + 相对时间 + 已编辑 + 未读点 + 收藏星（常显）；
  正文 `lineLimit(5)`；单图按 API 宽高预留纵横比、2/4 图 2 列、其余 3 列方格；
  视频/文件 chip；`WebPagePreviewCard`（Telegram 内嵌预览，左竖线样式）。
- **`MessageDetailSheet`** — `.medium/.large` detents；全文 NSDataDetector 链接化 →
  `openURL` 环境接管 → `SFSafariViewController`；原图（非 thumb）、转发来源、本地时区
  时间、收藏、"在 Telegram 打开"（username join，无则隐藏）。
- **`AuthedAsyncImage` / `ChannelAvatarView` / `ImageLoader`** — 带 Bearer header 的
  图片加载；URLCache 手动读写保证磁盘缓存（媒体代理不一定带缓存头）；头像失败回退
  彩色首字母（按 id 稳定取色）。

## 开发调试基建（记入 ios/AGENTS.md）

- `AuthSession` `#if DEBUG` 环境变量注入（`CONDENSER_DEBUG_SERVER/TOKEN`，仅内存态），
  配合 `SIMCTL_CHILD_` 前缀从 simctl 传入 → 跳过交互授权直连本地后端。
- `tmp/condenser.db` 的 devices 表插了 `iOS Simulator (dev)` 行（token 明文
  `devtoken-ios-sim`）。
- Info.plist（project.yml）加了 `NSAllowsLocalNetworking`。

## 遗留 / 下一步（phase 4）

- 频道 tab、收藏 tab、SnapshotCache（冷启动快照）、图片全屏浏览器、设置页。
- 详情 sheet 图片点击暂无全屏缩放（phase 4）；视频不播放（v1 非目标）。
- 端到端授权流程（真实 `ASWebAuthenticationSession`）仍待真机/手动验证一次。
