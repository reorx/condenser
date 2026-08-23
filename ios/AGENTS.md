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
通道字母是开放字典（`[String: XVerdictChannel]`），所以后端 2026-07-29 加通道 A（作者先验）只需补一行中文名与它的证据渲染：A 的证据不是权重对而是一句话（`XVerdictChannel.record`，「@ibkr · 你踩过 6 次，赞过 0 次」），因为这个通道根本不读推文，只读账号。
计划见 `../kb/plans/2026-07-24-x-source-local-probe.md`。

**转发源通用化（2026-07-27）**：转发不再是 Telegram 专属。Kit 的
`forwardMessage(channelID:messageID:)` 换成 `forwardItem(key:comment:)`（打
`POST /api/forward`，服务端按 key 分派：TG 原生 forward / 引用发布，HN 渲染成
「粗体标题超链接原文 + 来源行超链接讨论」，X 只发一条把域名换成 fixupx.com 的链接——
x.com 不给 Telegram 供 embed，fixupx 给，作者/正文/图/引用推全在预览卡里）。三个 detail sheet 的
**收藏星标从 header 挪到底部动作行**，和新加的「转发」并排——两件事都是「对这条做点
什么」，摆在一起才好按；共用组件是 `ItemActionButtons`（收藏 + 转发）与
`ItemActionRow`（放不下就横向滚动，四个中文按钮在窄屏上会溢出）。
`ForwardDialog` 收 `itemKey` + `isTelegram`，后者只影响留空时的文案（「原样转发」
vs「只发标题和链接」）。旧的 `/api/messages/{cid}/{mid}/forward` 服务端保留为薄壳，
所以升级服务端不会打断手机上还没重装的旧版本。

**理由 chip（2026-07-26，schema v9）**：踩之后追问一次「为什么不喜欢？」——
`ItemFeedbackReason`（topic / promo / aiSlop / engagementFarming / author，同样有
`other` 兜底；`engagementFarming`「博眼球」是 2026-07-27 加的，只动常量不动 schema），
envelope 上是与 `feedback` **平级**的 `feedback_reason`（老版本 App 把 `feedback` 当字符串
解，改成对象会整页解码失败，而 App 是单独升的）。两条规则：`TimelineStore` /
`RecordsStore` 的 `setFeedback`（拇指，不带理由）与 `setReason`（选 chip，verdict 保持
down）都走同一个 `write(_:verdict:reason:)`，一次请求写完整条标签，所以改正会丢掉过期理由、
撤销连理由一起删；理由**可跳过**，跳过零损失。UI 用原生 `confirmationDialog` 而不是内联
chip 行（手机上一行摆不下这些中文标签），只在「这一下确实标成了踩」时弹；已选理由只在
`XDetailSheet` 的「反馈」行回显，卡片上不画。

**RSS 信息源（Phase 6，2026-08-21）**：envelope 多了 `rss`（`RssEntry`）。这个源没有
判定、没有反馈、没有媒体，卡片（`RssCard` + `RssGlyph`）与 sheet（`RssDetailSheet`）
是四个源里最简单的一对，订阅行 / 单 feed 视图（`RssFeedTimelineScreen`）照 HN/X 的
形状。四处值得记：

- **feed key 是整个 feed URL**（读者输入什么就用什么作键，`RssFeed.label` 在学到标题前
  回落成去掉 scheme 的 URL）。所以 debug 路由 `rss[/<下标>]` 用下标而不是 key——URL
  塞不进路径段；`detail/rss[/<id>]` 则要翻页找，归档按时间倒序而想看的往往是老条目。
- **摘要不替代正文**（2026-08-23 定型，`RssBody` 枚举随之退役）：摘要是机器的转述，
  必须标出来，但也不该顶掉原文开头——只看转述没法快速判断文章本身。卡片先画正文
  开头 3 行（空白折叠成单空格、纯省略号截断，不给 more），`AiSummaryBlock` 摘要块
  跟在下面：浅靛蓝底 + 左侧深一档同色竖条的引用块，「AI 摘要」标注在块内顶部
  （先撞上标注再读内容；靛蓝是因为琥珀/橙/天蓝都已有含义），卡片与详情 sheet 共用。
  Kit 面是两个属性：`displaySummary`（trim 后非空才算有）+ `contentText`；详情 sheet
  两样都给——摘要块在上、全文接在下面，因为点进来是要读文章的。
  sheet 还挂了 `.edgeSwipeToDismiss()`（`EdgeSwipeDismiss.swift`，可复用）：长文滚到
  底后下拉手势只会回滚内容，从左边缘右滑是给单手补的退路；手势用普通 `gesture` 不用
  `highPriorityGesture`，否则会抢走从边缘起手的纵向滚动。
