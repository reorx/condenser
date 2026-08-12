---
created: 2026-08-12
tags:
  - ios
  - signing
  - app-store
  - provisioning
  - release
---

# iOS 换正式证书 + App Store 发布就绪（图标 / 版本号 / 隐私清单 / 归档链路）

## 概要

诉求有两条：把 iOS 证书换成付费账号的新 Certificate，使装到手机上的版本有效期至少一年
（不再是免费账号的 7 天过期版）；同时把项目推到「可提交 App Store」的 Ready 状态。

查证下来第一条的**代码早在 2026-08-10 的 commit `aba239b` 就改完了，但从未真正生效**：
`scripts/device.sh` 的 Team ID 已固定为付费 Team `YU3FMV36N2`，钥匙串里
`Apple Development: Xiao Meng` 证书也在（有效期到 **2027-08-10**），可是通过 ASC API 实测
**该 Team 下一台设备都没注册过**（`asc devices list` 返回空）。没有设备就出不了
development provisioning profile，所以那次 `make device` 不可能成功过——手机上跑的仍是旧
免费 Team `QFW98B7VB4` 的 7 天版本，而那套证书其实 2026-04 就已过期。

远程补注册设备的两条路都试过、都不通，最终只能把这一步留给用户用数据线跑一次：

1. **ASC API 注册 UDID**：装了 `asc` CLI（brew），用 `~/Sync/apple-developer/` 里的 API key
   认证成功（能读 bundle-ids / devices），但 `asc devices register` 与
   `asc certificates create` 都返回 403 —— 这把 key 是当年为 macOS 公证建的 **Developer 角色**，
   注册设备与建证书需要 Admin。
2. **Wi-Fi 隧道构建**：`devicectl device info details --timeout` 能把休眠的手机唤醒并读到完整
   硬件信息，但 `xcodebuild` 的 destination 发现始终报「Unable to find a destination」——
   它要求的是完整信任隧道（USB 直连，或手机解锁且在同一局域网），后台 poke 保活 +
   `-destination-timeout 90` 都救不回来。

第二条（App Store Ready）在本机全部完成并验证：生成了 App Icon 资产目录、补齐版本号 /
出口合规 / 隐私清单、新增 `make archive` 归档导出链路。归档链路跑到签名步骤同样被
「团队无设备」挡住（archive 的 development 签名阶段也依赖它），所以设备注册是**唯一**
剩下的阻塞点，一旦解除，`make device` 与 `make archive` 会一起通。

## 修改的文件

| 文件 | 改动 |
|---|---|
| `ios/project.yml` | 加 `MARKETING_VERSION` (1.0.0) / `CURRENT_PROJECT_VERSION` (1) / `ASSETCATALOG_COMPILER_APPICON_NAME`；Info.plist 加 `CFBundleShortVersionString`/`CFBundleVersion` 插值与 `ITSAppUsesNonExemptEncryption=false` |
| `ios/Condenser/Info.plist` | xcodegen 从 project.yml 重新生成（不手工编辑） |
| `ios/Condenser/Assets.xcassets/` | 新增 AppIcon 资产目录：1024×1024 单尺寸、不透明、满幅 |
| `ios/Condenser/PrivacyInfo.xcprivacy` | 新增隐私清单：不追踪、不采集，唯一 required-reason API 是 UserDefaults（CA92.1） |
| `ios/Makefile` | 新增 `make archive`（Release 归档 + exportArchive），`TEAM_ID` 提为可覆盖变量 |
| `ios/scripts/ExportOptions.plist` | 新增：method `app-store-connect`、automatic 签名、teamID、uploadSymbols |
| `ios/AGENTS.md` | 「命令」加 `make archive`；「真机部署」补设备注册与 Wi-Fi 构建限制两条 ⚠️；新增「App Store 发布」章节 |
| `tmp/make_ios_appicon.py` | 新增图标生成脚本（复用 PWA 的漏斗+水滴设计，改为 RGB 不透明） |

## 注意事项

- **「证书换了」不等于「装得上」**：签名身份、设备注册、profile 是三件事。这次的教训是
  commit 改了 Team ID 就以为完事，实际链路从没跑通过。判断标准只有一个——
  `asc devices list` 有没有这台设备，以及产物里 `embedded.mobileprovision` 的有效期。
