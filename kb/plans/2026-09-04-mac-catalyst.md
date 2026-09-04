---
created: 2026-09-04
tags:
  - ios
  - macos
  - catalyst
  - plan
---

# iOS app 编成 Mac app：Mac Catalyst

> 起因：用户想让 iOS app 在 macOS 上跑，并在 Mac App Store 上能找到、能装。
> 本 plan 记路线比较、落地范围、实测发现与商店侧待办。代码适配 + 本地跑通已完成
> （2026-09-04），Mac App Store 上架部分**刻意延后**到 iOS 审核解掉之后。

## 1. 路线比较

| 路线 | 代码量 | 体验 | 商店侧 |
|---|---|---|---|
| Designed for iPhone（iOS 二进制在 Apple Silicon 上原样跑） | 0 | 固定竖屏手机窗口，不能拉伸 | 默认随 iOS 版列入 Mac App Store，一个勾 |
| **Mac Catalyst**（选中） | 实测零改动可编译；适配约 1 天 | 真正的可缩放窗口、侧栏、菜单栏 | 同 record 加 macOS 平台版本，需 Mac 证书 + 沙盒 + Mac 截图 + 单独审核 |
| 原生 macOS target | 5 个 UIKit 文件重写（`SelectableTextView` 最重）+ ~30 处条件编译，4 天+ | 最正 | 同上 |

决定：Catalyst。一个只读阅读器的收益不值原生 target 的成本；Designed for iPhone 的
窗口不是「在 Mac 上用」而是「在 Mac 上看手机」。

## 2. 落地（已完成）

**工程**（`ios/project.yml`）：`SUPPORTS_MACCATALYST: YES`；
`TARGETED_DEVICE_FAMILY[sdk=macosx*]: "2,6"`（Catalyst 从 iPad idiom 派生，6 =
Optimize for Mac，控件按 AppKit 尺寸 1:1；base 仍是 `"1"`，iOS 版保持 iPhone only——
加 2 就要交 iPad 截图）；`SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD: NO`；
`DERIVE_MACCATALYST_PRODUCT_BUNDLE_IDENTIFIER: NO`（同 bundle ID → 同一 app record 的
macOS 平台，universal purchase，USD 2.00 买一次两端都有）；
`CODE_SIGN_ENTITLEMENTS[sdk=macosx*]` → `Condenser-macCatalyst.entitlements`
（App Sandbox、network.client、photos-library、keychain-access-groups）。
xcodegen 的 `KEY[sdk=…]` 条件键实测按 SDK 生效（`-showBuildSettings` 两边核过）。

**代码**（全部集中在 `UI/Platform.swift` + 各处一行）：

- `Platform.isMac`：编译期 `targetEnvironment(macCatalyst)`。
- `MainView`：`.tabViewStyle(.sidebarAdaptable)`——Mac 变侧栏，iPhone 不变。
- `readingColumn()`：timeline / 收藏列表限宽 720pt 居中；登录表单 `maxWidth 480`。
- `detailSheetPresentation()`：四个详情抽屉 iPhone 仍两档 detent + grabber，Mac 改
  `.presentationSizing(.page)` + 右上关闭钮（`keyboardShortcut(.cancelAction)`）。
  Catalyst 默认 sheet 约 460pt 见方，读长文像从门缝里看。
- `AutoHideBars`：Mac 直通（桌面不缺那几十点，栏随滚动闪现像抽搐）。
- `openExternalURL`：Mac 直接 `UIApplication.shared.open`（没有 X app 可深链；
  Catalyst 的 SFSafariViewController 本来就是转手给 Safari）。
- `ImageViewerScreen` 关闭钮加 Esc。
- `Platform.deviceName`：Catalyst 的 `UIDevice.current.name` 是字面的「iPad」，Mac 取
  `ProcessInfo.hostName` 去 `.local`。登录页与设置页共用。

**Makefile**：`build-mac`（缺省团队签名，`MAC_SIGN=adhoc` 只编译）/ `run-mac`
（AppleScript 优雅退出上一个实例后直接跑二进制，环境变量能传进去）/ `dev-mac`。

