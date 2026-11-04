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

## 返工：最大字号下上行截断（验收 #1 之后）

验收 #1 判 FAIL 的唯一一项：iPhone 17 阅读字号调到最大档「大」（footnote 17pt）时，
「在 Telegram 打开」被 `lineLimit(1)` 截成「在 Telegram...」。原因是上行按钮固定为半行宽，
图标加文字超出了宽度。执行时只在 Mac 上检查了最大档（16pt），刚好放得下。

改动：`actionTextLabel()` 改用 `ViewThatFits`，先试图标加文字，放不下就只留文字，
最后一档再加 `minimumScaleFactor(0.8)` 兜底，四个信源的上行都由它统一处理。

验证（`tmp/2026-11-04-ios-detail-action-bar-rework/`）：
- `make clean` 后 `make build`、`make build-mac` 均通过。
- iPhone 17（402pt）和新建的 iPhone SE 第 3 代（375pt，验完已删）在「正常 / 略大 / 大」三档下
  拍了 Telegram 上行（`telegram-fontscale-both.png`）：前两档保留图标，「大」档去掉图标、
  文字完整、字号不变，两行仍然等分。验收推测 SE 在「略大」档会截断，实测没有。
- 最大档下 HN 有外链（iPhone 17）、HN self-post、RSS 有链接和无链接（SE）都正常。
  X 的上行在 iPhone 上被判定卡片挤到 medium 档以下，没拍到；它的标签比 Telegram 短。
- 第一次复测时 HN 详情一打开就崩，原因是增量构建没有重编调用方（见 `ios/AGENTS.md` 的构建说明），
  `make clean` 后消失。崩溃报告在 `stale-build-crashes/` 里。

## 遗留问题

Mac `.help` 的提示气泡已在验收 #1 中确认。
未进行真机触感与 VoiceOver 朗读验证。

## 相关文档

- [iOS 功能说明](../docs/ios.md) — 更新详情底部动作区与分享入口说明。
