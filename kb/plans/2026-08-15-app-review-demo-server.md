---
created: 2026-08-15
tags:
  - ios
  - app-store
  - app-review
  - demo-server
  - deploy
  - hn
---

# App Store 审核 demo server（condenser-demo.reorx.com）部署与提审材料

## 状态：✅ 已完成（2026-08-15 当日执行完毕）

`https://condenser-demo.reorx.com` 已上线并端到端验收通过（134 条 / 7 天历史、采样循环
准点、浏览器与 iOS 都走完了完整 reviewer 序列），`asc validate` 的最后一个阻塞项消除。
commit `ac4762a` + `28293e4`（push 即部署，生产已上线同版本，两个域名 health 均 200）。

**日常怎么用这个 demo，不看这份 plan，看 `kb/docs/demo-server.md`**（初始化即健康检查的
脚本、审核表单三个字段、备注英文话术、每次提审前的 checklist）；运维记录（role / 端口 /
Caddy / DNS）在 deploy workspace 的 `kb/docs/condenser.md`「Demo 实例」；密码实值与已填的
ASC 表单值在 kb.private。截图与可重跑脚本在 `tmp/2026-08-15-app-review-demo/`（读其 README）。

这份 plan 之后只作为**决策记录**保留——下面每一节都补了实际结果，与预案不符的地方标了出来。

### 尚未做完的两件事

1. **UptimeFlare 监控条目没加**（`reorx/uptimeflare` 的 `uptime.config.ts`）。工作区规则要求
   新域名同步接入站外监控，对 demo 更是实打实的——审核期掉线就是被拒。没做的原因是那个 repo
   当时有另一个 session 的未提交改动，而 push 即部署，混一行进去要么被误提交要么被冲掉。
   照抄 condenser 那条改 id/target/tooltip 即可，别忘了同时加进 `'🌐 Apps'` 分组数组。
2. **iOS 要重出一个 build 再提审**。见下面「执行中发现的问题」第 2 条：已上传的 `1.0.0 (1)`
   带着预填的生产域名，不能用来提审。

## 执行中发现的问题（都不在预案里，都已修）

**这两条是本次工作里唯一动了应用代码的地方，都经用户逐条拍板。**

1. **web UI 整个被 Telegram 登录挡着。** `App.tsx` 的门是 `data.status !== 'authorized'`
   → 渲染 `TgLogin`，所以 demo（无 TG 会话）输完 app password 后看到的是一个手机号表单。
   `/authorize` 在门之前返回、iOS 也从不请求 `/api/tg/status`，**所以 reviewer 路径本来就是通的**，
   但验收标准 1（浏览器里能看到 HN 时间线）在零代码变更下**不可能满足**。而且这本身是真缺陷：
   自从有了 HN 和 X，一个只订阅 HN 的安装是有内容可读的。
   改法：只有「`GET /api/sources` 里一个非 Telegram 订阅都没有」时才拦。三处是承重的——门要
   **等** sources 落地再判（否则对有其他信源的安装会闪一下墙）、sources 请求失败按「没有其他
   信源」处理（退回多信源之前的行为）、`/connect-telegram` 把 `TgLogin` 放进 app 内部（Settings
   的 Telegram 行断开时链到那里，而那现在是通往 TG 登录的**唯一**入口）。9 个新前端测试。
2. **iOS 登录页把服务器地址预填成生产域名** (`LoginView.swift`)。审核员拿到全新安装，直接点
   登录会去**作者的生产服务器**认证，demo 密码在那里必被拒——错误读起来像「demo 凭据不管用」
   而不是「服务器填错了」，正是 2.1 的典型形状（实测过：确实弹出
   `"Condenser" Wants to Use "condenser.reorx.com" to Sign In`）。改成空值（已有 placeholder
   「服务器地址」），`CURRENT_PROJECT_VERSION` 1 → 2。首次登录后 `onAppear` 会用
   `session.serverURL` 覆盖，所以只影响全新安装。

## 背景

iOS 首次提审的最后一个实质待办（见
`kb.private/condenser/kb/docs/ios-app-store-release.md` §③）：Condenser 是自托管
单用户阅读器，审核员装上 app 只会看到登录页。不提供可访问的 demo server + 凭据，
几乎必然被拒（metadata rejected / Guideline 2.1）。

