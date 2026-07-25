---
created: 2026-07-24
tags:
  - plan
  - multi-source
  - x-twitter
  - local-probe
  - feedback-ranking
---

# X 信息源：local probe + 反馈判定

通过运行在用户本地电脑上的 **local probe**（调用 [bird cli](https://github.com/) 读取已登录账号的数据）接入 X (Twitter) 信息源。两种订阅形态：**For You** 算法流（对标 HN front page）和**关注的人**（对标 TG 频道）。For You 叠加一层用户反馈驱动的判定：用户对推文 thumb up/down，服务端据此对新推文计算 verdict（positive / neutral / negative）。

这是项目第一个**推模式**的源（TG/HN 都是服务端主动拉；X 的数据只存在于本地 bird 的 cookie 会话里，由 probe 推给服务端），也是第一个同时具备「feed 型 + 账号型」两种订阅的源。

## 进展（更新于 2026-07-25）

| Phase | 状态 | 说明 |
|---|---|---|
| 1 — probe + ingest + 存档 | ✅ **完成 2026-07-24** | schema v7、`condenser/x.py`、`routers/x.py`、`probe/` 包、web 订阅区块。188 backend（含 27 X）+ 11 probe + 45 frontend 绿；真机端到端 + UI 截图 `tmp/2026-07-24-x-source-phase1/`。会话记录：`kb/sessions/2026-07-24-x-source-phase1-probe-ingest.md` |
| 2 — timeline 接入 | ✅ **完成 2026-07-25** | `sources/x.py` provider、`items.py` 的 `x_key`/`x_envelope`、`feed` 作用域、`/api/sources` 的 X 分组、X 收藏快照、`/api/x/avatar/{handle}`、web 卡片 + `/s/:source/:feed` 路由。容量策略已定（见下）。211 backend（含 23 X timeline）+ 51 frontend 绿；对本地 dev 后端做了真实端到端（fixture 推送 → 真实 UI），截图 `tmp/2026-07-25-x-phase2-timeline/` |
| 3 — 反馈闭环 | ⬜ 未开始 | `item_feedback` 表已在 v7 建好，等 API + UI |
| 4 — Embedding 判定 | ⬜ 未开始 | `x_embeddings` / `x_vec_labeled` 届时才建（SCHEMA_VERSION 8）；存储估算需按新容量重算（见下方修正） |
| 5 — iOS 适配 | ⬜ 未开始 | Kit 的 `XTweet` payload + envelope 分发 + `XCard`；注意 iOS 也要遵守「For You 不进聚合流」 |

未决问题：

1. ~~**For You 的容量策略**~~ —— 已定案（2026-07-25，见决策记录「For You 的容量策略」）。
2. ~~**作者头像**~~ —— 已定案：unavatar.io 代理（`/api/x/avatar/{handle}`，`fallback=false`），失败回落字母头像。
3. **旧 raw 的重 parse 回填工具** —— 目前只保证 raw 留底，还没有「格式漂移后按新解析器重刷」的脚本。
4. **verdict 徽标的 UI 位置**（Phase 4 才需要）—— `XCard` 已经把 `verdict` 透到前端类型里，卡片上还没有呈现位。

## 决策记录

与用户讨论后确定（2026-07-24）：

| 决策点 | 结论 | 理由 |
|---|---|---|
| For You 的 timeline 排序时间 | **`first_seen_at`**（probe 首次推送入库时刻），非推文 `created_at` | 与 HN front page 决策完全一致：算法会捞出几天前的旧推，按 `created_at` 排会插进 timeline 历史中间，破坏 append-only 与 cursor 语义。卡片上仍展示推文原始发布时间。关注人 feed 则用 `created_at`（本来就是时序流，同 TG） |
| negative 判定的呈现 | **先只打标不隐藏**：verdict 以徽标形式展示，观察准确率；人工确认靠谱后再启用折叠/过滤（后续迭代） | 算法会误杀，不可见的误杀永远发现不了；先攒信任再放权 |
| 判定算法选型 | **Embedding 分类**：标注推文取 embedding，新推文按相似度（kNN / 逻辑回归）判定 | 效果与成本的平衡点；语义泛化优于作者/关键词统计，运行成本远低于每轮 LLM judge |
| Embedding 模型 | **DashScope `text-embedding-v4`**，走 OpenAI 兼容接口（base URL 由 env 注入，无供应商专用代码） | 用户指定（2026-07-24）；参考 `../tenderbuddy` 的既有接法，见 Phase 4 示例代码 |
| up/down 反馈范围 | **全部 X 推文**（For You + 关注人 feed 都可标注），但 verdict 计算与未来的隐藏动作**只作用于 For You** | 扩大标注数据量（正好补 embedding 方案的训练数据短板）；关注人的噪音用退订解决，不需要算法介入 |
| 收藏作为反馈信号 | **收藏（save）是比 thumb up 更高级别的肯定**：`saved_items` 中的 X 推文自动进入训练集作强正样本，权重高于 up | 用户补充（2026-07-24）。零额外操作成本的高置信标注；不新建表，训练时直接读 `saved_items` |
| probe 配置来源 | **服务端下发**：probe 每轮先拉 probe-config，按当前 enabled 的 X 订阅决定抓什么 | 订阅管理保持在 web，probe 零本地配置；与「订阅驱动采样」的既有语义一致（HN 先例） |
| probe 状态 | **无状态**：每轮全量推最近 N 条，服务端按 tweet id 幂等去重 | probe 崩溃/休眠/重装零恢复成本 |
| probe 鉴权 | **复用 device token**（`devices` 表 + web `/authorize` 流程） | probe 本质是一种 device，服务端零新增鉴权代码 |
| 关注人订阅的 key | **handle（小写）作主键，数字 user_id 首次 ingest 自动学到写进 config** | 实现时发现的矛盾：数字 id 才是改名稳定的，但服务端拿不到它（bird 只在 probe 本地，web 端用户手上只有 @handle）。折中：probe 要的就是 handle，数字 id 作为改名后的人工修复线索留底。用户拍板于 2026-07-24 |
| `name` 字段语义 | **= X 上的显示名**，学到之前留 NULL（不写 `@handle` 占位） | 占位会让 UI 出现「@x @x」重复；NULL 让客户端 fallback 到 handle |
| **For You 的容量策略** | **隔离 + 降频**：For You 不进 All 聚合视图，只在 `/s/x` 与 `/s/x/foryou` 可见；`CONDENSER_X_HOME_COUNT` 默认 50 → 20。关注人 feed 照常进 All。**存档仍是全量**，不做限量存档 | 用户拍板（2026-07-25）。实测 ~2400 条/天，直接混入会淹没 TG/HN；但限量存档会伤到 Phase 4 的训练数据，所以只压「阅读面」不压「存档面」。For You 本来就是「想刷才刷」的东西，把它放在专属入口后面正好符合它的性质 |
| 作者头像 | **unavatar.io 代理**（`GET /api/x/avatar/{handle}` → `unavatar.io/x/{handle}?fallback=false`），失败 404 → 客户端字母头像 | 用户拍板（2026-07-25）。For You 一屏 ~46 个不同作者，头像是最强的定位线索，字母头像在这个密度下几乎无效。`fallback=false` 是关键：否则 unavatar 会回一张通用占位图，客户端反而无法降级 |
| 同一条推同时出现在两个 feed | **去重，保留「关注人」那次出现**（`ROW_NUMBER()` 分区取胜者） | For You 本来就包含你关注的人。保留关注人那次出现意味着它按 `created_at` 排序，跟同一个人的其它推一致；否则同一条推在 All 和 `/s/x` 里会落在两个不同位置 |
| 聚合视图的「全部已读」 | **不动 For You**（`source='x'` 或 `feed=foryou` 才扫它） | 聚合视图从来没显示过 For You，从那里把它清掉等于烧掉一整个没看过的 feed |

技术要点（实现侧）：

- item key：`x:{tweet_id}`（snowflake int64，`ref1` 放得下，`ref2=0`）。`read_items` / `saved_items` / `hidden_items` / envelope / federated merge 全部零改动复用。
- 订阅：`(source='x', channel_id='foryou')` 为 For You；`(source='x', channel_id='<lowercased handle>')` 为关注人 —— ~~数字 id 存 `channel_id`~~ 已按上表「关注人订阅的 key」决策改为 handle 作主键，数字 `user_id` 与 `handle` 存 `config`，显示名存 `name`（首次 ingest 学到）。`BareField channel_id` 当初就是为混型留的（TG 存 int，HN/X 存 str）。
- **raw JSON 必须留底**：bird 的输出跟着 X 内部 API 走，不是稳定 contract；解析层容错，raw 供格式漂移后重 parse 回填。

## 数据模型（Phase 1 = SCHEMA_VERSION 7；向量表在 Phase 4 = SCHEMA_VERSION 8）

同一条推文可能同时出现在 For You 和某个关注人的 feed 里，且 verdict 只挂在 For You 的出现上 —— 所以推文本体与「出现在哪个 feed」分开：

```
# SCHEMA_VERSION 7（Phase 1）
x_tweets       id (PK, tweet id), author_id, author_handle, author_name,
               text, created_at, media (JSON), metrics (JSON),
               quote_of (自引用 tweet id, 可空), rt_of_handle (TEXT, 可空, 见实测⑤),
               reply_to_id (可空), article (JSON, 可空), raw (JSON), fetched_at
x_feed_items   (channel_id TEXT, tweet_id INT) PK, first_seen_at,
               verdict (positive/neutral/negative, 可空; 仅 foryou 行计算),
               verdict_meta (JSON: score, 近邻样本, 算法版本)
item_feedback  (source, ref1, ref2) PK, verdict ('up'/'down'), created_at

# SCHEMA_VERSION 8（Phase 4 —— 维度等参数届时才冻结，不提前建表）
x_embeddings   tweet_id (PK), vector (BLOB float32, L2-normalized), model, created_at
x_vec_labeled  vec0 虚拟表（KNN 索引，仅训练集），见 Phase 4「向量存储」
```

- `item_feedback` 是**源通用**表（与 `hidden_items` 同款三元组形态），将来 HN 想做同样的事零迁移。
- 实现补记（v7 已落地）：`x_feed_items.channel_id` 存的就是订阅主键（`'foryou'` 或小写 handle）；
  `x_tweets` 另有实现期加上的 `author_id` 索引，`created_at` 可空（时间戳解析失败时留空并计入
  `parse_errors`，推文本体照存，raw 供重 parse）。
- 引用推展示为内嵌卡片，被引原推入 `x_tweets` 自引用行；转推展示为转发卡（复用 TG forward 的 UI 语言），但**只能靠文本启发式**（见实测⑤）。**thread 合并 v1 不做**。
- 索引：`x_feed_items(channel_id, first_seen_at)`、`x_tweets(author_id)`。

### bird 输出实测结论（2026-07-24，bird 0.8.0，样本 `tmp/2026-07-24-bird-samples/`）

实跑 `bird home -n 50 --json` / `bird user-tweets <handle> -n 10 --json`（Chrome cookie，`bird check`/`whoami` 验证凭据）得到的事实，数据模型据此定案：

1. **顶层是纯 JSON 数组**，条目扁平（bird 已消化过 GraphQL 原始结构）。这加重了 raw 留底的必要性——上游 X API **和** bird 自身的转换逻辑都是漂移源。
2. **`id` / `authorId` / `conversationId` 是字符串**（JS 大整数安全），入库转 int64。
3. **`createdAt` 是 legacy 格式** `Thu Jul 23 14:46:20 +0000 2026` → `strptime('%a %b %d %H:%M:%S %z %Y')`。
4. **metrics 只有 `replyCount` / `retweetCount` / `likeCount`**，无 views/bookmarks。
5. **转推没有结构化字段**：被压平为 `RT @orig: <text>` 文本前缀，author = 转推者，无 retweetedTweet 对象。→ schema 用 `rt_of_handle`（从前缀 parse 出原作者 handle，可空）替代原设想的 `rt_of` id 自引用；legacy RT 格式有截断风险（样本未观察到，未证实）。可考虑给 bird 提上游 issue。
6. **`quotedTweet` 是完整内嵌对象**（默认 depth=1，media 齐全）→ 自引用行设计可行，从内嵌 payload 直接建被引推的行。
7. **media**：`type` 见到 photo/video（animated_gif 待观察），photo 有 `url/width/height/previewUrl`，video 加 `videoUrl/durationMs`。**宽高齐全**——前端图片占位（对齐 TG 的 media_width/height 实践）无忧。
8. **`author` 只有 `username`/`name`，无头像 URL**。头像方案：unavatar.io 代理、或 v1 字母头像（对齐 ChannelAvatar 的 fallback）。
9. **X 长文（article）只有 `title` + `previewText`（~200 字符截断）**，`text` 字段即标题——判定文本需拼 `title + previewText`，全文拿不到。
10. **For You 混有回复**（`inReplyToStatusId`，2/50）和**疑似无标记的广告**（推广文案账号出现在 50 条中，无任何 promoted 标记——推测 bird 不过滤/不标注 ads）。广告识别恰好是判定算法（作者先验 + 文风通道）的用武之地。
11. **50 条里 46 个不同作者**——作者先验通道冷启动会慢（单作者样本极少），佐证多通道集成的必要性（见算法讨论笔记）。
12. bird 另有 **`following`**（关注列表自动同步可行，「后续方向」升级为已验证）、**`likes` / `bookmarks`**（自己的喜欢/书签列表——潜在的**免费隐式正样本**，强度介于 up 与 save 之间，留给算法 Phase 评估）。

### ⚠️ 追加实测（2026-07-24，Phase 1 实现期间）：For You 每次调用重新采样

连续 3 次 `bird home -n 20 --json`（间隔数秒）返回 **60 条互不重叠**的推文（overlap 0/20、0/20）。
即 X 的 For You 端点每请求给一份新样本，**不是一个稳定窗口**。推论：

- **容量假设作废**：本计划「~500 条/天」的估算偏低一个量级。n=50、30min 一轮 ≈ **2400 条/天**
  （≈ 88 万/年）。直接影响 Phase 4 的向量存储估算（256 维 ≈ 1KB/条 → ~900MB/年，仅 embedding）
  与 Phase 2 的阅读量（timeline 会被 For You 淹没）。**待定**：probe 频率、是否对 For You 限量
  存档、或把 negative 过滤提前到判定可用之时。
- **`first_seen_at` 排序决策被进一步坐实**：算法捞出的旧推按 `created_at` 排会插进历史中间。
- **For You 一侧的 ingest 幂等在实践中观测不到**（永远是全新的）；幂等仍然重要（probe 重试、
  轮次重叠），且关注人 feed 会重复，实测第二轮正确报告 0 new。

## Phase 1 — probe + ingest + 存档（最先上线，开始攒数据）⏰ ✅ 已完成 2026-07-24

实现落点：schema v7（`x_tweets` / `x_feed_items` / `item_feedback`，纯新建表无迁移）、
`condenser/x.py`（解析 + ingest + probe-config + status）、`condenser/routers/x.py`、
`probe/`（独立 uv 包 `condenser-probe`）、web 订阅页 X 区块
（`XSection` / `XSubscriptionRow` / `XGlyph`）。
测试：27 X 场景（fixture 用真实 bird 输出，`tests/fixtures/x/`）+ 11 probe，
全量 188 backend / 45 frontend 绿；真机端到端（真 bird → probe → ingest）与 UI 截图见
`tmp/2026-07-24-x-source-phase1/`。`x_embeddings` 按本文 schema 块留到 Phase 4
（正文早前「四张表」的说法是旧稿残留）。

与 HN Phase 1 同理：**存档和标注数据越早开始攒越好**，本 phase 不含 breaking change，独立部署。

### 服务端（已交付，✓ = 与计划一致，△ = 实现期调整）

- ✓ 三张表（`x_tweets` / `x_feed_items` / `item_feedback`），纯新建，升级即 `create_tables`；
  `x_embeddings` 留到 Phase 4。
- △ `POST /api/sources/x/subscriptions` `{channel_id: "foryou" | "<handle>"}`（`@`/大小写/空格由服务端
  归一化，非法 handle → 422），可选 `n` 覆盖抓取条数；`name` 不再由客户端提供占位。
  PATCH（`config` 为**合并**而非替换，否则会丢掉学到的 `user_id`）/ DELETE 同 HN 形态。
  额外加了 `GET /api/sources/x/subscriptions` 供 web 区块列表（Phase 2 前 `/api/sources` 还没有 X 分组）。
- ✓ `GET /api/sources/x/probe-config` → `{feeds: [{channel_id, kind, handle, n}]}`；无 enabled 订阅
  或 `CONDENSER_X_ENABLED=false` 时为空清单。
- ✓ `POST /api/sources/x/ingest` `{channel_id, tweets: [<bird 原始 JSON>]}` → parse + 按 id upsert
  `x_tweets`，`x_feed_items` 不存在才插入（`first_seen_at` 不重置）；parse 失败计数入 status、raw 照存。
  △ 内嵌引用推用 insert-if-absent（depth=1 的浅拷贝不得覆盖已有完整行）；未订阅/已暂停的
  channel_id → 404；源被禁用 → 503。
- △ 状态端点路径是 `GET /api/x/status`（与 `/api/hn/status` 对齐，非 `/api/sources/x/status`），
  返回 `{source_enabled, subscribed, tweets_total, feed_items_total, last_push_at, last_push_counts, parse_errors}`。
- ✓ web 订阅页 X 区块（`XSection` / `XSubscriptionRow` / `XGlyph`，Subscriptions 页第三个 tab）。

### probe（monorepo `probe/` 目录，独立 uv 包 `condenser-probe`）—— 已交付

- ✓ 每轮：拉 probe-config → 逐 feed 跑 `bird home -n N --json` / `bird user-tweets <handle> -n N --json`
  → POST ingest；单 feed 失败（bird 报错 / 非 JSON / ingest 失败）不影响其余，逐条 log。
- ✓ 配置仅两项：服务端 URL + device token（env 或 `~/.config/condenser-probe/config.json`）。
- ✓ launchd 定时（`run` = 跑一轮就退出，笔记本休眠只是漏轮次）；另有 `check`（同时验证 bird 会话与
  服务端 token）和 `watch --interval`（前台调试用）。抓取条数由服务端 probe-config 下发，频率仍是本地定时。

### 测试（BDD 先行，bird 输出用真实 JSON fixture）—— 全部覆盖

`tests/test_x_source.py`（27）+ `probe/tests/test_probe.py`（11）。fixture 由
`tmp/make_x_fixtures.py` 从真实样本里按形态挑选（quote/RT/reply/article/photo/video/纯文本）。

- ✓ 无 enabled X 订阅 → probe-config 空清单；添加后出现对应 feed 条目。
- ✓ ingest 幂等：重复推送不产生重复行、不重置 `first_seen_at`；metrics 会刷新。
- ✓ RT/quote：被引原推入库为自引用行（且不被浅拷贝覆盖），RT 取 `rt_of_handle`。
- ✓ 畸形 tweet JSON：raw 留底 + parse_errors 计数 + 不毁整批；时间戳解析失败仍存推文。
- ✓ 鉴权：Bearer 与 cookie 皆可（与 device token 既有语义对齐），无凭据 401。
- 额外：v7 升级不动既有数据、handle 归一化与去重、跨 feed 同推文共用一行、首次 push 学到 user_id/name。

## Phase 2 — timeline 接入 ✅ 已完成 2026-07-25

容量策略先定后写（见决策记录）：**隔离 + 降频** —— For You 不进聚合流，`CONDENSER_X_HOME_COUNT`
50 → 20，存档不限量。

### 服务端（✓ = 与计划一致，△ = 实现期调整）

- ✓ `sources/x.py` provider：`x_feed_items JOIN x_tweets`（+ 自连接取被引推），anti-join
  `read_items` / `saved_items` / `hidden_items`，挂进 k-way merge。
  △ 排序键做成一列 SQL 表达式 `SORT_AT_SQL`（For You → `first_seen_at`，关注人 →
  `created_at`，都 COALESCE 回 `first_seen_at` 兜住时间戳解析失败的行），这样混合查询里
  两种 feed 能用同一个 cursor 列比较。
  △ 同一条推出现在两个 feed 时用 `ROW_NUMBER()` 去重，保留关注人那次出现。
  △ **去重必须按查询作用域来排名**（自审时发现的 bug 并已加回归测试）：feed 过滤放在
  子查询*里面*。放外面的话，一条同时在两个 feed 的推在「只看 For You」视图里会拿到
  rank 2 而被过滤掉——从它自己的 feed 里消失。顺带解决性能：过滤下推后
  `x_feed_items(channel_id, first_seen_at)` 索引才用得上，否则每翻一页全表扫描。
  △ 单 feed 作用域时跳过窗口函数（`(channel_id, tweet_id)` 是主键，一个 feed 里不可能重复），
  且 For You 单独看时排序键就是 `first_seen_at` 这一列本身 —— `EXPLAIN QUERY PLAN` 从
  「materialize + 全量 temp b-tree 排序」变成「走索引 + 只对并列项排序」。For You 是唯一
  高速增长的 feed（~1000 条/天），这条路径值得特化。
- △ **`feed` 作用域**：`/api/timeline`、`/timeline/days`、`/timeline/new`、`/read/bulk`
  都接受 `feed`（handle 归一化在 provider 里做，`@Name` / `NAME` 都认）。计划里没预见到
  X 是第一个「一个源多个 feed」的源 —— HN 只有 `front`，TG 用 `channel_id`。
- ✓ `items.py`：`x_key` / `parse_key` / `x_envelope`。
  △ snowflake id 在 JSON 里一律**转字符串**（int64 超出 JS 安全整数范围，不转会被静默改值）。
- ✓ `GET /api/sources` 出现 X 分组，带每个 feed 的未读数。
- ✓ X 收藏：快照直接存 envelope payload（引用推已内嵌），删档后仍可渲染。
- △ `GET /api/x/avatar/{handle}`：unavatar 代理（Phase 1 实测⑧留下的坑，这一步补上）。
- △ `mark_read_bulk` 的聚合形态**跳过 For You**（只有 `source='x'` / `feed=foryou` 才扫）。

### web（✓ 全部交付）

- `XCard` + `XQuoteCard` + `XMedia` / `XMediaThumb` / `XLightbox` + `XAvatar`
  （清单见 `frontend/AGENTS.md`）。RT 前缀转成「Retweeted @orig」标题并从正文里剥掉；
  长文的 `text` 就是标题，只渲染 article 卡不重复打印。
- `/s/:source/:feed` 路由 + `SidebarXFeedLink`（For You 只有这一个入口）。
- `ItemDetailPane` / `ItemDetailInfo` 的 X 分支：作者、来自哪个 feed、发布 vs 抓取时间、
  互动数、RT/引用/回复来源、"Open original on X"。
- 推文媒体和头像都走后端代理，浏览器不直连 X。

### 测试

`tests/test_x_timeline.py`（23 场景）+ `XCard.test.tsx`（6）。211 backend / 51 frontend 绿。
关键场景：For You 不进聚合流、只订阅 For You 时聚合流为空、`/s/x` 两个 feed 都在、
feed 作用域与 handle 归一化、两种排序键、跨 feed 去重、envelope 形状（含字符串 id）、
被引推不单独成条、read/save/hide 复用通用管道、删档后收藏仍可渲染、聚合「全部已读」
不动 For You、days/new 的作用域。

## Phase 3 — 反馈闭环（web + iOS）⬜ —— `item_feedback` 表已在 v7 就位

- `POST /api/feedback {key, verdict: "up"|"down"}` / `DELETE /api/feedback/{key}`（撤销）。
- web：X 卡片上 thumb up/down（**所有 X 推文均可标注**，高亮已选态，可撤销）；iOS 同步。
- 反馈只是写 `item_feedback`，本 phase 不做任何判定。

## Phase 4 — Embedding 判定 ⬜

- **训练信号三档**：save（强正，权重最高）> up（正）> down（负）。训练集 = `item_feedback`（source='x'）∪ `saved_items`（source='x'）联合，训练时实时读表——取消收藏即自动退出训练集，无需同步逻辑。同一推文 save + down 并存属矛盾样本，从训练集剔除（预期极罕见）。kNN 的权重体现为投票加权；逻辑回归为样本权重。
- 标注推文（up/down/save）入库时算 embedding 存 `x_embeddings`；embedding 后端做成可插拔接口，本地模型留为替代实现。Phase 4 上线时对存量已收藏/已标注推文做一次 embedding 回填。

### 向量存储：sqlite-vec（SCHEMA_VERSION → 8）

SQLite 原生无向量能力，选 [sqlite-vec](https://alexgarcia.xyz/sqlite-vec/python.html)（PyPI 包自带预编译 loadable extension）。设计为**两层存储、职责分离**：

**1. `x_embeddings` —— storage of record（普通 peewee 表，BLOB）**

所有算过的向量都存这里：float32 BLOB（`sqlite_vec.serialize_float32()`，写入前 L2 normalize），`model` 列记 `text-embedding-v4@256`。定位是**可重建缓存**（对齐 `is_filtered` 的精神）——文本都在 `x_tweets.text`，任何时候可重嵌；换模型/维度 = 按 `model` 列筛选重算，不做原地迁移。

**2. `x_vec_labeled` —— KNN 索引（vec0 虚拟表，只装训练集）**

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS x_vec_labeled USING vec0(
  embedding float[256] distance_metric=cosine
);
-- rowid = tweet_id（snowflake int64，vec0 rowid 放得下）
```

**为什么不把全量向量都进 vec0、用 metadata 列过滤出训练集**：判定查询永远只搜「已标注的推文」，训练集规模是百~千级，全量表是十万~百万级；小表 KNN 天然快，且「在/不在索引里」的 presence 同步远比「label 值」同步简单——label 的真值只存在于 `item_feedback` / `saved_items`，vec0 表不复制它，查询时 join 回去取。

**同步规则**（vec0 的 shadow table 在同一 SQLite 文件内、参与事务，与 label 写入同事务提交，不会漂移）：

- 标注产生（feedback POST / save）→ 确保 `x_embeddings` 有向量（关注人 feed 的推文此时才 lazy 嵌入）→ `INSERT INTO x_vec_labeled(rowid, embedding)`。
- 标注消失（feedback DELETE / unsave 且无其他标注）→ `DELETE FROM x_vec_labeled WHERE rowid = ?`。
- 兜底提供 `rebuild_labeled_index()`：truncate 后从 `x_embeddings` ∩ (`item_feedback` ∪ `saved_items`) 全量重灌——升级 sqlite-vec、换模型、怀疑漂移时用。

**判定查询**（ingest 时对每条 For You 新推文）：

```sql
SELECT rowid AS tweet_id, distance
FROM x_vec_labeled
WHERE embedding MATCH :query_vec AND k = 15
```

结果在 Python 里 join label（save=强正/up=正/down=负）做距离加权投票 → verdict + `verdict_meta`（分数、命中的近邻 tweet_id 列表、`model@dims` 版本）。`k = ?` 是 sqlite-vec 的推荐语法（`LIMIT` 形态要求 SQLite ≥ 3.41）；具体权重与 positive/negative 阈值留给回测定。

**扩展加载（关键工程点）**：peewee 连接是**线程本地**的（conftest 每 case 关连接的既有 gotcha 同源），扩展必须对**每个新连接**加载。telememo 的 `db = SqliteDatabase(None)` 不用改类——peewee `SqliteDatabase` 原生支持 `db.load_extension(path)`，注册后每次建连自动 `enable_load_extension` + load，condenser 在 `init_db` 里调用 `db.load_extension(sqlite_vec.loadable_path())` 即可（实现时验证 peewee 版本行为；兜底方案是包一层 `_add_conn_hooks`）。vec0 虚拟表不建 peewee model，`init_db` 里原生 SQL 建表——**必须在扩展加载之后**。运行环境：Docker/Linux 与 uv 管理的 CPython 都支持扩展加载；macOS **系统自带** Python 不支持（sqlite-vec 文档明示），本项目不受影响但写进 README 提醒。

**维度与容量**（嵌入范围 = For You 全部 + 被标注的关注人推文）：

⚠️ 下表原按 ~500 条/天估算，Phase 1 实测 For You 每次调用重新采样（见上方追加实测），
n=50 / 30min 一轮实际约 **2400 条/天**，即右列要 **×5**（256 维一年 ~950MB，1024 维 ~3.7GB）。
**Phase 2 已把 n 降到 20**（决策：隔离 + 降频），30min 一轮 ≈ 960 条/天，256 维一年 ~380MB
—— 回到可接受区间，但 **retention 仍然是 Phase 4 的前置条件**（未标注向量保留 90 天后
prune，随时可重嵌）。注意降的是抓取量不是存档策略：`x_tweets` 仍然全量留底。

| dims | 单条 | 一年 @~500 条/天（原估） | 一年 @~2400 条/天（实测频率） |
|---|---|---|---|
| 1024 | 4 KB | ~750 MB | ~3.7 GB |
| **256（默认）** | 1 KB | ~190 MB | ~950 MB |

SQLite 文件是生产环境 bind-mount 的单文件，1024 维一年近 GB 不可接受。text-embedding-v4 支持 64~2048 可变维度（MRL 式训练，低维截断质量衰减平缓——推测，回测时用留一验证对比 256 vs 1024 再定案）。另一个杠杆是 **retention**：未标注推文的向量只在判定时刻用一次，保留 90 天供回测后 prune（可随时重嵌）；标注向量永久保留。两个杠杆叠加后存储进入稳态，不随时间线性膨胀。

### 判定算法流程

```
新 For You 推文（ingest 批次内逐条）
   │
   ▼
 ① 取判定文本
     普通推  → text
     纯转推  → 原推的 text（转推本体没有文字）
     引用推  → 本推 text + 被引推 text 拼接
   │
   ▼
 ② embedding（text-embedding-v4@256 → L2 normalize）→ qvec
   │
   ▼
 ③ 冷启动闸门
     训练集正样本 < P 或 负样本 < N ────────────────▶ neutral（不装懂）
   │ 通过
   ▼
 ④ KNN 检索
     SELECT rowid, distance FROM x_vec_labeled
     WHERE embedding MATCH qvec AND k = 15
   │
   ▼
 ⑤ 有效邻居过滤（OOD 闸门）
     只保留 distance ≤ D_MAX 的邻居；
     有效邻居 < M 个 ──「离所有标注都太远」──────────▶ neutral
   │ 通过
   ▼
 ⑥ join 标签并赋权（label 真值从 item_feedback / saved_items 取）
     label:  up   → +1
             save → +1，且样本权重 ×2（比 up 更高级别的肯定）
             down → −1
     相似度权: sim = 1 − distance（cosine 距离）
   │
   ▼
 ⑦ 加权打分
     score = Σ(simᵢ × wᵢ × labelᵢ) / Σ(simᵢ × wᵢ)     ∈ [−1, +1]
   │
   ▼
 ⑧ 三段阈值（刻意不对称）
     score ≥ +0.35                      ────▶ positive（推荐）
     score ≤ −0.55 且 down 邻居 ≥ 2 个   ────▶ negative（隐藏候选）
     其余                                ────▶ neutral
   │
   ▼
 ⑨ 落库
     x_feed_items.verdict + verdict_meta =
     {score, neighbors: [{tweet_id, distance, label}], model@dims, algo_ver}
```

设计意图：

- **默认答案是 neutral**。③（数据不足不装懂）和 ⑤（OOD：离所有标注都太远不硬判）两道闸保证只在有真实证据时才表态；⑤ 是最重要的一道——没有它，kNN 永远返回 k 个邻居，每条推文都会被强行打分。
- **⑧ 不对称是成本决定的**：误推荐 = 多看一眼，误隐藏 = 永远看不到。negative 阈值更严，且要求 ≥2 个不同的 down 邻居佐证——单条误标的 down 不能独自拉黑一片语义邻域。
- **save 的权重放在样本权重（×2）而非 label 值 +2**：score 保持在 [−1, +1]，阈值可解释、跨算法版本可比较。
- **verdict_meta 存命中邻居**是「先打标不隐藏」的配套：UI 可解释「因为它像你 down 过的这几条」，对误判的纠错点击回流成训练样本。
- 所有常量（P、N、k、D_MAX、M、±阈值）为占位值，Phase 1–3 攒下标注后**留一法回测定案**。
- verdict 只在 ingest 时算一次，标注变化不回溯已判定推文（For You 流式消费，回溯价值低；回测阶段可评估是否对最近 48h 重算）。
- **本节的 dense kNN 定位是 v1 baseline / 回测对照组**。算法演进方向（多通道弱信号集成：作者先验 + dense kNN + LLM 属性提取 + n-gram 贝叶斯，及 down-reason chips）见讨论笔记 `kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md`，通道取舍由留一法回测定。

### Embedding 接入：DashScope text-embedding-v4（OpenAI compatible）

选型确定（2026-07-24）：**DashScope `text-embedding-v4`**，走 OpenAI 兼容接口。参考实现 `../tenderbuddy/app/src/lib/openai.ts` + `utils/embedding.ts` —— 标准 OpenAI SDK + env 注入 base URL，不写任何 DashScope 专用代码，将来换供应商只改 env。

配置（复用 tenderbuddy 的 env 形态）：

```bash
CONDENSER_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
CONDENSER_EMBEDDING_API_KEY=sk-...
CONDENSER_EMBEDDING_MODEL=text-embedding-v4
CONDENSER_EMBEDDING_DIMENSIONS=256    # v4 支持 64~2048；容量考量见「向量存储」，回测后定案
```

最基本的调用（condenser 是 async httpx 栈，直接 POST 兼容端点，零新增依赖）：

```python
# condenser/embedding.py
import httpx

from condenser.config import settings


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. DashScope caps batch size at 10 — caller chunks."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f'{settings.embedding_base_url}/embeddings',
            headers={'Authorization': f'Bearer {settings.embedding_api_key}'},
            json={
                'model': settings.embedding_model,        # text-embedding-v4
                'input': texts,                           # len ≤ 10
                'dimensions': settings.embedding_dimensions,
            },
        )
        resp.raise_for_status()
        data = resp.json()['data']
        # order is not guaranteed by the contract — sort by index
        return [item['embedding'] for item in sorted(data, key=lambda x: x['index'])]
```

注意点（继承 tenderbuddy 的 Qwen 实践）：

- **批量上限 10 条/请求**（tenderbuddy `embedLargeTexts` 的 Qwen config：`maxTextsPerRequest=10`、每请求 ~8192 token 留 90% 余量）。推文短文本不会碰 token 上限，按 10 条一批切分即可；ingest 每轮 ~50 条 = ~5 个请求。
- 返回的向量先 L2 normalize，再经 `sqlite_vec.serialize_float32()` 落 `x_embeddings.vector`；`model` 列记 `text-embedding-v4@256`——换模型或维度时旧向量不可比，按 model 列筛选重算（存储细节见上节「向量存储」）。
- 失败重试简单指数退避（1s/2s），整批失败不阻塞 ingest（verdict 留空 = neutral，下轮补算）。
- ingest 收到 For You 新推文 → 算 embedding → 对标注集做 kNN（或标注量足够后逻辑回归）→ 写 `x_feed_items.verdict` + `verdict_meta`（分数、命中的近邻样本 id、算法版本——供徽标 tooltip 展示「为什么」）。
- 冷启动：标注量 < 阈值（如各 20 条）→ 全部 neutral，不装懂。
- UI：**verdict 徽标 only**（决策：先打标不隐藏）。negative 折叠/服务端过滤、positive 高亮/置顶，作为观察准确率之后的后续迭代，届时的纠错动作（对误判推文点 up/down）天然反哺标注集。
- 回测脚本：拿 Phase 1-3 攒下的标注做留一验证，上线前先看准确率数字。

## Phase 5 — iOS 完整适配 ⬜

- Kit：`XTweet` payload model + fixture、envelope 分发、feedback API。
- App：`XCard` / detail sheet、up/down 按钮、源切换菜单与订阅页出现 X、verdict 徽标。
- App 也要遵守「For You 不进聚合流」：源切换菜单里 X 的两级（源 / 各 feed）才是 For You 的入口。

⚠️ **Phase 2 部署后、Phase 5 之前的空窗**：iOS 的 `TimelineItem.source` 是普通 String、
payload 字段可选，所以 X 条目**不会炸解码**；但 `MessageListView.card(_:)` 的分发只认
`telegram` / `hn`，X 条目会渲染成**空白行**。影响范围仅限「关注人 feed」——For You 本来
就不进聚合流。规避办法：Phase 5 之前先只订阅 For You（web 上照常读 `/s/x/foryou`），
或者接受 iOS 上的空白行。要提前消掉，最小改动是在 iOS 侧过滤掉 payload 全空的条目。

## 风险

- **账号风险是 MTProto 灰色地带的加强版**：X 对第三方抓取的封号执法比 Telegram 激进得多。缓解：低频率、单点单账号、自担风险的自托管功能定位。
- **数据有空洞**：probe 依赖本地电脑开机在线。For You 本是采样性质影响小；关注人 feed 长时间离线会漏，n 可调大兜底。
- **bird 输出格式漂移**：raw 留底 + 解析容错 + status 暴露 parse_errors，格式崩了能及时发现并重 parse 回填。
- embedding API 依赖：判定是异步增强，API 挂了推文照常入库展示（verdict 留空 = neutral），不阻塞 ingest。
- **sqlite-vec 是 pre-1.0**（0.1.x）：vec0 shadow table 的磁盘格式可能随版本变。缓解：uv.lock pin 版本；升级视为「重建事件」——跑 `rebuild_labeled_index()` 即可，因为向量真值在 `x_embeddings`、label 真值在 `item_feedback`/`saved_items`，vec0 表整体可抛弃重灌。

## 后续方向（本计划不含）

- negative 折叠（「已折叠 N 条」可展开）与服务端过滤；positive 的高亮/单独视图。
- thread 合并展示。
- `item_feedback` 泛化到 HN（表已就位）。
- 关注人列表从 bird 自动同步（`bird following` 已实测存在）而非手动逐个订阅。
- `bird likes` / `bird bookmarks` 作为隐式正样本通道（强度介于 up 与 save 之间），probe 顺带采集。
