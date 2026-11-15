# Condenser iOS

condenser 的原生阅读客户端（SwiftUI，iOS 18+），同一份代码也编成 Mac Catalyst app。
只读不管：订阅、过滤、摘要都在服务端配置。四个信源（Telegram / HN / X / RSS）各有一对
卡片和详情 sheet。

去哪里找什么：

- 本文件：命令、工程约定、改代码时不能破坏的约束。
- `../kb/docs/ios.md`：各功能的设计决定与来历。**改某个功能前先读它对应的小节**。
- `../kb/docs/ios-walkthrough.md`：模拟器 / Mac 走查的做法、debug 路由表、走查的坑、
  商店截图的造法。
- `../kb/known-issues.md`：未解决的问题（搜 iOS / Catalyst），动一个区域前先查。
- 私密 KB `~/Code/kb.private/condenser/kb/`：发布状态、ASC 资源 id、审核 demo
  （`docs/ios-app-store-release.md`、`docs/demo-server.md`），发布待办在 `next-up.md`。

## 技术栈与分层

- Swift 5 语言模式（非 Swift 6 strict concurrency）。工具链：Xcode、xcodegen、xcbeautify。
- `CondenserKit/`：本地 SPM 包，纯逻辑（APIClient、Models、Store、状态机）和全部单测。
  **禁止依赖 UIKit**：平台含 macOS，`swift test` 在宿主机直接跑。
- `Condenser/`：app target，UI 与系统胶水，按 `App/` `UI/` `Services/` 组织。
- 新功能 BDD：先在 `CondenserKit/Tests/CondenserKitTests/` 写行为测试（Swift Testing，
  网络用 `MockURLProtocol`），再实现。bug 修复 TDD：先写复现测试。
- Models 的字段事实来源是 `../frontend/src/lib/types.ts`，逐一对照翻译（snake_case →
  `CodingKeys`；日期 UTC，tz-aware 与 naive 两种形式都要能解析）。

## 工程约定

- **构建、测试、运行都走 Makefile，不用 Xcode GUI。**
- 工程定义的唯一事实来源是 `project.yml`（XcodeGen）。**不要手工编辑
  `Condenser.xcodeproj`（已 gitignore）和 `Condenser/Info.plist`**，两者都由它生成。
  - 加源文件：放进 `Condenser/`（目录即 sources），然后 `make gen`。
  - 改 target 配置、Info.plist、URL scheme、包依赖、版本号：改 `project.yml`，然后
    `make gen`（`make build` 已包含）。
- `TARGETED_DEVICE_FAMILY` 的 base 保持 `"1"`（iPhone only）。加进 2，商店就要交 iPad
  截图。Mac 的 `"2,6"` 只挂在 `[sdk=macosx*]` 下。

## 命令

```
make build       # xcodegen + xcodebuild Debug，模拟器 generic destination
make test        # CondenserKit swift test（宿主 macOS 上跑）
make run         # boot 模拟器 + 安装 + 启动已构建的 app（不触发构建）
make dev         # build + run
make device      # 真机构建 + 推送安装（scripts/device.sh）
make archive     # App Store 归档 + 导出 ipa（Release）
make build-mac   # Mac Catalyst Debug 构建（团队签名）
make run-mac     # 启动已构建的 Mac app（优雅退出上一个实例）
make dev-mac     # build-mac + run-mac
make gen         # 仅重新生成 xcodeproj
make clean       # 清理构建产物与生成的 xcodeproj
```

- 单个测试：`cd CondenserKit && swift test --filter <测试名>`。
- 模拟器由 Makefile 的 `SIM` 指定，缺省 `iPhone 17`，本机只保留这一台。
- 产物在 `.build/DerivedData/Build/Products/Debug-{iphonesimulator,iphoneos,maccatalyst}/`。
- 模拟器构建无需签名。真机和 Mac 的签名参数在 xcodebuild 命令行覆盖，不改 `project.yml`。
  Team ID 从 `~/Sync/apple-developer/secrets.env` 的 `APPLE_TEAM_ID` 读（Apple 凭据的唯一
  来源，用法见该目录的 AGENTS.md，文件用 envops 读）。不从钥匙串探测证书：里面还留着旧
  免费 Team 的证书，取首个匹配会探错。
- ⚠️ 改了返回 `some View` 的函数、让它的底层类型变了（比如外面套一层 `ViewThatFits`），
  走查前先 `make clean`。增量构建只重编这一个文件，调用方还按旧类型取返回值，运行时在
  调用处 `EXC_BAD_ACCESS`，崩溃栈只有一帧。
- 构建怪异时先怀疑环境：`make clean && make build` → `xcrun simctl list runtimes` 是否
  为空 → 删 `CondenserKit/.build` 和 DerivedData 下的 SourcePackages →
  `pgrep -l xcodebuild` 查僵尸进程。都无效再看代码。

## 走查