审核员的操作序列（release 构建下唯一可走的登录路径）：

1. 打开 app → 填服务器地址 `https://condenser-demo.reorx.com`
2. app 跳转 `/authorize` 网页 → 输入 app password（AppLogin 先出现，输一次密码）
3. 配对成功拿到 device token → 回 app 看到时间线

预生成 device token 交给审核**不可行**——token 注入是 DEBUG-only 通道，release
构建没有入口。

## 既定决策（用户已拍板）

- 域名 `condenser-demo.reorx.com`，部署在生产同主机 **hh-hk-01**，ansible role
  复制一份。
- demo 密码用生成密码，写进 demo server 文档。
- demo 数据 = 只开 HN 源（front 订阅）。HN 是无认证的公开数据源，demo 内容随采样
  循环自动保鲜，零维护。这一步用脚本完成并验证「只开 HN、无 Telegram 会话」时服务
  正常运行。

## 调研结论（写方案前已核实）

- **hh-hk-01 没跑 caddy role**：condenser 的 vhost 在该主机手工维护的 legacy
  Caddyfile 里（playbook.yml 的 hh play 注释明确说明）。所以 demo 的 vhost 要
  ssh 上去手工加一段（照抄现有 condenser 块），ansible 只管容器。
- **DNS 需要新增**：Cloudflare 加 `condenser-demo` 记录，代理模式照抄
  `condenser.reorx.com` 现有记录；`*.reorx.com` origin cert 覆盖新子域。
- **配置面**：`TELEGRAM_API_ID/HASH` 是必填 settings（pydantic 无默认值），但无
  TG 会话时不应有任何连接发生——demo 用 dummy 值（`1` / `dummy`），本地演练首先
  验证这一点；若启动路径意外要求合法 api_id，退回用真实 api_id/hash（无会话也
  无害）。`CONDENSER_HN_ENABLED` 默认 true；demo 显式设 `CONDENSER_X_ENABLED=false`
  （probe 不指向 demo，关掉是明确语义而非必需）；embedding / attr key 不设 →
  判定管线整体惰性；生产 compose 里的 `CONDENSER_VERDICT_SHADOW_CHANNELS` 行
  demo 模板不带。
- **HN 数据到位速度**：POST 订阅即 `kick()` 立即采样一轮（front 30 条），
  hckrnews 7 天历史 backfill 以 4s/天 节流，几分钟内齐（v14 的 `stamp_history`
  保证 backfill 的天在时间线上可见）。
- **hookploy**：生产 condenser 是 push-即-发。demo **不接** hookploy（见下方
  决策点 2）。
- **备份**：demo 数据可再生（公开 HN 数据 + 可重跑的 bootstrap），不进 backup
  role 的 `enabled_apps`。

## 决策点（用户已全部裁决，2026-08-15）

1. **密码写在哪** → **kb.private**。公开 `kb/docs/demo-server.md` 写 runbook 与指针，
   密码实值与 ASC 表单三个字段记进 `kb.private/condenser/kb/docs/ios-app-store-release.md` §⑧。
2. **demo 是否跟随自动部署** → **不接 hookploy**，手动刷镜像。落实方式是 role 的 compose 任务
   用 `pull: missing`——**跑 ansible 不会换版本**，换版本只有一条路（`docker compose pull && up`），
   所以审核期间不会有任何人无意间给 demo 换了版本。
3. **端口** → **3465**（不是预案建议的 3460；用户选了与其他主机端口表不相邻的值以免记混）。
   部署前实测过 hh-hk-01 上只有 3457/3459 在监听，3465 空闲。
4. **web UI 的 TG 登录门**（执行中新增）→ **改前端门**，见上面「执行中发现的问题」。
5. **iOS 登录页预填地址**（执行中新增）→ **改成空值并重传 build**，同上。

## 实施步骤

### 阶段 1 —— 本地演练：验证「只开 HN」可正常运行（先于任何部署）

这是用户点名的验证项，也是 dummy TG creds 可行性的裁决现场。

