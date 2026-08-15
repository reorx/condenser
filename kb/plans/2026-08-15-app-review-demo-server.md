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

## 待用户确认的决策点

1. **密码写在哪**。用户指示「密码写到 demo server 文档里」，但 condenser 是
   **公开仓库**。按 kb.private 惯例（同 `ios-app-store-release.md` 的处理），
   建议：公开 `kb/docs/demo-server.md` 写 runbook（架构、脚本、提审步骤、备注
   话术），密码本体与「密码放进 App Review 表单」的实值记录进
   `kb.private/condenser/kb/docs/`，公开文档留指针。若用户认为 demo 密码
   低价值可公开（它同时也会交给 Apple），则按原指示写公开文档。
   **计划按 kb.private 方案执行，除非用户否决。**
2. **demo 是否跟随自动部署**。推荐**不接** hookploy：审核周期内稳定压倒新鲜，
   一次坏部署可能直接导致 2.1 被拒；每次提审前用 checklist 里的一条命令手动
   `docker compose pull && up` 刷新镜像即可。备选：加一个 hookploy 条目与生产
   同步（代价是审核期间也会被 push 触发重启/换版本）。
3. **端口**：建议 3460（生产 3459 相邻）。

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

### 阶段 3 —— demo 数据与线上验收

1. 对 `https://condenser-demo.reorx.com` 跑 `scripts/demo_bootstrap.py` → HN
   front 订阅 + 7 天历史就位。
2. 浏览器过一遍 reviewer 流程（登录页 → 密码 → 时间线）；隔一个采样周期
   （≥10 分钟）确认新故事仍在进来（采样循环活着）。
3. iOS（模拟器或真机）指向 demo 域名走完整 reviewer 序列。截图并入
   `tmp/2026-08-15-app-review-demo/`。

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

## 验收标准

1. `https://condenser-demo.reorx.com` 冷加载出登录页；输入 demo 密码可进入，
   时间线只有 HN 内容且含 7 天历史。
2. `scripts/demo_bootstrap.py` 对 demo 域名幂等跑通、退出码 0。
3. iOS 按 reviewer 步骤（URL → /authorize → 密码 → 配对 → 时间线）全流程通，
   有截图存档。
4. 生产实例全程无感知（独立容器/DB/端口/域名；ansible 变更不触碰
   `/opt/apps/condenser`）。
5. `kb/docs/demo-server.md` 落地，AGENTS.md 与 kb.private 文档指针就位。

## 风险与备注

- **dummy TG creds 未经验证** —— 阶段 1 第一步就是验证它；有备选（真实
  api_id/hash）。
- **审核员会污染 read/saved 状态** —— demo 无所谓；checklist 里有可选重置。
- **hh-hk-01 稳定性** —— 已知风险（生产也在上面，6h 备份是兜底）。若成为
  实际问题，demo 迁到别的主机只是改 play 归属 + Caddy/DNS，role 不变。
- 本 plan 不动 condenser 应用代码（零代码变更），只新增脚本、ansible role
  副本、文档。

## 相关文档

- `~/Code/kb.private/condenser/kb/docs/ios-app-store-release.md` —— 发布全流程
  与 demo 方案的原始需求（§③）
- `~/Code/kb.private/condenser/kb/sessions/2026-08-12-ios-signing-and-app-store-ready.md`
  —— 遗留问题清单里的「审核用 demo 账号」条目
- deploy workspace（`~/Library/Mobile Documents/com~apple~CloudDocs/deploy`）：
  `ansible/playbook.yml` hh play、`roles/condenser/`、`kb/docs/condenser.md`