- **列表只有摘录，全文按需取**（2026-08-23）：envelope 的 `content_excerpt` 是服务端
  剥好的约 500 字纯文本，`content` 只有 `GET /api/rss/entries/{id}` 与改版前存下的
  收藏快照才带（feed 正文平均 13.9KB、最长一条 7.1MB，一页 30 条全带就是一次几 MB
  的下载）。Kit 面因此是两个属性：`contentText` 走摘录（卡片用；旧快照里没有摘录时
  才回落去解析 `content`），`articleText` 才解析全文。`RssDetailSheet` 打开时
  `reader.api.rssEntry(id:)` 取一次，到手前先显示摘录 + 「正在加载全文…」，失败就停在
  摘录上——**解析结果算一次存 state**，那是一整篇的正则，放在 body 里每次重渲染都会
  重跑（正是这次排查 RSS 卡顿找到的另一半）。后端计划
  `../kb/plans/2026-08-23-rss-list-excerpt-detail-endpoint.md`。
- **`rssPlainText` 不是 `hnPlainText` 的推广**，三条规则刻意相反：链接保留锚文本
  （HN 换成 href 是因为它截断显示文本）、`<script>`/`<style>` 连内容一起丢、源码换行
  按空白处理（只有块级标签断行，否则句子会在中间硬折），`<pre>` 是唯一例外——整块
  摘出去、处理完再放回来，代码的缩进才留得住。
- 信源方块的底色是琥珀而不是系统 `.orange`：`HnGlyph` 已经是纯橙，两个方块在同一条
  时间线上前后相邻，颜色一样就等于没有信源标记（走查才发现的，单看 RSS 卡片没问题）。

计划见 `../kb/plans/2026-08-20-rss-source-opml-llm-summary.md`。

**外链统一出口（2026-07-29）**：所有外链都过 `ExternalLink.swift` 的
`openExternalURL(_:fallback:)`——X 的推文 / 主页链接先试 `twitter://` 深链进 X app
（scheme 是改名前注册的，X 一直认；打不开再试一次 x.com 的 universal link），
两条都不成才回落 in-app Safari，其余链接直接 Safari。「在 X 上打开」要的是能点赞、
能回复、已经登录好的原生界面，SFSafariViewController 里的 x.com 只是个逼你登录的壳。
网页链接 → 深链的映射在 Kit 的 `xAppURL(for:)`（纯逻辑，有测试）：只认单条推文与
作者主页两种确定形态，认不出就返回 nil 走网页——把人送进 app 的错误界面比留在 Safari 更糟。
列表/详情用 `.externalLinks(safari:)` 接管子树链接；sheet 自己的按钮直接调
`openExternalURL`，因为 `@Environment(\.openURL)` 在 sheet 的 body 里读到的是**外层列表**
那份，Safari 会从这张 sheet 背后弹出来。深链有没有真的落进 X app 只能在装了 X 的真机上
验（`make device`），模拟器没有 X app，走的永远是回落分支。

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
make archive     # App Store 归档 + 导出 ipa（Release，见「App Store 发布」）
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

`make device`：xcodegen → Team ID 从 `~/Sync/apple-developer/secrets.env` 的
`APPLE_TEAM_ID` 读（Apple 凭据的唯一权威来源，变量与用法见该目录 AGENTS.md；
2026-08-13 起不再在项目里硬编码，可用 `TEAM_ID=` 覆盖。不再从钥匙串探测——钥匙串里
还留着旧免费 Personal Team 的证书，find-certificate 取首个匹配会探错）
→ 选设备（唯一已连接的
真机，多台时 `DEVICE="<名称或UDID>"` 指定）→ device 构建（`-allowProvisioningUpdates`
自动出 profile）→ `devicectl` 安装 + 启动。
产物在 `.build/DerivedData/Build/Products/Debug-iphoneos/`（与模拟器产物不冲突）。

