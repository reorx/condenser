---
created: 2026-07-18
tags:
  - ios
  - swiftui
  - ux
  - bugfix
---

# iOS 阅读体验优化：修复多图排版溢出与未读刷新残留，滚动隐藏操作栏等六项交互改进

## 概要

真机体验 iOS 版后发现两个 bug 和一批交互问题。bug 一：相册多图时缩略图溢出卡片区域、
互相叠加 —— 根因是直接对 `AuthedAsyncImage`（内部 `Image.resizable().fill`）套
`.aspectRatio(1, .fill)`，在 LazyVGrid 无界高度下图片按原始像素尺寸参与布局；改为
「`Color.clear.aspectRatio` 固定占位盒 + overlay 装图 + clipShape 裁剪」后图片只做视觉
填充、不再影响布局。bug 二：未读视图下拉刷新后刚划过已读的消息不消失 —— 已读上报是
2 秒 debounce 的批量队列，刷新时常常还没发出去，服务端仍视为未读；`MessageListView.refresh()`
现在先 `readReporter.flushNow()` 再重载。交互改进六项：滚动方向感知的上下操作栏自动隐藏
（新 `AutoHideBars` modifier）、默认只看未读（eye/eye.slash 图标切换，两种模式各落冷启动
快照）、设置改为第 4 个 tab、正文截断时末尾显示蓝色 more（隐藏全文副本测高）、卡片内
链接/图片/网页预览卡直接可点（链接 → in-app Safari，图片 → 全屏查看器）。`make build`
通过、63 个 Kit 测试全绿，模拟器连本地后端截图验证了未读首页、频道页、竖长单图与双图
网格的渲染。

## 修改的文件

- `ios/Condenser/UI/MessageCard.swift` — 核心改动：`photoBox`（固定纵横比占位盒 +
  overlay + clip + contentShape + tap）替代原来的直接 aspectRatio 填充，竖长单图收敛到
  最小 3:4；新增 `TruncatableText`（5 行截断 + 隐藏全文副本测高 → 蓝色 more，链接经
  `linkified` 高亮）；`WebPagePreviewCard` 自带 openURL 点击；新增 `onOpenPhoto` 回调。
- `ios/Condenser/UI/Linkify.swift` — 新文件：`linkified()` 从 MessageDetailSheet 提出共享
  （NSDataDetector 标注 URL → AttributedString 链接）。
- `ios/Condenser/UI/AutoHideBars.swift` — 新文件：`onScrollGeometryChange` 判定滚动方向，
  `toolbarVisibility` 同时隐藏/恢复导航栏与 tab 栏；`autoHideBars()` extension。
- `ios/Condenser/UI/MessageListView.swift` — refresh 前先 `flushNow()`；挂 `autoHideBars`、
  列表层 `openURL` 环境（→ in-app Safari sheet）、`fullScreenCover` 图片查看器；
  MessageCard 传 `onOpenPhoto`。
- `ios/Condenser/UI/SavedScreen.swift` — 同 MessageListView 的 Safari/查看器/autoHideBars 接线。
- `ios/Condenser/UI/TimelineScreen.swift` — 移除设置入口；切换按钮改 eye/eye.slash。
- `ios/Condenser/Services/ReaderSession.swift` — 默认 `unreadOnly = true`；快照 key 拆为
  `timeline-all` / `timeline-unread`，两种模式都缓存。
- `ios/Condenser/UI/MainView.swift` — 加第 4 个「设置」tab；debug 路由 `settings` 改切 tab。
- `ios/Condenser/UI/SettingsScreen.swift` — 去掉自带 NavigationStack 与「完成」按钮
  （由挂载点提供导航容器）。
- `ios/Condenser/UI/MessageDetailSheet.swift` — 改用共享 `linkified`；删除网页卡外层
  tap（卡片自持）。
- `AGENTS.md` / `ios/AGENTS.md` — iOS 段落补充本次改动；debug 路由 settings 说明更新。

## 注意事项

- **SwiftUI 图片装盒 pattern**：`Image.resizable().aspectRatio(contentMode: .fill)` 参与
  布局时会以原图像素尺寸为 ideal size，在 LazyVGrid/无界高度容器里必然溢出。正确做法是
  `Color.clear.aspectRatio(ratio, .fit)` 定布局，图片放 `.overlay` 里再 `clipShape`，并加
  `contentShape` 约束点击热区（否则溢出部分会偷走相邻视图的 tap）。
- **乐观队列 + 服务端过滤视图的刷新时序**：凡是「本地 debounce 上报 + 服务端条件查询」
  组合（这里是已读队列 vs unread_only timeline），刷新前必须先冲刷队列，否则服务端状态
  滞后于本地视觉状态，刷新反而"复活"已处理的条目。
- **Text 截断检测**：`lineLimit` 的 Text 用 `.background` 放一个 `.hidden()` +
  `fixedSize(vertical)` 的全文副本，两个 `onGeometryChange` 比高度差即知是否截断；
  background 不参与布局所以不撑高卡片。
- **列表层 `openURL` 环境接管**：`.environment(\.openURL, OpenURLAction)` 挂在列表容器上，
  卡片内 AttributedString 链接、`WebPagePreviewCard` 的 `openURL(url)` 全部收敛到一个
  in-app Safari sheet；详情 sheet 内部自己 override，互不干扰。
- **SourceKit 误报**：编辑 app target 文件时 LSP 会报 "No such module 'CondenserKit'" 和
  macOS 平台 API 不可用，是编辑器索引平台问题，以 `make build` 为准。

## 遗留问题

- 正文链接点击与整卡 tap 手势的优先级（链接吃掉 tap、空白处落详情 sheet）只在模拟器验证了
  渲染，未真机实点；建议 `make device` 后实际走查。
- 3 图相册的三列网格未直接截到图（dev DB 首屏没有该消息），但与已验证的双列网格走同一
  `photoBox` 代码路径。
- `AutoHideBars` 在频道 timeline 会连返回按钮一起藏（回滑即恢复，符合 Safari 式惯例）；
  如后续觉得别扭可对 push 层只藏 tab 栏。

## 相关文档

- [iOS reader app 计划](../plans/2026-07-16-ios-reader-app.md) — 本次 session 在其 v1 完成后做阅读体验 polish
- [上一次 session：phase 4](../sessions/2026-07-16-ios-phase4-tabs-saved-viewer.md) — 本次工作的前置状态
