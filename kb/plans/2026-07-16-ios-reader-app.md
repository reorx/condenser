---
created: 2026-07-16
tags:
  - ios
  - swiftui
  - mobile
  - frontend
---

# iOS 阅读器 App（monorepo `ios/` 目录）

condenser 的原生 iOS 阅读客户端：Twitter 式简化阅读体验——紧凑卡片 timeline、点击弹出详情
sheet、顶部"N 条新消息"胶囊、滚动即已读、收藏。**只读不管**：不含订阅管理、filter 管理、
Telegram 登录等 web 管理功能。

依赖后端先落地 device token 认证：见
[2026-07-16-mobile-client-api-device-token.md](2026-07-16-mobile-client-api-device-token.md)。

## 决策记录（已与用户确认）

| 决策点 | 结论 |
|---|---|
| 形态 | 原生 iOS，SwiftUI |
| 项目位置 | 本仓库 `ios/` 目录（monorepo），不开新 repo |
| 认证 | web 跳转授权换 device token（`ASWebAuthenticationSession`），存 Keychain |
| 已读 | 滚动过顶即已读（与 web 一致），批量上报 |
| 详情 | 底部抽屉 sheet（medium/large detents） |
| 缓存 | 轻量：首屏 JSON 快照落盘 + URLCache，不做完整离线库 |
| 图片认证 | 统一带 `Authorization` header 的 URLSession，无 query token |

## 工程结构

```
ios/
  project.yml          # xcodegen 单一事实来源，不手编 .xcodeproj
  Makefile             # make build / test / run（模拟器）/ generate
  Condenser/           # App target（SwiftUI 视图层 + 入口）
  CondenserKit/        # 本地 SPM 包：全部逻辑，纯 Swift 可单测
    Sources/CondenserKit/
    Tests/CondenserKitTests/
```

- 纯命令行工作流（xcodegen + Makefile），沿用 macos-app-bootstrap 的模式适配到 iOS
  （模拟器 run：`xcrun simctl`）。
- 最低 iOS 18（用 `onScrollGeometryChange` 做滚动已读；单人使用，无兼容包袱）。
- Swift Testing 写测试；网络层用自定义 `URLProtocol` mock。

### CondenserKit 模块划分

| 模块 | 职责 |
|---|---|
| `APIClient` | URLSession + Codable；错误统一为 `APIError`（含 401 判别） |
| `Models` | 镜像后端 JSON。**以 `frontend/src/lib/types.ts` 为字段事实来源**，逐一对照翻译成 Swift（snake_case → `CodingKeys`）；日期沿用 web 版语义：UTC，tz-aware 与 naive 两种形式都要能解析 |
| `TokenStore` | Keychain 读写 device token + 服务器地址（UserDefaults） |
| `AuthFlow` | 组装 `/authorize?device_name=` URL、解析 `condenser://auth` 回调 |
| `TimelineStore` | 游标分页状态机（`@Observable`）：加载/追加/刷新/去重，`head_cursor` 记录 |
| `ReadReporter` | 已读收集器：卡片滚出顶部 → 入队 → debounce ~2s 批量 `POST /api/read`；本地乐观已读集合；失败重回队列 |
| `NewContentPoller` | 前台每 30s + `scenePhase` 回到 active 时立即查 `GET /api/timeline/new?after=head_cursor`，发布未读新消息计数 |
| `SnapshotCache` | timeline 首页 + subscriptions 响应 JSON 落盘（Caches 目录）；冷启动先渲染快照再后台刷新 |
| `ImageLoader` | 带 auth header 的图片加载（`URLCache` 磁盘缓存），供 `AuthedAsyncImage` 视图用 |

### 使用的后端端点（全集）

`GET /api/timeline`（分页 + `channel_id` 过滤 + `unread_only`）、`GET /api/timeline/new`、
`GET /api/subscriptions`、`POST /api/read`（body `{items: [{channel_id, message_id}]}`）、
`GET/POST /api/records`、`DELETE /api/records/{cid}/{mid}`、
`GET /api/media/{cid}/{mid}`（`?thumb=1` 缩略图）、`GET /api/channels/{id}/avatar`。
（`/api/preview/image` 留给 v1.5 的 link-preview 面板，v1 不用——卡片内嵌
WebPagePreview 缩略图走媒体代理。）
请求/响应形状以 `frontend/src/lib/api.ts` + `types.ts` 为准，实现时逐端点对照。
注意：timeline item 只带 `channel_id`，**频道名/username 由 subscriptions 数据在客户端
join**（同 web 版 `useChannelLabels`）——卡片头的频道名和详情页 t.me 链接都依赖这个 join。