带 debug 环境变量启动，直连本地后端并导航到目标界面，不用点屏幕（仅 DEBUG 构建）：

```bash
SIMCTL_CHILD_CONDENSER_DEBUG_SERVER=http://localhost:8792 \
SIMCTL_CHILD_CONDENSER_DEBUG_TOKEN=devtoken-ios-sim \
SIMCTL_CHILD_CONDENSER_DEBUG_ROUTE=<route> \
  xcrun simctl launch "iPhone 17" com.reorx.condenser
```

route 有 `tab/…`、`settings`、`channel/<id>`、`hn`、`x[/<feed>]`、`rss[/<下标>]`、
`detail/…`、`viewer/…`、`forward/…`。完整路由表、本地后端与 token 的准备、Mac 上的
启动方式、其余 debug 变量都在 `../kb/docs/ios-walkthrough.md`。两条先记住：

- ⚠️ `forward/<key>/<comment>` 会**真实转发**到目标频道。
- Mac app 退出用 AppleScript quit 或 `make run-mac`，**不要 pkill**：下次启动会被「quit
  unexpectedly」模态框挡住。

## 数据契约

已发出去的 build 按它编译时的 API 形状解码，而服务端先升级是常态。

- 条目是 `TimelineItem` envelope：`source` / `key` / `datetime` / `is_read` / `is_saved`，
  加信源载荷（`telegram?` / `hn?` / `x?` / `rss?`）和与之平级的 `feedback` /
  `feedback_reason` / `note` / `annotations`。read、save、转发、标注都按 item key
  （`tg:{cid}:{mid}` / `hn:{sid}` / `x:{id}` / `rss:{id}`）上报。订阅来自 `GET /api/sources`。
- 新字段一律可选，加在旧字段旁边，不改旧字段的形状。枚举带 `other` 兜底（`XVerdict`、
  `ItemFeedback`、`ItemFeedbackReason`），判定通道是开放字典：遇到新值降级渲染，不让整页
  解码失败。
- `SnapshotCache` 目录带契约版本号（现在 `condenser-snapshots-v3`）。缓存的载荷形状变了、
  旧快照会画错时升 `contractVersion`，旧快照按 miss。
- 踩的理由集合由测试与 `db.py`、`lib/sources.ts` 钉在一起，改之前读
  `../kb/docs/x-feedback.md`。

## 改代码时的约束

每条的来历在 `../kb/docs/ios.md` 同名小节。

**阅读界面通用**

- 文字样式用 `.readingFont(.subheadline[, weight:])`，不要写 `.font(.caption)`。Mac
  没有 Dynamic Type，`.font` 写的那一处在 Mac 上偏小且不随字号滑块变，iPhone 上看不出来。
- 外链都过 `openExternalURL`（`UI/ExternalLink.swift`）。列表和详情用
  `.externalLinks(safari:)` 接管子树；sheet 自己的按钮直接调它，因为
  `@Environment(\.openURL)` 在 sheet 里读到的是外层列表那份，Safari 会从 sheet 背后弹出来。
- Purifier 开着时，改写成功的链接不再走 X 深链；明确要进 X app 的按钮传
  `purify: false`。哪些链接不改写由 Kit 的 `isPurifierExcluded(host:path:)` 决定，它与
  后端的 `purifier.rewrite_url`、`purifier_x.parse_status_url` 是同一条规则，两边一起改。
- 客户端从不直连 X：推文媒体走 `/api/preview/image`，头像走 `/api/x/avatar/{handle}`。
- 新加的详情 sheet 走 `detailSheetPresentation()`，iPhone 的 detent、左边缘右滑关闭和
  Mac 的栏形态都从它来。列表用 `.detailPresentation(item:)` 呈现详情。
- 新内容只通过 `NewContentChecker` 问条数，结果是列表上方的蓝色胶囊，点了才回顶刷新。
  不要加轮询或自动刷新。启动的首个 store 停在快照上不打网络（`preferSnapshot`）。

**各信源**

- RSS：列表只带 `content_excerpt`，全文由 `rssEntry(id:)` 在详情里按需取。全文解析出的
  块序列算一次存 `@State`，不要放在 `body` 里重算。卡片不放图。feed key 是整个 feed URL。
- `rssPlainText` 不是 `hnPlainText` 的推广，三条规则刻意相反。`articleBlocks` 复用
  `rssPlainText` 的管线（私用区占位符 U+E000 / U+E001），RSS 全文和 X 长文共用。
- X 的标注定位底本是 `xDisplayedText`，它和 `linkifiedNS` 共享 t.co 替换规则，改一处必须
  连改另一处。
- 标注的 `block` 下标数文本块序列，图块不占号。RSS 摘录回落态禁用高亮入口。引用推卡和
  AI 摘要块刻意不接标注。
- 反馈的 `setFeedback` 与 `setReason` 都走同一个 `write(_:verdict:reason:)`，一次请求写
  整条标签。不要拆成两次写。