## 3. 实测发现（两个真问题 + 三个工具坑）

1. **`.sidebarAdaptable` 切 tab 丢 Observable**：Mac 上切到「设置」即
   `Fatal error: No Observable object of type ReaderSession found`。外层
   `tabs(reader).environment(reader)` 在首个 tab 有效，非首个 tab 的视图树拿不到。
   修法：每个 tab 的 NavigationStack 各挂一次 `.environment(reader)`，DEBUG 的三个 sheet
   同样。iPhone 不受影响。
2. **Keychain -34018**：Catalyst 走 data-protection keychain（和 iOS 一样），要求
   `keychain-access-groups` + profile 里的 application-identifier。ad-hoc 签名什么都没有，
   `SecItemAdd` 静默失败，症状是重启回登录页而服务器地址（UserDefaults）还在——正是
   plan 前预判的那个风险点。修法三件：`make build-mac` 缺省团队签名（destination 指向
   这台 Mac 才能 `-allowProvisioningDeviceRegistration`，generic 下报「no devices」）；
   entitlements 显式写 `keychain-access-groups`（不写 Xcode 的 Debug 构建根本不嵌 profile）；
   `KeychainStore.write` 把非零状态写进 OSLog——这次要不是加了 print 根本看不见。
   换签名后首次启动 macOS 问一次「differs from previously opened versions」，Open Anyway。
3. 工具坑：① `pkill` 出来的实例被 macOS 记成异常退出，**下次启动**先弹模态的
   「Condenser quit unexpectedly」把主窗口挡住，看起来像 app 起不来；② 第二份
   DerivedData 里的同 bundle ID app 会被 `tell application id … to activate` 解析并启动，
   跑的是老代码（症状：明明改了却没变）；③ `screencapture -R` 截屏幕区域，要先 activate。

**验收**（`tmp/2026-09-04-mac-catalyst/`，含 `shot.sh` / `winid.swift` 截图脚本）：
timeline、HN / RSS 详情抽屉（page 尺寸 + 关闭钮）、设置（主机名）、收藏、订阅、HN feed
push、登录全链路（ASWebAuthenticationSession → Chrome → 密码 → Authorize →
`condenser://auth` 回调 → timeline）、优雅退出后重启会话仍在、点卡片开抽屉、Esc 关闭、
标题外链开 Chrome、分享面板（AirDrop / Mail / Add to Photos…）。iOS 模拟器构建通过，
Kit 287 测试通过。

## 4. 未做：Mac App Store 上架

等 iOS 1.0.0 的 Guideline 2.1 退回解掉再动——同一个 app record，两个平台的审核不要
叠在一起。到时候要做的：

1. 证书：Mac App Distribution + Mac Installer Distribution（`asc certificates create`，
   Admin key）；macOS App Store 型 profile（automatic 会补）。
2. `make archive` 的 Catalyst 变体：`-destination 'generic/platform=macOS,variant=Mac Catalyst'`，
   导出 method `app-store-connect`，产物是 `.pkg`。Hardened runtime 对 App Store 不是必需，
   沙盒是。
3. ASC：同一 app 加 **macOS** 平台版本（`asc versions create --platform MAC_OS`），Mac
   截图（`asc screenshots sizes` 看 `DESKTOP` 规格，通常 1280×800 / 2880×1800），
   审核详情复用 demo server + demo 账号。
4. 提审前在 Mac 上过一次 TestFlight（Mac 也有 TestFlight）。
5. 商店文案里点一句「Mac 版同一账号买一次」。

## 5. 相关

- `ios/AGENTS.md`「Mac Catalyst」——工程细节与走查坑的权威位置。
- `kb/docs/ios.md`「Mac Catalyst」——feature history 条目。
- 私密 KB `kb.private/condenser/kb/docs/ios-app-store-release.md`——iOS 审核现状
  （2026-08-16 2.1 退回，`asc review status --app …`）。