## 信息架构与界面

`TabView` 三个 tab：**Timeline / 频道 / 收藏**。设置入口放 Timeline 导航栏 gear。

### 首启与认证

1. 首次启动：输入服务器地址（默认 `https://condenser.reorx.com`）→ "登录" 按钮
2. `ASWebAuthenticationSession` 打开 `<host>/authorize?device_name=<设备名>`
   （设备名默认 `UIDevice.current.name`，可编辑）
3. 回调 `condenser://auth?token=...` → 存 Keychain → 进主界面；`error=denied` 或用户直接
   关闭 session（收到 `ASWebAuthenticationSessionError.canceledLogin`）→ 回登录页
4. 任意请求 401 → 清 token → 回登录页（toast 提示）

### Timeline tab

- 紧凑卡片：频道头像 + 频道名 + 相对时间；正文预览（`lineLimit(5)`）；媒体缩略图
  （单图按 MediaItem 的 `width`/`height` 预留纵横比，多图九宫格方形，与 web 版策略一致；
  album 已由后端合并为单 unit）；转发标记（`↪ 来源名`）；收藏星标（已收藏时 amber）。
- **滚动即已读**：`onScrollGeometryChange` 检测卡片滚出视口顶部 → `ReadReporter` 入队。
- **新消息胶囊**：`NewContentPoller` 计数 > 0 时顶部悬浮 "N 条新消息"，点击 → 刷新 + 滚回顶。
- 无限滚动（接近底部预取下一页）+ 下拉刷新。
- 导航栏：未读过滤开关（`unread=1` 重查）、设置 gear。

### 频道 tab

订阅列表（头像 / 标题 / 未读徽标，来自 `GET /api/subscriptions`，只列 enabled）。
点击 → push 进该频道的 timeline（**同一 Timeline 视图复用**，带 `channel` 参数）。

### 详情 sheet

点卡片 → bottom sheet（`presentationDetents([.medium, .large])`，拖动指示条）：

- 全文（链接可点 → `SFSafariViewController`；web 版的 link-preview 面板 **v1.5 再说**）
- 原图（点击 → 全屏图片浏览器：缩放/滑动切换/下滑关闭）
- 转发来源、发布时间（本地时区展示）、收藏按钮（乐观切换）、"在 Telegram 打开"
  （`https://t.me/<username>/<mid>`，无 username 时隐藏）
- 视频/文件：v1 只显示类型 chip，不播放

### 收藏 tab

`GET /api/records` 列表（快照渲染，自包含），点开同一详情 sheet，可取消收藏（乐观 + 失败回滚）。

### 设置页

服务器地址（只读展示）、设备名、外观跟随系统、登出（清 Keychain；服务端吊销留给 web 端）。

## 错误处理与状态

- 错误只在顶层（Store / View 层）处理，CondenserKit 底层函数直接 throw。
- 网络失败：保留现有内容 + 非阻塞 toast；下拉可重试。
- 冷启动：有快照 → 立即渲染 + 后台刷新；无快照 → skeleton 占位。

## 测试策略（BDD：先写行为测试）

CondenserKitTests，`URLProtocol` mock 网络：

1. 分页状态机：两页游标衔接、`has_more=false` 停止、刷新后去重
2. `ReadReporter`：入队 → debounce 合并为一次批量请求；失败后重试队列不丢
3. `NewContentPoller`：`head_cursor` 传参正确、计数发布、归零
4. `AuthFlow`：回调 URL 解析（token / error / 畸形输入）
5. Models：用真实后端 JSON fixture（从 dev 服务器抓取存入 Tests/Fixtures）做解码回归
6. `SnapshotCache`：写入→读回→损坏文件容错（返回 nil 不 crash）

UI 层以手动验证为主（模拟器 `make run`），不做 UI 自动化测试。

## 非目标（v1）

订阅增删、filter 管理、Telegram 登录/refresh 等管理操作；视频播放；link-preview 面板；
推送通知；完整离线库；iPad 适配（能跑即可，不专门布局）。

## 实施阶段

1. **骨架**：`ios/` 脚手架（xcodegen + Makefile + 空 App + CondenserKit）跑通 build/test/run
2. **认证**：TokenStore + AuthFlow + 首启页 + 401 处理（依赖后端 spec 完成）
3. **核心阅读**：APIClient + Models + TimelineStore + Timeline 卡片 + 详情 sheet + 滚动已读 + 新消息胶囊
4. **补全**：频道 tab、收藏 tab、SnapshotCache、图片全屏浏览器、设置页、打磨