前提（一次性）：Xcode → Settings → Accounts 登录付费 Apple ID；iPhone 数据线连 Mac 并
信任；手机开启开发者模式（设置 → 隐私与安全性）。付费 Team 的 profile 一年有效，
**没有免费账号的 7 天重装问题**；首次安装需在手机上信任开发者证书（设置 → 通用 →
VPN 与设备管理）。首次 USB 配对后 devicectl 支持同一局域网 Wi-Fi 部署。
⚠️ **设备必须先注册进付费 Team**（Certificates, Identifiers & Profiles → Devices），
否则 development profile 生成不了，报「Your team has no devices」——连 `make archive`
的 development 签名也会被它挡住。注册的唯一顺手途径是 **USB 连上手机跑一次
`make device`**（`-allowProvisioningDeviceRegistration` 自动注册）；ASC API key
是 Developer 角色，`asc devices register` 会 403（需 Admin）。⚠️ Wi-Fi 部署对
**构建**不够用：`devicectl` 的按需隧道能查信息，但 xcodebuild 的 destination 发现
要求完整信任隧道（USB 或手机解锁且在同一局域网），否则报「Unable to find a
destination」——实测手机锁屏时 poke 保活 + `-destination-timeout` 都救不回来。
⚠️ **从旧免费 Team 切换过来的手机要先删掉旧 app 再装**：Team 变了 →
`application-identifier` 前缀变了，iOS 拒绝覆盖安装（devicectl 报 mismatch 错）。
删除会连带丢掉 Keychain 里的 device token，装好后要重走一次 `/authorize` 配对
（Settings 里旧的 device 行可顺手删掉）。此为一次性迁移成本，之后签名身份稳定。

## App Store 发布（2026-08-12 起 Ready）

`make archive`：Release 归档（automatic 签名 + `-allowProvisioningUpdates`，Apple
Distribution 证书与 App Store profile 由 Xcode 云签名按需补发；`DEVELOPMENT_TEAM`
从 secrets.env 的 `APPLE_TEAM_ID` 读）→ `exportArchive`（导出配置由
`scripts/ExportOptions.template.plist` 渲染 teamID 生成
`.build/DerivedData/ExportOptions.plist`，method `app-store-connect`）→ ipa 落在
`.build/DerivedData/export/Condenser.ipa`。前提同真机部署：团队里至少注册过一台设备
（archive 的 development 签名也依赖），Xcode 已登录付费账号。

发布素材已就位：

- **App Icon**：`Condenser/Assets.xcassets/AppIcon.appiconset`（1024 单尺寸、不透明、
  满幅）——由 `../tmp/make_ios_appicon.py` 生成，与 PWA 图标同款设计（漏斗+水滴）；
  改设计先改 `tmp/make_pwa_icons.py` 再同步这份脚本
- **版本号**：`project.yml` 的 `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION`
  （升版本改这里 + `make gen`；Info.plist 由它们插值）
- **出口合规**：`ITSAppUsesNonExemptEncryption=false`（只用 HTTPS 标准加密），
  上传后 ASC 不再逐 build 问询
- **隐私清单**：`Condenser/PrivacyInfo.xcprivacy` —— 不追踪、不采集；唯一
  required-reason API 是 UserDefaults（CA92.1）。新增用到文件时间戳 / 磁盘容量 /
  系统启动时间等 API 的代码时要同步补声明
- **上传**：asc CLI 已装（brew），认证已 `asc auth login` 持久化到系统钥匙串
  （profile `reorx-dev`，默认，裸跑即可用；`asc auth status` 查看）。兜底是
  `~/Sync/apple-developer/secrets.env` 的 `ASC_*` 三件套（asc 原生识别的变量名，
  `set -a; source …; set +a` 即可，文件用 envops 读）。上传 build：
  `asc builds upload --path <ipa>`（asc-release-flow sub-skill 有完整编排）。
  2026-08-13 起默认 profile 是 **Admin 角色** key（`reorx-admin`），旧 Developer key
  的 403 限制不再存在（详见凭据目录 AGENTS.md 的「已知限制」）

**App record 已创建（2026-08-13）**：名称 Condenser、bundle `com.reorx.condenser`、
SKU `condenser-ios`、主语言 en-US——经 `asc web apps create`（网页会话 API）无头创建，
无需浏览器自动化。app id / bundle ID 资源 id / 注册设备 / API key 等标识不入公开库，
见私密 KB `kb.private/condenser/kb/docs/ios-app-store-release.md`。