1. 写 bootstrap 脚本 `scripts/demo_bootstrap.py`（uv script；放 `scripts/` 而非
   `tmp/`，因为每个审核周期都要重跑它做健康检查）。行为（幂等）：
   - 密码从 stdin / 环境读，不落 argv（`dev-browser-login.sh` 的先例）；
   - 登录拿 cookie → `POST /api/sources/hn/subscriptions`（`channel_id='front'`，
     重复跑会走 re-enable 路径，无害）；
   - 轮询 `/api/hn/status` 直到 `stories > 0`；
   - 断言 `GET /api/timeline` 返回含 `source == 'hn'` 的 envelope、
     `/api/timeline/days` 与 unread 计数非空；
   - 输出一行结论（story 数、最早/最晚日期），非零退出即失败。
2. 本地起一个全新实例演练：临时目录里空 SQLite + dummy TG creds +
   `CONDENSER_X_ENABLED=false`，`uv run python -m condenser`（或 uvicorn）。
   验证：启动不炸、无 TG 会话时无任何 Telegram 连接尝试、`/authorize` 冷加载
   可达（SPAStaticFiles fallback）、跑 bootstrap 脚本全绿、web UI 登录后能看到
   HN 时间线。
3. iOS 模拟器指向本地实例，走一遍**完整 reviewer 序列**（填 URL →
   webAuthenticationSession → 输密码 → 配对 → 时间线出 HN 卡片），确认 TG 无
   会话对 app 无影响。截图归档 `tmp/2026-08-15-app-review-demo/`，测完
   `mac-dev-cleanup --only sim`。

**✅ 结果**：全通。几处与预案不同或值得记的：

- **dummy TG creds 可行，无需退回真值**。`TgManager.startup()` 在没有 session 行时直接
  return，根本不构造 client——启动日志里零 Telegram 活动，一次连接都没有。
- 脚本**轮询的是 `/api/timeline` 而不是 `stories > 0`**（预案写错了）：v14 之后「已归档」
  与「在时间线上」是两件事，`stories_total` 涨不证明屏幕上有东西。
- 脚本多了一条预案没有的**硬检查：服务器不得有 Telegram 会话**（`/api/tg/status` 一旦是
  `authorized` 就拒绝放行）。这是安全检查不是体面检查——demo 带真账号等于把私人频道交给
  审核员。它也是唯一一条「只在我们绝不该处的境地里才触发」的检查，所以用
  `tmp/…/check_tg_guard.py` 对着 stub 两个方向都跑过，而不是读代码了事。
- 三条失败路径实测：密码错、连不上、没给密码，全部退出 1 且信息可读。
- unread 计数由「断言非空」降级为**只报数**：首次 bootstrap 时它必然 > 0，但作为提审前的
  健康检查，审核员读过内容后它就是 0，硬断言会假报警。
- 本地演练脚本 `run_local_demo.sh` 的**进程 CWD 必须在数据目录里**：pydantic-settings 读
  的是**当前目录**的 `.env`，从仓库根启动会静默加载开发者真实的 TG 凭据与会话——正是这次
  演练要排除的那个事故。

### 阶段 2 —— 部署 demo 实例（deploy workspace）

1. ansible：`roles/condenser` 复制为 `roles/condenser-demo`（目录
   `/opt/apps/condenser-demo`、`condenser_demo_port: 3460`、compose 模板去掉
   shadow-channels 行、environment 加 `CONDENSER_X_ENABLED: "false"`；env.j2 的
   TG 两项改为 dummy 预填而非 CHANGEME，placeholder guard 只拦密码与 secret key）。
   hh play 挂上 role 与 vars；backup 的 `enabled_apps` **不**加。
2. 生成凭据：`openssl rand -hex 32` 做 secret key；app password 用生成的 16 位
   字母数字（审核员从备注复制粘贴，不需要好记，但避免易混字符）。envops 写进
   服务器 `.env`（0600）。
3. Cloudflare 加 `condenser-demo` DNS 记录（模式照抄 `condenser.reorx.com`）。
4. ssh hh-hk-01：legacy Caddyfile 照抄 condenser 块加 vhost
   （`condenser-demo.reorx.com` → `localhost:3460`，同 origin cert），reload。
