# Condenser iOS

condenser 的原生 iOS 阅读客户端（SwiftUI）：Twitter 式简化阅读 timeline，只读不管。
完整设计见 `../kb/plans/2026-07-16-ios-reader-app.md`；后端 device-token 认证 spec 见
`../kb/plans/2026-07-16-mobile-client-api-device-token.md`。**多信源（Phase 4，2026-07-21）**：
条目是 `TimelineItem` envelope（source/key/datetime/is_read/is_saved + `telegram?`/`hn?`），
read/save 按 item key（`tg:{cid}:{mid}` / `hn:{sid}`）上报；订阅数据源是 `GET /api/sources`
（`SourceGroup`/`SourceSub`，`/api/subscriptions` 不再使用）；Timeline 左上角信源切换 Menu
（All + 已添加信源，驱动 `TimelineStore.source`）；tab 2「频道」→「订阅」（信源 → 订阅两级，
TG 行进频道 timeline，HN 行进 `HnFeedTimelineScreen`）；HN 卡片/详情（`HnCard`/`HnDetailSheet`，
self-post HTML 经 Kit 的 `hnPlainText` 转纯文本）；`SnapshotCache` 目录带契约版本号
（`condenser-snapshots-v2`，旧快照 decode 失败按 miss）。多信源计划见
`../kb/plans/2026-07-19-multi-source-hn.md`。

**X 信息源（Phase 5，2026-07-25）**：envelope 多了 `x`（`XTweet`）与源通用的
`feedback`（`ItemFeedback`，今天只有 X 暴露）。X 是第一个「一个信源多个 feed」的源，
所以 `TimelineStore` / `NewContentChecker` / timeline 端点都多了 `feed` 作用域
（`XFeed.foryou` 或关注人 handle）。**For You 不进聚合 timeline**（一天 ~1000 条会淹没
TG/HN），订阅 tab 的 X 分组行是它唯一入口 → `XFeedTimelineScreen`。卡片是 `XCard`
（+`XQuoteCard`/`XMediaView`/`XMediaThumb`/`XAvatarView`/`XGlyph`/`XVerdictBadge`/
`XFeedbackButtons`），详情是 `XDetailSheet`（判定证据用中文展开，卡片徽标沿用 web 的英文）。
推文媒体走 `/api/preview/image`、作者头像走 `/api/x/avatar/{handle}`，客户端从不直连 X。
`XVerdict` / `ItemFeedback` 都有 `other` 兜底值——后端先行升级出新值时降级渲染而不是炸解码。
计划见 `../kb/plans/2026-07-24-x-source-local-probe.md`。

**理由 chip（2026-07-26，schema v9）**：踩之后追问一次「为什么不喜欢？」——
`ItemFeedbackReason`（topic / promo / aiSlop / author，同样有 `other` 兜底），
envelope 上是与 `feedback` **平级**的 `feedback_reason`（老版本 App 把 `feedback` 当字符串
解，改成对象会整页解码失败，而 App 是单独升的）。两条规则：`TimelineStore` /
`RecordsStore` 的 `setFeedback`（拇指，不带理由）与 `setReason`（选 chip，verdict 保持
down）都走同一个 `write(_:verdict:reason:)`，一次请求写完整条标签，所以改正会丢掉过期理由、
撤销连理由一起删；理由**可跳过**，跳过零损失。UI 用原生 `confirmationDialog` 而不是内联
chip 行（手机上一行摆不下四个中文标签），只在「这一下确实标成了踩」时弹；已选理由只在
`XDetailSheet` 的「反馈」行回显，卡片上不画。

## 技术栈

- iOS 18+，SwiftUI App lifecycle，Swift 5 语言模式（非 Swift 6 strict concurrency）
- 本地 SPM 包 `CondenserKit`（纯逻辑 + 单测，Swift Testing）+ app target（UI 与系统胶水）
- 本机工具链：Xcode（含 iOS 平台）、xcodegen、xcbeautify（后两者 `brew install xcodegen xcbeautify`）

## 工程约定（重要）

- **一切构建/测试/运行走 Makefile，不用 Xcode GUI。**
- 工程定义的唯一事实来源是 `project.yml`（XcodeGen）。**永远不要手工编辑 `Condenser.xcodeproj`**
  （已 gitignore，`make gen` 随时重新生成）。
  - 加源文件：直接放进 `Condenser/` 目录（目录即 sources），然后 `make gen`
  - 改 target 配置 / Info.plist / URL scheme / 包依赖：改 `project.yml`，然后 `make gen`
  - `Condenser/Info.plist` 是 xcodegen 从 project.yml 生成的，不要直接编辑
- 分层规则：
  - `CondenserKit/` — 本地 SPM 包，纯逻辑（APIClient、Models、Store、状态机），
    **禁止依赖 UIKit**（平台含 macOS，`swift test` 在宿主机直接跑），所有单测在此
  - `Condenser/` — app target，UI 与系统胶水，按 `App/` `UI/` `Services/` 组织
- 开发方法：新功能 BDD —— 先在 `CondenserKit/Tests/CondenserKitTests/` 写行为测试
  （Swift Testing，`@Test` / `#expect`，网络用自定义 `URLProtocol` mock），再实现；
  bug 修复 TDD —— 先写复现测试再修
- Models 的字段事实来源是 `../frontend/src/lib/types.ts`，逐一对照翻译
  （snake_case → `CodingKeys`；日期 UTC，tz-aware 与 naive 两种形式都要能解析）

## 命令

