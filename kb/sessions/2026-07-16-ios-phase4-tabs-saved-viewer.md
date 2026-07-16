---
created: 2026-07-16
tags:
  - ios
  - swiftui
  - mobile
---

# iOS Phase 4：补全（三 tab / 收藏 / SnapshotCache / 全屏图 / 设置页）

按 [2026-07-16-ios-reader-app.md](../plans/2026-07-16-ios-reader-app.md) 完成阶段 4，
BDD 先测后写。CondenserKit **63 个测试全绿**（较 phase 3 新增 16 个）；模拟器真实数据
截图走查了全部新界面。**v1 spec 至此全部落地。**

## CondenserKit 新模块

- **`SnapshotCache`** — Caches 目录 JSON 快照（`JSONEncoder/Decoder.condenserAPI` 保持
  日期语义一致）；save 尽力而为静默失败，load 缺失/损坏返回 nil 不 crash（spec 明确要求
  容错，且系统随时可能清 Caches）；key 非法字符替换为 `_`。
- **`TimelineStore` 快照集成** — 可选 `cache`/`cacheKey` 参数：`loadInitial` 先渲染
  快照（items 空且有快照时 `apply(page:)`），网络成功后整页替换并回写；网络失败保留
  快照内容 + error 文案。不配 cache 行为不变。
- **`RecordsStore`** — 收藏列表状态机：`loadInitial`（一次）/ `refresh`（全量替换）；
  `unsave` 乐观移除 + 失败**按原位置**放回；401 → `onUnauthorized`，其余 error 文案。
- **`TokenStore.deviceName`** — UserDefaults 持久化，登出保留；
  `AuthSession.completeLogin` 增加 `deviceName` 参数（LoginView 传入）。
- `Subscription` 补 `Hashable`（NavigationStack path value 用）。

## App 层

- **`MainView`** → iOS 18 `TabView`/`Tab` 三 tab（Timeline / 频道 / 收藏），各自独立
  NavigationStack；频道 tab 的 `NavigationPath` 提到 MainView（debug 深链要 push）。
- **`MessageListView`**（新文件）— 从 TimelineScreen 拆出的列表核心：无限滚动、
  滚动即已读、下拉刷新、详情 sheet、可选 poller 胶囊。`TimelineScreen` 瘦身为
  主 tab 包装（poller 生命周期 + scenePhase flush + 未读开关 + 设置入口）；
  tab 切走 `.task` 自动取消、切回自动重跑，poller 随之停/启。
- **`ChannelsScreen` / `ChannelTimelineScreen`** — enabled 订阅列表（头像/标题/
  @username/未读徽标，`task` + refreshable 刷新未读数）→ push 单频道 timeline
  （`reader.makeChannelStore`，无快照无轮询，滚动已读仍生效）。
- **`SavedScreen`** — RecordsStore 驱动；卡片复用 MessageCard（`showsUnread: false`，
  records 不带已读态）；星标/详情收藏按钮 = unsave。
- **`ImageViewerScreen`** — 详情 sheet 图片点击 → `fullScreenCover`：`TabView(.page)`
  相册滑动切换 + `ZoomableImageView`（UIScrollView 1x–4x 捏合、双击 1x/2.5x）+
  纵向为主的下拉手势关闭（背景透明度随位移变化）。
- **`SettingsScreen`** — gear 弹出：服务器地址/设备名只读、主题跟随系统、登出
  （confirmationDialog + flushNow，footer 注明服务端吊销走 web）、版本号。
- **`ReaderSession`** — 新增 records store、`makeChannelStore`、SnapshotCache 接线
  （主 timeline key `timeline-all`，unread 视图不落快照；subscriptions init 时先读
  快照、加载成功后回写）；`channelTitle(for message:)` / `channelUsername(for:)`
  优先 `message.channel`（records 自包含），回退 subscriptions join。

## 开发调试基建（记入 ios/AGENTS.md）

**CLI 驱动的界面走查**：模拟器窗口在另一个 Space 时 AppleScript 数不到窗口、
cliclick 会劫持用户鼠标；`simctl openurl` 自定义 scheme 会弹 "Open in Condenser?"
系统确认框（跨 app 重启存活，要 shutdown+boot 才清掉）。解法：
`SIMCTL_CHILD_CONDENSER_DEBUG_ROUTE=<route>` 启动时注入，`MainView` DEBUG 代码等
timeline 首屏加载完再应用路由。路由：`tab/*`、`channel/<id>`、`settings`、
`detail/<cid>/<mid>`、`viewer/<cid>/<mid>`。

## 遗留 / 下一步

- 端到端授权流程（真实 `ASWebAuthenticationSession`）仍待真机/手动验证一次。
- 视频播放、link-preview 面板：v1 非目标（v1.5 再议）。
- 收藏在 timeline 与收藏 tab 间不做实时同步（收藏 tab 每次进入 refresh 拉平）。
- 真机部署需在 project.yml 配 `DEVELOPMENT_TEAM`。
