---
created: 2026-11-04
tags:
  - ios
  - swiftui
  - ui
---

# iOS 详情底部动作区改为两行

## 概要

四个信源共用两行动作区，移除横向滚动。上行保留信源专有动作的文字，X 的打开入口排在最前；
下行依次展示收藏、评论、转发、复制链接、分享图片图标。按钮等分可用宽度，保留 bordered 样式、
状态色和读屏名称，并添加 `.help`。没有专有动作时省去上行与间距。

## 修改的文件

- `ios/Condenser/UI/ItemActionButtons.swift`：标签修饰与 `ItemActionBar`，集中共享分享按钮。
- 四个 `*DetailSheet.swift`：上行只传入专有动作；Telegram 打开入口前移，复制全文触感挂在按钮上。
- `ios/Condenser/UI/Share/ShareImageButton.swift`：纯图标标签并使用阅读字号。
- `ios/AGENTS.md`、`kb/docs/ios.md`：同步两行规则与 DEBUG 分享入口说明。

## 验证

- `cd ios && make build`、`make build-mac` 均通过；Kit 未修改，按计划未运行 Kit 单测。
- Mac Catalyst 走查 X、HN self-post、HN 外链、Telegram、RSS 有链接与无链接样本。
- 988pt 窗口保留侧栏时详情栏为 360pt，上行两个按钮各 160pt（另有边距与间距）；
  设置页实际将字号切到最大 `xLarge` 后，X 和「在 Telegram 打开」均完整显示。
- 本地测试库设置收藏和评论后，确认橙色实心星、靛蓝实心气泡；点击复制链接确认绿色对勾及原始 URL。
- 辅助功能树确认纯图标按钮仍暴露中文名称；评论按钮仍能打开编辑 sheet。
- iPhone 17 / iOS 26.5 模拟器确认 X 短推、HN self-post、RSS 两行布局，以及 RSS 深色模式。
- 模拟器 `CONDENSER_DEBUG_SHARE=1` 成功生成 RSS PNG 并弹出系统分享面板，归档了生成图片。
- 截图、构建日志与走查脚本归档：`tmp/2026-11-04-ios-detail-action-bar/`。
- 已运行 `mac-dev-cleanup --only sim`，释放本次启动的模拟器。

## 注意事项

DEBUG 详情路由不会切回 Timeline tab，设置页验完字号后要先回 Timeline。
首次加载可能停在旧快照，Telegram 调试路由又只在当前列表里找条目，走查时应先备份缓存再用本地库加载。
分享图在模拟器容器的 `tmp/` 中；Mac 的 DEBUG 分享未用于证明出图成功。

## 遗留问题

Mac `.help` 已按计划添加，但自动化悬停与屏幕截图未观察到提示气泡，需在后续验收中人工确认。
未进行真机触感与 VoiceOver 朗读验证。

## 相关文档

- [iOS 功能说明](../docs/ios.md) — 更新详情底部动作区与分享入口说明。