**首版素材已全部上架（2026-08-15）**：文案（副标题 / 描述 / 关键词 / 支持与营销 URL）、分类
（NEWS + PRODUCTIVITY）、年龄分级（全 none → 4+）、版权、定价（免费）、全 175 地区可用、
内容版权声明、隐私标签（Data Not Collected，已 publish）、3 张 `IPHONE_65` 截图——
全部经 asc CLI 无头完成。命令与 ASC 侧资源 id 见上面那份私密 KB 文档；两个反复踩的坑记在
那里：隐私标签 `publish` 前必须先 `apply`（pull 显示的是规范视图，远端其实空的，直接
publish 报 409），以及 `asc review details-create` 强制要 `--contact-phone`。
⚠️ 隐私政策是新建的 `PRIVACY.md`，商店里的 URL 指向 GitHub master——**提审前必须确认它
已经 push**，否则链接 404。

**demo server 已就位（2026-08-15）**，`asc validate` 的最后一个阻塞项（审核 demo 账号的
name/password）由此消除：`https://condenser-demo.reorx.com`，只开 HN 源、无 Telegram 会话、
不接自动部署。运维记录在 deploy workspace 的 `kb/docs/condenser.md`「Demo 实例」，**提审前
必读**的是私密 KB `kb.private/condenser/kb/docs/demo-server.md`——初始化即健康检查的
`scripts/demo_bootstrap.py`（脚本在本库）、审核表单三个字段怎么填、备注英文话术、每次提审前的
checklist；密码实值与已填的表单值在同目录的 `ios-app-store-release.md`。

连带一处 app 改动：`LoginView` 的服务器地址字段以前预填生产域名
`https://condenser.reorx.com`，现在改成空（`CURRENT_PROJECT_VERSION` 1 → 2）。原因是
审核员拿到的是全新安装，直接点登录会去**作者的生产服务器**认证，demo 密码在那里必被拒——
报错读起来像「demo 凭据不管用」而不是「服务器填错了」，正是 2.1 被拒的典型形状。所以
**build 1.0.0 (1) 作废**，提审用的是带这处改动的 **build 1.0.0 (2)**。

**提审前的一切都已就绪，只差最后一条命令（2026-08-16）**：build 1.0.0 (2) 已 archive →
upload → processing VALID → 挂到 1.0.0 版本；审核详情（demo 账号 = demo 域名 + 密码 +
三步英文备注）已填；`asc validate` **0 error / 0 warning**（唯一 info 是「隐私标签发布状态
公开 API 查不到」，用 `asc web privacy pull` 实测 `published: true`）；`asc review submit
--dry-run` 报 `wouldSubmit: true`。**故意停在 `asc review submit --confirm` 之前**——提审
是对外不可逆动作，留给人按。ASC 侧资源 id 与提审命令原文见私密 KB。
⚠️ 提审当时的四项前置（demo 在线 / 密码一致 / `PRIVACY.md` 已 push / build 号对）逐条
怎么查，见私密 KB `kb.private/condenser/kb/docs/demo-server.md` 的 checklist——**每次提审
都要重跑一遍**，不是一次性的。

### TestFlight（2026-08-16 起可用）

**内部测试不需要任何审核**，build processing 一 VALID 就能装——所以它和提审是两条独立的线，
提审前先发一轮 TestFlight 不会耽误任何事。外部测试（最多 10000 人 / 公开链接）才需要
Beta App Review，那是另一套、比正式审核轻。

对本项目它有个**别处替代不了**的用处：提审的 ipa 是 App Store 签名的，profile 里没有设备清单，
`make device` 装不上——TestFlight 是唯一能在真机上跑「即将提交的那个二进制」的途径。

已建好一个 internal 组，账号持有人已是组内 tester（组 id / tester id 在私密 KB）。之后每个
build 只需一条命令，`--build` 指已上传的 build id 就不会重复上传：

```bash
asc publish testflight --app <app id> --build <build id> --group <group id> \
  --locale en-US --notify --test-notes "这轮要验什么"
```

验收看两处：`asc testflight distribution view --build-id <id>` 的 **Internal State 应为
`IN_BETA_TESTING`**，以及 `asc builds test-notes list --build-id <id>` 能读回笔记
（`asc publish testflight` 的输出表里 `Notified` 显示 false 是正常的——组上
`Auto Notify: true` 时由 Apple 自动发信，不走这个字段）。内部 tester 必须是 ASC 用户
（`asc users list`），拿外部邮箱加进 internal 组是不行的。TestFlight build **90 天后过期**。