- 分享图另画纯 SwiftUI 卡片，不截抽屉：`ImageRenderer` 不渲染 UIKit 桥接视图。哪些内容
  进图由 Kit 的 `ShareCard` 决定并有测试盯着。⚠️ 位图高度超过 8192px 会渲成全黑图且不
  报错，所以先量后画。

**Mac Catalyst**

- 平台判断用 `Platform.isMac`（`UI/Platform.swift`，编译期），不用 `userInterfaceIdiom`。
- 每个 tab 的内容、每个 DEBUG sheet 各挂一次 `.environment(reader)`。`.sidebarAdaptable`
  在 Mac 上切 tab 时拿不到外层注入的 Observable，直接 Fatal error。
- 详情在 Mac 上是列表右侧的栏，不是 sheet：① 详情视图必须 `.id(item.id)`，否则上一条的
  `@State` 留给下一条；② `@Environment(\.dismiss)` 在栏里是空操作，关闭走
  `\.detailColumnDismiss`；③ 容器宽度要量 `.frame(maxWidth: .infinity)` 之后的尺寸，
  量 HStack 自身会布局死循环，吃满 CPU 且退不出。
- `make build-mac` 缺省团队签名。ad-hoc 签名没有 keychain-access-groups，token 写
  Keychain 静默失败（-34018），症状是每次重启回登录页。`MAC_SIGN=adhoc` 目前过不了
  provisioning 检查（见 known-issues）。
- 不要给菜单注册 ⌃⌘S：UIKit 已占用，重复注册直接崩。侧栏开关用的是 ⌥⌘S。
- Mac 版还没有商店发布链路，`make archive` 只出 iOS。

## 真机部署

`make device`：xcodegen → 选设备（唯一已配对的真机，多台时 `DEVICE="<名称或UDID>"`）→
device 构建（`-allowProvisioningUpdates` 自动出 profile）→ `devicectl` 安装并启动。
一次性前提：Xcode 登录付费 Apple ID，手机数据线连 Mac 并信任，开启开发者模式，首次安装
后在手机上信任开发者证书。

- 设备必须先注册进 Team，否则报「Your team has no devices」，`make archive` 也会被挡。
  USB 连上跑一次 `make device` 会自动注册。
- Wi-Fi 对**构建**不够用：xcodebuild 的 destination 发现要求 USB，或手机解锁且在同一
  局域网，否则报「Unable to find a destination」。
- devicectl 报 application-identifier mismatch：手机上是别的 Team 签的旧 app。删掉重装，
  Keychain 里的 device token 会丢，要重走一次 `/authorize` 配对。

## App Store 发布

app 还没上架，build 经 TestFlight 发。**做任何发布操作前先读私密 KB 的
`ios-app-store-release.md`**（当前审核状态、各 build、ASC 资源 id、asc 的坑），提审前再读
`demo-server.md` 并重跑它的 checklist。这里只记工程侧：

- `make archive`：Release 归档 + `exportArchive`，ipa 落在
  `.build/DerivedData/export/Condenser.ipa`。分发证书与 profile 由 Xcode 云签名按需补发。
- 版本号是 `project.yml` 的 `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION`，改完
  `make gen`。
- 新增用到文件时间戳、磁盘容量、系统启动时间等 required-reason API 的代码时，同步补
  `Condenser/PrivacyInfo.xcprivacy` 的声明（现在只声明了 UserDefaults）。新增权限要在
  `project.yml` 加 usage description，下个 build 提审时会被看到。
- App Icon 由 `../tmp/make_ios_appicon.py` 生成，与 PWA 图标同一设计。改设计先改
  `../tmp/make_pwa_icons.py` 再同步这份脚本。
- 上传与分发用 asc CLI，认证已持久化在系统钥匙串，默认 profile 是 Admin 角色，裸跑即可
  （`asc auth status`）。上传：`asc builds upload --app <app id> --ipa <ipa> --wait`。
- ⚠️ `asc review submit --confirm` 是对外不可逆的动作，留给人按。

### TestFlight

内部测试不需要审核，build processing 一 VALID 就能装。它也是唯一能在真机上跑「即将提交的
那个二进制」的途径：App Store 签名的 ipa 没有设备清单，`make device` 装不上。

```bash
asc publish testflight --app <app id> --build <build id> --group <group id> \
  --locale en-US --notify --test-notes "$(cat tmp/<date>-…/test_notes.txt)"
```

- 验收：`asc testflight distribution view --build-id <id>` 的 Internal State 为
  `IN_BETA_TESTING`，`asc builds test-notes list --build-id <id>` 能读回笔记。输出表里
  `Notified: false` 是正常的，组上开着 Auto Notify 时由 Apple 发信。
- ⚠️ What to Test 的字符集是白名单，带 `✕`、`↑` 这类符号会被打回
  `Text for whatsNew contains invalid characters`。界面元素用文字描述。
- 内部 tester 必须是 ASC 用户。build 90 天后过期。
