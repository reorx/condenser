# Condenser iOS

condenser 的原生 iOS 阅读客户端（SwiftUI）：Twitter 式简化阅读 timeline，只读不管。
完整设计见 `../kb/plans/2026-07-16-ios-reader-app.md`；后端 device-token 认证 spec 见
`../kb/plans/2026-07-16-mobile-client-api-device-token.md`。

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

route 取值：`tab/{timeline|channels|saved}` 切 tab；`channel/<id>` push 单频道
timeline；`settings` 切设置 tab；`detail/<cid>/<mid>` / `viewer/<cid>/<mid>` 弹详情
sheet / 全屏图片浏览器（消息须在 timeline 首页内，路由会等首屏加载完才应用）。
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
