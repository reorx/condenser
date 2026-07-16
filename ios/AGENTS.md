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
make gen         # 仅重新生成 xcodeproj
make clean       # 清理构建产物与生成的 xcodeproj
```

- 构建产物：`.build/DerivedData/Build/Products/Debug-iphonesimulator/Condenser.app`
- 默认模拟器设备由 Makefile 的 `SIM` 变量指定，覆盖：`make run SIM="iPhone 17 Pro"`
- 跑单个测试：`cd CondenserKit && swift test --filter <测试名>`
- 改了 `project.yml` 后必须 `make gen`（`make build` 已包含）
- 模拟器构建无需签名（ad-hoc）；真机部署时再在 project.yml 配 `DEVELOPMENT_TEAM`

## 排错顺序

构建怪异时先怀疑环境再怀疑代码：

1. `make clean && make build`（清 DerivedData + 重新生成工程）
2. 模拟器 runtime 缺失（`xcrun simctl list runtimes` 为空）：`xcodebuild -downloadPlatform iOS`
3. SPM 缓存问题：`rm -rf CondenserKit/.build`、删 `.build/DerivedData` 下 SourcePackages
4. 僵尸进程：`pgrep -l xcodebuild`、`pgrep -l Simulator`
5. 以上无效再看代码