```
make build       # xcodegen + xcodebuild Debug，模拟器 generic destination（xcbeautify 美化输出）
make test        # CondenserKit swift test（宿主 macOS 上跑）
make run         # boot 模拟器 + 安装 + 启动已构建的 app（不触发构建）
make dev         # build + run
make device      # 真机构建 + 推送安装（scripts/device.sh，见下）
make gen         # 仅重新生成 xcodeproj
make clean       # 清理构建产物与生成的 xcodeproj
```

- 构建产物：`.build/DerivedData/Build/Products/Debug-iphonesimulator/Condenser.app`
- 默认模拟器设备由 Makefile 的 `SIM` 变量指定，覆盖：`make run SIM="iPhone 17 Pro"`
- 跑单个测试：`cd CondenserKit && swift test --filter <测试名>`
- 改了 `project.yml` 后必须 `make gen`（`make build` 已包含）
- 模拟器构建无需签名（ad-hoc）；真机签名参数由 `scripts/device.sh` 在 xcodebuild
  命令行覆盖（`CODE_SIGN_STYLE=Automatic` + `DEVELOPMENT_TEAM`），不改 project.yml

## 真机部署

`make device`：xcodegen → 探测 Team ID（钥匙串 Apple Development 证书的 OU，可用
`TEAM_ID=` 覆盖）→ 选设备（唯一已连接的真机，多台时 `DEVICE="<名称或UDID>"` 指定）→
device 构建（`-allowProvisioningUpdates` 自动出 profile）→ `devicectl` 安装 + 启动。
产物在 `.build/DerivedData/Build/Products/Debug-iphoneos/`（与模拟器产物不冲突）。

前提（一次性）：Xcode → Settings → Accounts 登录 Apple ID；iPhone 数据线连 Mac 并信任；
手机开启开发者模式（设置 → 隐私与安全性）。免费 Personal Team 签名 7 天过期，重跑
`make device` 重装即可（Keychain 里的 token 不丢）；首次安装需在手机上信任开发者证书
（设置 → 通用 → VPN 与设备管理）。首次 USB 配对后 devicectl 支持同一局域网 Wi-Fi 部署。

## 开发调试：跳过授权直连本地后端

模拟器验证 timeline 等真实数据 UI 时，不必走交互式授权：

1. 起本地后端（dev DB 在 `tmp/condenser.db`，有真实消息数据）：
   `CONDENSER_DB_PATH=tmp/condenser.db uv run uvicorn condenser.app:create_app --factory --port 8792`
2. 往 devices 表插一个已知 token 的 sha256（`iOS Simulator (dev)` 行可能已存在，
   token 明文 `devtoken-ios-sim`）
3. 带 debug env 启动 app（AuthSession 的 `#if DEBUG` 注入口，仅内存态、不落 Keychain）：
   `SIMCTL_CHILD_CONDENSER_DEBUG_SERVER=http://localhost:8792 SIMCTL_CHILD_CONDENSER_DEBUG_TOKEN=devtoken-ios-sim xcrun simctl launch "iPhone 17" com.reorx.condenser`

Info.plist 已配 `NSAllowsLocalNetworking`（http://localhost 放行）。
截图：`xcrun simctl io booted screenshot <path>.png`。

### CLI 驱动的界面走查（debug 深链路由）

模拟器窗口不在当前 Space（AppleScript/cliclick 点不到）时，用启动环境变量直接导航到
目标界面再截图（`MainView.handleDebugURL`，仅 DEBUG 构建）：

```
SIMCTL_CHILD_CONDENSER_DEBUG_ROUTE=<route> xcrun simctl launch "iPhone 17" com.reorx.condenser
```

route 取值：`tab/{timeline|subs|channels|saved}` 切 tab（channels 是订阅 tab 的旧别名；
`tab/subs/<source>` 再带一段则进去就滚到该信源分组——订阅列表已经长到一屏放不下，
而模拟器窗口收不到合成手势：`System Events` 拿不到它的 window，`cliclick` 也就无从下手）；
`channel/<id>` push 单频道 timeline；`hn` push HN feed timeline；
`x[/<feed>]` push 某个 X feed（缺省第一条 X 订阅；For You 不在聚合流里，这是唯一入口）；
`settings` 切设置 tab；
`detail/<cid>/<mid>` / `viewer/<cid>/<mid>` 弹详情
sheet / 全屏图片浏览器（消息须在 timeline 首页内，路由会等首屏加载完才应用）；
`detail/x/<feed>[/<tweet id>]` 弹推文详情——X 条目单独走一次网络查，因为 For You
根本不在 `reader.timeline.items` 里；省略 id 时挑该 feed 第一条有判定的（判定证据
正是这个界面最值得看的部分）；
`forward/<cid>/<mid>[/<comment>]` 直接弹转发 dialog（消息不必在首页内；带第 4 段
则 1s 后自动提交——**真实转发落地目标频道**，`-` 表示空评论原生转发，中文评论需
percent-encode）。
每换一个界面 terminate + 重新 launch 一次即可。也支持
`xcrun simctl openurl booted "condenser://debug/<route>"`，但系统会弹
"Open in Condenser?" 确认框（且该框跨 app 重启存活，误触发后要
`simctl shutdown && boot` 才能清掉），无人值守走查一律用环境变量形式。

## 排错顺序

构建怪异时先怀疑环境再怀疑代码：

1. `make clean && make build`（清 DerivedData + 重新生成工程）
2. 模拟器 runtime 缺失（`xcrun simctl list runtimes` 为空）：`xcodebuild -downloadPlatform iOS`
3. SPM 缓存问题：`rm -rf CondenserKit/.build`、删 `.build/DerivedData` 下 SourcePackages
4. 僵尸进程：`pgrep -l xcodebuild`、`pgrep -l Simulator`
5. 以上无效再看代码