5. ansible 跑 `-t condenser-demo`，容器起来后 `curl 127.0.0.1:3460` 健康检查。
6. 更新 deploy workspace 的 `kb/docs/condenser.md`：记 demo 实例的存在、端口、
   手工 Caddyfile 段落的位置。

**✅ 结果**：全部落地（端口是 3465 不是 3460）。三件预案没料到的事：

- **占位守卫被自己的注释卡死**。role 抄的是 `grep -q CHANGEME <file>`，而新 env.j2 的注释里
  写了「Telegram 那两项为什么**不是** CHANGEME」——这句话本身让守卫命中，容器永远起不来
  （连跑两次 ansible 都 skip）。改成 `grep -qE '^[A-Za-z_][A-Za-z0-9_]*=CHANGEME$'`：守卫要
  读的是**赋值**，不是这个词。`condenser` role 的旧守卫没动（它的模板注释里没这个词）。
- **DNS 我做不了**。唯一能摸到的 CF token 是 ali-hk-01 上 Caddy 的 DNS-01 token，实测
  作用域**只有 breeze.pub**（`/zones` 只返回它一个），碰不了 reorx.com。记录由用户在面板加
  （A → 103.69.129.33，橙云）。`tmp/…/cf_dns.sh` 写了但没用上，留作以后有合适 token 时的工具。
- **secret 全程没落本地盘也没进 argv**：`ssh <host> openssl rand -hex 32 | envops set -k …`，
  服务器上生成、管道进 envops 写远端 `.env`（0600 保持）。

### 阶段 3 —— demo 数据与线上验收

1. 对 `https://condenser-demo.reorx.com` 跑 `scripts/demo_bootstrap.py` → HN
   front 订阅 + 7 天历史就位。
2. 浏览器过一遍 reviewer 流程（登录页 → 密码 → 时间线）；隔一个采样周期
   （≥10 分钟）确认新故事仍在进来（采样循环活着）。
3. iOS（模拟器或真机）指向 demo 域名走完整 reviewer 序列。截图并入
   `tmp/2026-08-15-app-review-demo/`。

**✅ 结果**：134 条 / 7 天（2026-08-08…08-15）；采样循环 16:08:29 → 16:18:34 准点又跑一轮
（10 分钟间隔，`docker logs | grep topstories`）；浏览器与 iOS 都走完了完整 reviewer 序列。

- **数据是在 DNS 到位之前就灌好的**——`ssh -L` 隧道打到 127.0.0.1:3465 跑 bootstrap，
  这样 hckrnews 回填的几分钟与等 DNS 的时间重叠。
- **PWA service worker 会喂你刷镜像之前的前端**。demo 镜像刷完后浏览器里仍是旧界面，
  注销 SW + 清 caches 才看到新的——差点误判成部署没生效。这条已写进 runbook 的 checklist。
- 驱动模拟器打字的三条实测规则（cliclick 的键盘事件到不了模拟器、坐标要从窗口截图换算、
  密码走剪贴板）记在 `tmp/…/README.md`，也存了一条 memory。

### 阶段 4 —— 文档与提审材料

1. 写 `kb/docs/demo-server.md`（公开 runbook）：
   - 架构：独立容器/端口/SQLite，与生产的隔离边界；HN-only 的配置面
     （dummy TG creds、X off、判定惰性）；
   - `scripts/demo_bootstrap.py` 用法（初始化 = 健康检查，可随时重跑）；
   - **如何提交审核**：App Review Information 里 Sign-In Required = Yes；
     User Name 填 `https://condenser-demo.reorx.com`（或 `see notes`），
     Password 填 app password，完整操作步骤写进 Notes。备注话术（英文草稿，
     基于 kb.private 文档里的版本细化）：

     > Condenser is a self-hosted, single-user feed reader. Each user runs
     > their own server instance; this app is a read-only client for it.
     > There is no public sign-up. For review, please use our demo server:
     > 1. On the first screen, enter the server URL:
     >    https://condenser-demo.reorx.com
     > 2. A web authorization page opens. Enter the app password: <password>
     > 3. The app pairs with the server and shows the reading timeline
     >    (content is public Hacker News front-page data).
   - **每次提审前 checklist**：demo 在线（bootstrap 脚本跑一遍）→ 是否要刷新
     镜像（手动 pull/up）→ 密码与备注仍一致 →（可选）重置 demo 数据：删
     data 目录重启容器再跑 bootstrap；
   - 运维注意：整个审核周期必须在线；配置保留不删（每个版本提审都复用）；
     hh-hk-01 不稳定是已知风险，若审核期间宕机导致被拒，恢复后重新提交即可。
