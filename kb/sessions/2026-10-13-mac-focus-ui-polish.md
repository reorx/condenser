---
created: 2026-10-13
tags:
  - ios
  - mac-catalyst
  - swiftui
---

# Mac 焦点更新提醒与界面修整

Mac 阅读列表重新获得焦点时，若距上一次真实 focus 超过十分钟，就按当前列表范围向远端查询新内容数量。有新增则显示顶部蓝色胶囊，点击主体才回顶刷新，关闭只隐藏提示。登录页在 iPhone 和 Mac 上都改用 Condenser 主图标；Mac 当前页面标题改为靠左排列。

## 实现

- Kit 新增 `FocusRefreshPolicy`，先写六个行为测试再实现：首次 focus 不重复请求；间隔严格 >600 秒才检查；每次真实 focus 重置基准；重复通知、持续前台和短时间切换不触发检查。
- `MacWindowFocus` 按当前可见列表、所属窗口与应用激活状态投递焦点变化。Catalyst 切换应用时 UIKit 通知不总是完整，因此同时监听公开的 AppKit 应用激活通知。隐藏的列表不参与请求。
- `MessageListView` 复用蓝色胶囊，防止并发检查及过期范围结果；`ReaderSession.makeChecker(for:)` 保留频道、信源、feed 和未读过滤。主时间线及 Mac 的单频道、单 feed 共用该行为。
- `readerNavigationTitle()` 在 Mac 使用 editor 工具栏角色，让标题靠左；iPhone 保留原有标题布局。登录页使用已有 `ShareMark` 主图标资产。
- 增加仅 DEBUG 可用的焦点等待时间和登录页走查开关。正常构建默认十分钟，登录页开关不清除 Keychain。

## 验证

- `make test`：350 个测试、48 个 suite 全部通过；新逻辑先验证红灯，再实现通过。
- `make build-mac`、`make build`：Mac Catalyst 与 iOS 模拟器构建成功。
- 本地无网络依赖的模拟服务配合真实 Mac 应用切换验证十项行为，全部通过：长间隔只检查一次、不自动刷新、保留未读过滤、短切无请求、持续 focus 不轮询、关闭不刷新、数量变化重新提醒、点击刷新、刷新保留过滤、刷新后可继续检查零新增。界面走查使用 DEBUG 三秒阈值；600 秒边界由 Kit 行为测试覆盖。
- HN 单 feed 另行验证：计数请求携带 `source=hn`，隐藏的主时间线没有重复请求。
- 截图确认 Mac 左侧标题、蓝色提示及点击刷新后的列表，iPhone / Mac 登录页均显示漏斗主图标。截图归档在 `tmp/2026-10-13-mac-focus/`，其中 `03-hidden-sidebar.png`、`04-ios-login.png`、`05-mac-focus-pill.png`、`07-hn-feed-pill.png`、`08-mac-refreshed.png`、`10-mac-login.png` 为主要证据。
- 测试后恢复原有偏好和阅读快照，停止模拟服务；运行 `mac-dev-cleanup --only sim`，本次启动的模拟器已关闭。Mac 应用以默认设置重新启动。

行为说明已同步 [iOS 文档](../docs/ios.md) 和 `ios/AGENTS.md`。本次无新增待办或已知问题。