- **设备注册的唯一顺手途径是 USB 跑一次 `make device`**：脚本已带
  `-allowProvisioningDeviceRegistration`，会自动把设备注册进团队并生成 1 年期 profile。
  无头方案（ASC API）受限于 key 角色。
- **Wi-Fi 部署对「安装」够用，对「构建」不够**：`devicectl` 按需建隧道能装能查，
  但 xcodebuild 找不到 destination。别在手机锁屏时试图远程构建。
- **archive 的签名要显式给 `CODE_SIGN_IDENTITY="Apple Development"`**：project.yml 里为
  模拟器工作流写死了 `CODE_SIGN_IDENTITY: "-"`，Release 归档时若不覆盖，会报
  "has entitlements that require signing with a development certificate"；反过来写成
  `Apple Distribution` 又会与 automatic signing 冲突——automatic 模式下由 Xcode 在
  export 阶段决定分发证书，build 阶段只认 development。
- **iOS App Icon 与 PWA 图标的差异**：单尺寸 1024、**不能带 alpha**（App Store 直接拒）、
  满幅不做圆角（系统自己遮罩）。生成脚本因此不是复制粘贴，而是 RGB + `scale=0.55`。
- **`asc` 的 p8 私钥必须 `chmod 600`**，否则报 "private key file is too permissive"。
- 隐私清单的 required-reason API 是**扫代码得出的**（只有 `UserDefaults`/`@AppStorage`，
  无文件时间戳 / 磁盘容量 / 系统启动时间），后续新增这类调用要同步补声明。

## 遗留问题

按优先级排列，第 1 条是其余所有事情的前置：

- **[阻塞] 设备未注册进付费 Team** —— 用数据线连上 iPhone「Katherine」
  （UDID `00008120-00045D643672201E`），在 `ios/` 下跑一次 `make device`。这会自动注册设备、
  签发 1 年期 profile、安装并启动。**这一步不做，`make device` 和 `make archive` 都通不过。**
- **[一次性迁移] 装之前先删掉手机上的旧 app**：Team 从 `QFW98B7VB4` 换到 `YU3FMV36N2`，
  `application-identifier` 前缀变了，iOS 拒绝覆盖安装。删除会连带丢掉 Keychain 里的
  device token，装好后需重走一次 `/authorize` 配对，并在 Settings 里删掉旧的 device 行。
- **[未验证] `make archive` 只跑到签名阶段**：逻辑与 ExportOptions 已就位，但从未产出过
  ipa。设备注册完成后应实跑一次，确认 `.build/DerivedData/export/Condenser.ipa` 落地。
- **[未做] ASC 上的 app record 尚不存在**：创建 app（名称 / SKU / 主语言）无公开 API，
  需走网页或 `asc-app-create-ui` sub-skill。这是上传 build 的前置。
- **[未做] 商店素材与问卷**：App 隐私标签（按 PrivacyInfo 填 Data Not Collected）、
  6.9" 截图（可用 `asc-shots-pipeline` 自动化）、描述 / 关键词 / 年龄分级 / 定价。
- **[需决策] 审核用 demo 账号**：Condenser 是自托管单用户阅读器，审核员打开只会看到登录页。
  需准备一个可访问的 demo server + app password，或预生成一个 device token 交给审核。
  这一条可能是过审的最大变数，建议在提交前想清楚话术（App Review 备注里写明自托管性质）。
- **[可选] ASC API key 角色偏低**：现有 key 是 Developer，做不了设备注册 / 建证书 /
  部分发布操作。若希望后续 CI 或无头流程能全自动，需在 ASC 网页另建一把 Admin 角色的 key。

## 相关文档

本次 session 未新建 / 更新本项目内的 KB 文档（改动都落在 `ios/` 与 `ios/AGENTS.md`）。
参照的是**另一个项目**的笔记，路径记录如下（跨仓库，不用相对链接）：

- `~/Code/vocalflow-mac/kb/notes/2026-08-10-macos-developer-id-signing-guide.md`
  — 本次 session 的参照文档（VocalFlow，macOS Developer ID 方向）。iOS 走 App Store
  方向，证书类型与分发链路不同，可直接复用的是账号 / ASC API key / 凭据目录组织的部分