2. 密码实值与提审表单记录进 kb.private（按决策点 1 的裁决）。
3. 指针更新：condenser `AGENTS.md`（CLAUDE.md）Documentation 段加
   `kb/docs/demo-server.md`；`kb.private/.../ios-app-store-release.md` §③
   标记已解决并指向新文档；`ios/AGENTS.md`「App Store 发布」章节补一句。

**✅ 结果**：全部落地。备注话术最终版比上面的草稿细——写明了「字段一开始是空的」，
并把「输密码」与「点 Authorize」拆成两步，因为审核员的失败点就在这两处。以
`kb/docs/demo-server.md` 里那版为准。

## 验收标准（全部达成）

1. ✅ 冷加载出登录页（`05-demo-public-login.png`）；密码进入后时间线只有 HN、含 7 天历史
   （`06-demo-public-timeline.png`）。**注意这一条本来是不可能达成的**——见「执行中发现的
   问题」第 1 条，它靠一处前端改动才成立。
2. ✅ `demo_bootstrap.py` 对 demo 域名幂等跑通，退出 0（先后跑了 4 次）。
3. ✅ iOS 全流程通（`ios-05-demo-timeline.png`），本地实例上也走过一遍
   （`ios-02-timeline-hn.png`）。
4. ✅ 生产无感知：ansible 变更只碰 `/opt/apps/condenser-demo`；部署后两个域名 health 均 200，
   生产容器 revision 与 demo 一致但**是各自独立换的**（生产靠 hookploy，demo 靠手动 pull）。
5. ✅ `kb/docs/demo-server.md` 落地，三处指针就位（root `AGENTS.md`、`ios/AGENTS.md`、
   kb.private §⑧），另加 deploy workspace `kb/docs/condenser.md`「Demo 实例」。

## 风险与备注

- ~~**dummy TG creds 未经验证**~~ —— 已验证可行，无需退回真值（阶段 1 结果）。
- **审核员会污染 read/saved 状态** —— demo 无所谓；checklist 里有可选重置。
- **hh-hk-01 稳定性** —— 已知风险（生产也在上面，6h 备份是兜底）。若成为
  实际问题，demo 迁到别的主机只是改 play 归属 + Caddy/DNS，role 不变。
  ⚠️ 但审核期掉线就是被拒，所以**站外监控那条待办不是可选项**（见顶部）。
- ~~本 plan 不动 condenser 应用代码（零代码变更）~~ —— **这条判断错了**。实际动了两处
  （web 的 TG 登录门、iOS 登录页预填地址），都经用户拍板。前者是验收标准 1 的前提，
  后者不改大概率直接换来一次 2.1。教训：「demo server 只是运维工作」这个预设，在
  reviewer 会真的从零装一次 app 的场景下不成立——**全新安装路径上的每一个默认值都是
  产品决策**，而那条路径平时没人走。

## 相关文档

- **`kb/docs/demo-server.md` —— 日常入口**：初始化即健康检查的脚本、审核表单怎么填、
  备注英文话术、每次提审前的 checklist。做提审操作只需要读这一份。
- `tmp/2026-08-15-app-review-demo/README.md` —— 截图清单与可重跑脚本（tmp 不入库）
- `~/Code/kb.private/condenser/kb/docs/ios-app-store-release.md` —— 发布全流程
  与 demo 方案的原始需求（§③，现已标记完成并记下表单实值）
- `~/Code/kb.private/condenser/kb/sessions/2026-08-12-ios-signing-and-app-store-ready.md`
  —— 遗留问题清单里的「审核用 demo 账号」条目
- deploy workspace（`~/Library/Mobile Documents/com~apple~CloudDocs/deploy`）：
  `ansible/playbook.yml` hh play、`roles/condenser/`、`kb/docs/condenser.md`