### 商店截图的造法（下个版本照搬）

不碰生产数据、不需要任何账号，因为**只开 HN 源**就能填满界面（公开数据，一分钟内
200+ 条，含 hckrnews 历史回填）：

1. 临时后端指向全新 DB：`CONDENSER_DB_PATH=tmp/<date>-appstore-shots/condenser.db uv run
   uvicorn condenser.app:create_app --factory --port 8793`；
2. 往 `devices` 表插调试 token 的 sha256（脚本见 `tmp/<date>-appstore-shots/`），再
   `POST /api/sources/hn/subscriptions {"channel_id":"front"}`（订阅即 kick 一轮采样）；
3. 6.9" 模拟器（iPhone 17 Pro Max）装 Debug 构建 → `simctl status_bar override --time 9:41
   --batteryState charged --batteryLevel 100` → 用 `SIMCTL_CHILD_CONDENSER_DEBUG_ROUTE`
   逐屏截图（路由表见下面「CLI 驱动的界面走查」），`simctl ui <udid> appearance dark`
   出深色版；
4. `asc screenshots sizes` 说 iPhone 只有 **`APP_IPHONE_65`**（1284×2778）必填；6.9"
   出图是 1320×2868，`sips -z 2789 1284` 等比放大后 `sips -c 2778 1284` 居中裁。
   上传用 `--version-localization <版本本地化资源 id>`（**不是** `en-US`）。

⚠️ **设置页要单独拍**，别用上面这条临时后端的流水线——它第一行就是服务器地址，截出来印着
`http://localhost:8793`。做法（2026-08-16 补的第 4 张）：让模拟器直连 **demo server**，
截出来的地址就是审核员会看到的那个域名。token 不必碰数据库，用公开 API 现铸现销：
`POST /api/auth/login`（密码走 envops，别落盘）拿 cookie → `POST /api/auth/device` 拿 token
→ `SIMCTL_CHILD_CONDENSER_DEBUG_SERVER=<demo> SIMCTL_CHILD_CONDENSER_DEBUG_TOKEN=<token>
SIMCTL_CHILD_CONDENSER_DEBUG_ROUTE=settings` 启动 → 截图 → `DELETE /api/auth/devices/{id}`。
⚠️ `status_bar override` 要把信号一起盖掉（`--cellularMode active --cellularBars 4
--dataNetwork wifi --wifiMode active --wifiBars 3`），只给 `--time`/电量的话信号是「....」，
和另外三张对不上。定稿四张：浅色时间线 / 深色时间线 / 收藏页 / 设置页。

设置页截图里有两处**已知但没修**的东西，重拍前先看一眼是不是已经解决：tab 栏
`Timeline` 是英文而另外三个是中文；半透明 tab 栏下面会透出「设备」区的红色删除按钮残影
（iOS 原生半透明栏的正常表现，不是渲染 bug，但静态图里看着像）。

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
`rss[/<第几个订阅>]` push 某个 RSS feed——**用下标不是 key**，这个源的 feed key 是
整个 URL，塞不进路径段；
`settings` 切设置 tab；
`detail/<cid>/<mid>` / `viewer/<cid>/<mid>` 弹详情
sheet / 全屏图片浏览器（消息须在 timeline 首页内，路由会等首屏加载完才应用）；
`detail/x/<feed>[/<tweet id>]` 弹推文详情——X 条目单独走一次网络查，因为 For You
根本不在 `reader.timeline.items` 里；省略 id 时挑该 feed 第一条有判定的（判定证据
正是这个界面最值得看的部分）；
`detail/rss[/<条目 id>]` 弹条目详情——同样单独查，而且要**翻页**（最多 8 页）：
归档按时间倒序，值得看的怪例（中文长文、缺字段的）都排在两百多位；
省略 id 时挑第一条有正文的；
`forward/<item key>[/<comment>]` 直接弹转发 dialog（条目不必在首页内，只用 key，
例如 `forward/tg:-1001:123` / `forward/hn:44123` / `forward/x:2080…`；带第 3 段
则 1s 后自动提交——**真实转发落地目标频道**，`-` 表示不带评论，中文评论需
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
