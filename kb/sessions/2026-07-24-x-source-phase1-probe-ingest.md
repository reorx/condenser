---
created: 2026-07-24
tags:
  - session
  - x-twitter
  - multi-source
  - local-probe
  - bdd
---

# X 信息源 Phase 1：local probe + ingest + 存档

## 概要

按 `kb/plans/2026-07-24-x-source-local-probe.md` 完成 Phase 1，即 X (Twitter) 信息源的
**采集与存档**闭环：schema v7、服务端 ingest/probe-config 契约、跑在本机的独立 probe 包、
web 订阅页 X 区块。这是项目第一个**推模式**信源——X 数据只存在于本机浏览器登录态里，
服务端永远不主动抓，由 probe 调 [bird](https://github.com/steipete/bird) CLI 读取后推上来。

Phase 1 刻意**不碰任何阅读界面**（timeline 是 Phase 2、反馈 3、判定 4、iOS 5）：目的是尽早部署，
让存档和未来的训练数据先攒起来（与 HN Phase 1 同一策略）。

BDD 流程：先按 plan 的场景清单写 `tests/test_x_source.py`（27 个场景，fixture 用**真实 bird 输出**
`tests/fixtures/x/`，由 `tmp/make_x_fixtures.py` 从 `tmp/2026-07-24-bird-samples/` 里按形态挑选），
再实现到全绿；最后用真机端到端（真 bird → probe → 真 ingest）+ 浏览器走查验收。

## 两个实现期决策（plan 未定 / 与 plan 相左）

1. **关注人订阅的主键用 handle，不用数字 user_id**（用户拍板）。plan 原定用数字 id（改名稳定），
   但服务端根本拿不到它：bird 只在 probe 本地，web 端用户手上只有 @handle。折中方案是
   handle（小写）作 `channel_id`（probe 拿它直接喂 bird），数字 id 在**首次 ingest 时从
   `authorId` 学到**写进 `config.user_id`，作为改名后的人工修复线索。
2. **`name` = X 上的显示名，学到之前留 NULL**。最初写了 `@handle` 占位，截图里立刻暴露成
   「**@geoffreylitt** @geoffreylitt」重复；改为 NULL + 客户端 fallback 到 handle。

## ⚠️ 实测发现：For You 每次调用重新采样（推翻 plan 的容量假设）

连续 3 次 `bird home -n 20 --json` 返回 **60 条互不重叠**的推文（overlap 0/20、0/20）。X 的
For You 端点每请求给一份新样本，不是稳定窗口。后果：

- plan 里「~500 条/天」的估算偏低一个量级：n=50、30min 一轮 ≈ **2400 条/天**（≈88 万/年）。
  影响 Phase 4 向量存储估算（256 维 ≈ 1KB/条 → ~900MB/年）与 Phase 2 的阅读量。
  **待定**：probe 频率 / For You 是否限量存档 / 是否提前上过滤。
- 反向坐实了 `first_seen_at` 排序决策（算法捞出的旧推按 `created_at` 排会插进历史中间）。
- For You 一侧的幂等实践中观测不到（永远全新）；关注人 feed 会重复，实测第二轮正确报 0 new。

已回写进 plan 的「bird 输出实测结论」与 AGENTS.md 状态段。

## 修改的文件

**服务端**

- `condenser/db.py` — `SCHEMA_VERSION` 6→7；新增 `XTweet` / `XFeedItem` / `ItemFeedback`
  三张表（纯新建，升级即 `create_tables`，无数据迁移）+ X 订阅 CRUD + tweet/feed-item 的
  存取（`upsert_x_tweet` 全量刷新 vs `insert_x_tweet_if_absent` 不覆盖内嵌引用推）。
- `condenser/x.py`（新）— 容错解析（字符串 id → int64、legacy 时间格式、media/metrics/article
  透传、`quotedTweet` → 自引用行、转推只能从 `RT @x:` 文本前缀取 `rt_of_handle`）、幂等 ingest、
  `probe_config`、`_learn_user_identity`、`status`。
- `condenser/routers/x.py`（新）— 订阅 CRUD + `probe-config` + `ingest` + `/api/x/status`。
- `condenser/types.py` — `XSubscribeBody` / `XSubscriptionPatch` / `XIngestBody`
  （`tweets: list[Any]` 故意不校验：一个漂移字段不该在门口打回整批）。
- `condenser/config.py` — `CONDENSER_X_ENABLED` / `_HOME_COUNT` / `_USER_COUNT`；`app.py` 挂路由。
- `pyproject.toml` — `testpaths = ["tests"]`（否则 root pytest 会去收集 probe 的测试）。

**probe（新的独立 uv 包 `probe/`）**

`condenser_probe/{config,bird,client,runner,__main__}.py` + `tests/test_probe.py`（11 个）
+ `README.md` + launchd plist 示例。无状态、无本地 feed 配置，只要 server URL + device token。

**前端**

`components/subscriptions/XSection.tsx`、`XSubscriptionRow.tsx`、`components/XGlyph.tsx`、
`lib/types.ts`（`XSubscription` / `XStatus` / `XPushCount`）、`lib/api.ts`、
`pages/SubscriptionsView.tsx`（第三个 tab）。

**文档**：`AGENTS.md`（架构 v7 段、`x.py` 模块行、新增 probe 小节、状态段）、
`frontend/AGENTS.md`（组件清单三行）、`README.md`、`.env.example`、plan 文档。

## 验收

- 188 backend（其中 X 27）+ 11 probe + 45 frontend 全绿，`pnpm build` 通过。
- 真机端到端：scratch 后端 + 真 bird，`foryou` 与 `@novoreorx` 两个 feed 各 10 条推上去，
  quote 自引用行、media 宽高、metrics、`created_at` 全部正确落库，孤儿 feed item 为 0；
  第二轮关注人 feed 正确报 0 new/0 new_items；`user_id=132736859` / `name=Reorx` 自动学到。
- 浏览器走查（Playwright + 系统 Chrome，agent-browser 的二进制软链已坏）：X tab 明/暗/移动三态
  截图 + 添加→暂停→退订全流程。截图归档 `tmp/2026-07-24-x-source-phase1/`。

## 下一步

Phase 2（timeline 接入：`sources/x.py` provider + `items.py` 的 `x:` key/envelope + `XCard`）。
开始前先定 For You 的容量策略（见上文实测发现）。
