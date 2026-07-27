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
| 3 — 反馈闭环 | ✅ **完成 2026-07-25**（web；iOS 顺延到 Phase 5）；**理由 chips 补于 2026-07-26**（schema v9，三端齐活，见「Phase 3 补记」） | `/api/feedback` POST/DELETE、envelope 的 `feedback` 字段（timeline provider join + 收藏批量 join）、`XFeedbackButtons` + `useFeedback`、详情面板「反馈」行。11 反馈场景 + 223 backend / 58 frontend 绿 |
| 4 — Embedding 判定 | ✅ **完成 2026-07-25**（管线；准确率待回测） | schema v8（`x_embeddings` + `x_vec_labeled`）、`vectors.py` / `embedding.py` / `verdict.py`、`XVerdictBadge` + `XVerdictDetail` + 订阅页判定状态行、`scripts/x_verdict_backtest.py`。32 判定场景 + 254 backend / 64 frontend 绿；真实 DashScope 端到端 + 截图 `tmp/2026-07-25-x-phase4-verdict/`。**分类质量已回测 2026-07-27**（30 👍 / 29 👎）：正判定阈值定为 0.25（100% 精确），**负判定默认关闭**（在整个网格上等同瞎猜，成因是标签里 24/29 是文风判断）——见下方「阈值定案与负判定下线」 |
| 5 — iOS 适配 | ✅ **完成 2026-07-25** | Kit 的 `XTweet` payload 家族 + envelope 的 `feedback` + `feed` 作用域 + 反馈 API；App 的 `XCard` / `XDetailSheet` / `XFeedTimelineScreen`（For You 唯一入口）/ 判定徽标与证据。41 个新 Kit 场景（共 161）+ 256 backend 绿；模拟器走查（真实 bird 数据 + 真实判定）截图 `tmp/2026-07-25-x-phase5-ios/` |

未决问题：

1. ~~**For You 的容量策略**~~ —— 已定案（2026-07-25，见决策记录「For You 的容量策略」）。
2. ~~**作者头像**~~ —— 已定案：unavatar.io 代理（`/api/x/avatar/{handle}`，`fallback=false`），失败回落字母头像。
3. **旧 raw 的重 parse 回填工具** —— 目前只保证 raw 留底，还没有「格式漂移后按新解析器重刷」的脚本。
4. ~~**verdict 徽标的 UI 位置**~~ —— 已定案（2026-07-25）：**底栏左侧，与反馈按钮对望**。用户拍板。
5. ~~**标注量什么时候够 / 阈值定案**~~ —— ✅ **已定案 2026-07-27**，见下方「阈值定案与负判定
   下线」。一句话结论：正判定 `>=0.25` 100% 精确、负判定在整个网格上都等于瞎猜，于是
   **负判定默认关闭**（新开关 `CONDENSER_VERDICT_NEGATIVE_ENABLED=false`）。
   ⚠️ **「阈值定案」≠「判定做完」这句话现在有数据了**：负判定失效的成因正是笔记里那个「待验证
   的假设」——29 个踩里 24 个是文风判断（`promo` 11 / `engagement_farming` 10 / `ai_slop` 3 /
   `author` 1），只有 1 个 `topic`；话题 embedding 表示不了文风，只能连坐它恰好挂靠的话题。
   所以负判定要复活，靠的不是调阈值，是笔记里的通道 C（LLM 属性提取）/ D（n-gram）/ A（作者
   先验）——而这三个通道的优先级现在也由这个 reason 分布直接给出了。
6. **判定文案的语言**（实现期出现的小分歧）—— 卡片徽标用英文（"Recommended" / "Likely not for
   you"，与 `XCard` 其余文案一致），详情面板用中文（与 `ItemDetailPane` 一致）。如果觉得徽标也该
   中文化，改 `XVerdictBadge` 的 `STYLES` 即可。**iOS 沿用了同一分工**（`XCard` 的
   `XVerdictBadge` 英文、`XDetailSheet` 中文），所以要改就两端一起改。
7. **iOS 的 X 只读**（Phase 5 实现期确认）—— 订阅的增删改仍然只在 web；iOS 只读这条
   既有约定没有为 X 破例，probe 状态 / 判定闸门倒计时也只在 web 的订阅页有。

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
| **踩的理由 chip（credit assignment）** | **踩之后追问一次，四个封闭值、可跳过**：`topic` 不感兴趣 / `promo` 广告营销 / `ai_slop` AI Slop / `author` 不喜欢作者（`item_feedback.reason` 可空列，schema v9）。跳过 = 退化成原来的整条标签，零损失。up 侧暂不追问（列本身与 verdict 无关，将来要加是 UI 改动而非迁移） | 用户拍板（2026-07-26，chips 四个值由用户定）。**这是本计划最容易只看 plan 就丢掉的一条决策**，所以完整理由写在这里而不只在笔记里：一条推文只有**一个**向量，话题 / 文风 / 作者被平均成同一个点，于是 dense kNN 天生分不清「讨厌这个话题」和「讨厌这种说话方式」（笔记称之为**向量纠缠**，比信用分配更致命：down 十条 AI slop，换个话题的第十一条照样漏网；因「营销味」踩一条 LLM 话题的推则会误伤整个 LLM 邻域）。理由 chip 是这个问题**最便宜的解法——问用户**，而不是加模型：四个值一一对上笔记里规划的四个通道（`topic`→B 话题 kNN、`promo`/`ai_slop`→C/D 文风通道、`author`→A 作者先验），所以今天记下的属性将来可以按通道分派，而不是继续被平均。封闭枚举（入口 `Literal`，非法值 422）是因为自由文本没法当特征。**判定管线今天不读它**：数据先攒，通道取舍等回测 |
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

## Phase 3 — 反馈闭环 ✅ 已完成 2026-07-25（web；iOS 顺延到 Phase 5）

- ✓ `POST /api/feedback {key, verdict: "up"|"down"}` / `DELETE /api/feedback/{key}`（撤销）。
  落在 `routers/reading.py`（与 hidden 同一族：都是三元组标记），`verdict` 用 `Literal` 卡
  在入口（非法值 422）。**一条目一行**：up→down 是改正不是第二个标签，撤销即删行。
- ✓ web：X 卡片底部的 thumb up/down（**所有 X 推文均可标注**，高亮已选态，再点一次撤销），
  即使 bird 没给 metrics 也照常出现（底栏改为常驻）。详情面板加「反馈」行。
- ✓ 反馈只写 `item_feedback`，本 phase 不做任何判定：不隐藏、不改已读、不影响排序——
  有一条专门的测试盯着这件事，因为 Phase 4 之前任何「自动动作」都是在没有信任基础时越权。
- △ **状态要能回到读者眼前**，所以 envelope 加了 `feedback` 字段：timeline 走 provider 的
  `LEFT JOIN item_feedback`，收藏走 `records._saved_feedback` 的批量 join。
  **反馈刻意不进快照**——它是用户随时会改的活状态，快照只冻结推文本体。
- △ 端点是源通用的（表本来就是），但**只有 X 的 envelope 暴露 `feedback`**：别的源等它们
  自己的 UI 长出按钮时再加 join。字段「缺席」不等于「谎报 null」。
- △ 与 `hidden_items` / `read_items` 不同，反馈**不做相册展开**：标签属于用户实际判断的那个
  展示单元，而且今天只有无相册概念的 X 在写。
- △ iOS 顺延：`MessageListView.card(_:)` 还不认 X 条目（见 Phase 2 的空窗说明），没有卡片可
  挂按钮，所以 Phase 3 的 iOS 半边并进 Phase 5 一起做。

测试：`tests/test_x_feedback.py`（11 场景）+ `XFeedbackButtons.test.tsx`（5）+ `XCard.test.tsx`
新增 2 条。223 backend / 58 frontend 绿。关键场景：envelope 回传标签、切换只留一行、重复提交
幂等、撤销、关注人 feed 也可标注（聚合流里同样带标签）、**反馈不隐藏/不标已读/不产生 verdict**、
收藏项带标签且删档后仍在、非法 key/verdict 422、无凭据 401。

真机走查（本地 dev 后端 + 真实 bird 数据）：点赞 → 刷新 → 服务端状态 → 撤销、收藏视图、
详情面板、暗色 + 关注人 feed，截图与说明见 `tmp/2026-07-25-x-phase3-feedback/`。
走查中发现并修掉一个视觉 bug：`hover:text-accent-foreground` 会盖掉选中色，悬停已选中的
拇指会变黑——hover 文字色改成「仅未选中时生效」。

### Phase 3 补记 —— down-reason chips ✅ 2026-07-26（schema v9，三端齐活）

**这是一处漏做的补票**：算法讨论笔记
（`kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md`）把 chips 称为「性价比之王」、
建议进 Phase 3，并写明「`item_feedback` 需加可空 `reason` 列——落实时记得改主计划 schema」，
但那条建议只在本计划第 446 行以「算法演进方向」被引用，**没有回流进 Phase 3 的规格**，于是
按规格实现的 Phase 3 只有裸的 up/down。漏的代价是持续的：在补上之前打的每一个踩都是 bag 级
标签，将来多通道模型只能降级使用。

- **为什么要问**：一条推文只有一个向量，话题/文风/作者被平均成同一个点，所以「讨厌这种腔调」
  和「讨厌这个话题」在 dense kNN 眼里没有区别（笔记里的「向量纠缠」）。理由 chip 把成因归到
  属性上，是笔记里「信用分配」问题最便宜的解法——**问用户**，而不是加模型。
- **taxonomy（用户拍板，2026-07-26）**：`topic` 不感兴趣 / `promo` 广告营销 / `ai_slop` AI Slop
  / `author` 不喜欢作者。四个值一一对上笔记里规划的四个通道（B 话题 kNN、C/D 文风、A 作者
  先验），这也是把它做成**封闭枚举**（入口 `Literal`，非法值 422）的理由：自由文本没法当特征。
- **schema v9**：`item_feedback.reason` 可空列，shape-based `ALTER TABLE ADD COLUMN`（同 v5
  的做法）。chips 之前的老标签留 NULL——它们本来就是 bag 级的，补一个理由等于编数据。
- **「一次请求说清整条标签」**：`POST /api/feedback` 不带 reason = 没有理由，会清掉已存的那个。
  否则把「踩 + AI Slop」改正成「赞」时，旧成因会跟着跑到正样本上去。撤销连理由一起删。
- **理由可跳过**，跳过零损失（退化成原来的整条标签）——所以 UI 上它是一次追问，不是一道关卡。
- **envelope 用平级的 `feedback_reason`，不嵌进 `feedback`**：已装机的 iOS 版本把 `feedback`
  当字符串解，改成对象会让整页解码失败，而 App 是用户单独升的。
- UI：web 是卡片底栏下方展开的一行 chips（`为什么？` + 四个 + × 跳过，选中即收起，**只回应这
  一次点击**——已标注的推文滚回视野不会再问）；iOS 是原生 `confirmationDialog`（手机上一行摆
  不下四个中文标签，而系统弹层本就是「点一项 / Cancel 跳过」的形状）。已选理由只在详情面板
  回显（卡片上每条挂个 chip 太吵），web「反馈」行显示「踩 · AI Slop」，iOS 同。
- 判定管线**没动**：`verdict.py` 今天仍不读 reason（单通道 dense kNN 是 v1 baseline），
  这一步只保证数据质量，通道取舍等回测。

测试：`tests/test_x_feedback.py` +9（共 20）、`XFeedbackButtons.test.tsx` +8（共 13）、
Kit +7（共 168）。265 backend / 72 frontend / 168 Kit 绿。关键场景：跳过仍是完整标签、
chip 更新同一行、四个值全接受、改正丢弃过期理由、撤销带走理由、up 也能带理由（列是
verdict 无关的）、未知理由 422、收藏项回传理由、v9 迁移保住老标签。

走查（本地 dev 后端 + 真实数据，截图 `tmp/2026-07-26-x-feedback-reason-chips/`）：
web 走了「踩 → chips → 选 AI Slop → 落库 → 收起 → 刷新不再追问 → 详情面板显示
『踩 · AI Slop』→ 改成赞后 reason 被清空」全程；dev DB 上真实跑过 v8→v9 迁移。
iOS 侧 Kit 测试覆盖状态机，弹层渲染另行截图确认（模拟器窗口收不到合成手势，
临时把 `askingReason` 初值置 true 构建截图后已还原）。

## Phase 4 — Embedding 判定 ✅ 已完成 2026-07-25（管线；分类质量待回测）

### 实现纪要（✓ = 与计划一致，△ = 实现期调整）

- ✓ schema v8 纯新建：`x_embeddings`（向量的 storage of record，float32 BLOB + `model=name@dims`）
  + `x_vec_labeled`（vec0，只装训练集），`init_db` 里**先加载扩展再原生 SQL 建虚拟表**。
  维度变了自动 drop + 重建（`app_meta.x_vec_dims` 记着上次的值）。
- ✓ `vectors.py` 把 sqlite-vec 关在一个模块里（`setup / pack / unpack / upsert / delete /
  clear / labeled_ids / knn`），扩展不可用时全部降级为 no-op —— 不支持的宿主只丢判定，不丢应用。
- ✓ `embedding.py`：OpenAI 兼容、批 ≤10、两次退避重试、L2 normalize、按 `index` 重排。
  无 key = `available()` false = 整套 inert。
- △ **冷启动闸门提前到 embedding 之前**（计划流程里是 ② embedding → ③ 闸门）。理由：闸门关着时
  嵌入是纯浪费，一个刚装好的实例不该为了输出一堆 neutral 而花钱。同理，闸门关着时**不给 For You
  推文算 embedding**。
- △ **撤销标注不受闸门限制**：删索引不花钱，所以任何时候「你收回的标注不该还留在索引里」都成立。
  （这条是被测试逼出来的：先写的实现让闸门把删除也挡了。）
- △ **已标注的推文不再被判定**：它自己在索引里，会以距离 0 命中自己，判定结果就是标签本身——
  循环论证，且发生在唯一不需要判定的条目上。
- △ **训练集实时读表**（`item_feedback` ∪ `saved_items`），索引走**对账**而非写穿：标注端点保持
  同步（嵌入要联网），重启 / API 挂掉 / 换模型都能在下一轮自愈。
- △ `verdict_meta` 的近邻**截断到 5 条并带上作者 handle**。截断是因为这行每天写 ~1000 次；
  带 handle 是因为一串裸 tweet id 无法「解释」——而可解释性正是「只打标不隐藏」的全部依据。
- ✓ 三段阈值、save ×2 样本权重、OOD 闸门、`verdict_meta` 版本号，均按计划。
- ✓ `POST /api/sources/x/ingest` 后 kick 判定轮（For You 只在 probe 推送时才变），
  kick 失败不影响 ingest 返回——推送端点的契约是「存档收到了」。
- △ `/api/x/status` 多了 `verdict` 块（能否运行 / 闸门是否打开 / 还差几个标注 / 已判多少），
  订阅页 X 区块渲染成一行中文说明。「没有徽标」有三种完全不同的原因，只有一种是你能动手解决的。

### 决策：向量检索仍然用 sqlite-vec（2026-07-25 复议后维持原案）

动手前重新论证过一轮，结论不变，但理由比原计划更硬：

| 方案 | 传递依赖 | 数据同一性 |
|---|---|---|
| chromadb 1.5.9 | **79 个包**（`kubernetes` / `onnxruntime` / `grpcio` / 整套 opentelemetry / `uvicorn`+`uvloop`） | 另一个存储引擎、另一套文件，**无共同事务**，标签与向量可漂移且无法 join |
| 手写暴力 kNN | 0 | 靠「查询时现算」绕过漂移，等于用运行时开销换一致性 |
| **sqlite-vec 0.1.9** | **1 个包** | 同一个文件、**同一个事务** |

实测验证（`tmp/vec-smoke.py`，走 peewee 而非裸 sqlite3）：扩展在 uv 管理的 CPython 上正常加载；
peewee 的线程本地新连接会自动重载扩展；snowflake int64 作 rowid 往返无损；**vec0 与普通表同事务
回滚**——标签和向量要么一起提交要么一起回滚，结构上不可能漂移。这一条是 Chroma 给不了、暴力
方案也给不了的，也是选型的真正理由。

对「造轮子 / 可维护性」的回应：用库，但把库关进 `vectors.py` 的四个函数后面，换后端 = 重写这一个文件。

### 实测数据（`text-embedding-v4@256`，真实 API）

| 文本对 | cosine 距离 |
|---|---|
| 同主题、中英文（Rust borrow checker） | **0.18** |
| 跨主题（Rust vs crypto 推广） | **0.80** |

`CONDENSER_VERDICT_MAX_DISTANCE=0.6` 正好落在两者之间，占位值意外地合理。跨语种召回也说明
中英混杂的 For You 流不需要分语言建模。

### 真机端到端（本地 dev 后端 + 真实 DashScope）

8 条真实 For You 推文、手工标 2 👍 + 2 👎 → 真实嵌入 → vec0 kNN → verdict → UI 徽标。
截图与说明在 `tmp/2026-07-25-x-phase4-verdict/`。两点值得记下来：

- **默认阈值下 4 条全部 neutral**，其中一条拿到 score −1.00 仍未判负，因为只有 1 个 down 近邻，
  没达到「≥2 个佐证」。不对称闸门在真实数据上确实拦住了——这是设计生效，不是 bug。
- 为了验证徽标渲染路径，另跑了一组**仅供演示的阈值**（`MIN_DOWN_NEIGHBORS=1`、
  `POSITIVE_SCORE=0.10`）才凑出 1 正 1 负。**这组数字不构成任何准确率结论。**
- 4 个标注下所有近邻距离都在 0.43–0.60 之间，即「什么都不太像什么」——这正是冷启动闸门
  存在的理由，也说明 20/20 的默认下限不算保守。

### ~~遗留~~ → 阈值定案与负判定下线 ✅ 2026-07-27

标注攒够（30 👍 / 29 👎，闸门 20/20）后，管线第一次真跑：`indexed=59 dropped=0 judged=82
pruned=0`，82 条里 11 positive / 71 neutral / **0 negative**（`out_of_domain` 仅 3 条，最近邻
距离 min 0.094 / avg 0.413 / max 0.563）。随后把生产库快照到本地做留一法回测，占位常量变成了
决策：

| 侧 | 最好的一档 | 结论 |
|---|---|---|
| 正 | D0.60 / M3 / `>= 0.25` | **100% 精确**（8 次判定，coverage 13.6%），且是 0.35 那档的两倍覆盖、精确度不变 |
| 负 | 整个网格 | 最好 **55.6%** 精确，而负样本基率 **49.2%** —— 等于没有信息 |

于是 `condenser_verdict_positive_score` 定为 **0.25**，并新增
`condenser_verdict_negative_enabled`（默认 **false**，在 `score_neighbours` 里拦截负分支；
score 与近邻照常写进 `verdict_meta`，所以将来打开无需回填）。

**为什么负判定不是调参能救的**：29 个踩里 24 个是文风判断（`promo` 11 / `engagement_farming`
10 / `ai_slop` 3 / `author` 1），`topic` 只有 1 个。按 reason 拆开看召回（D0.60/M3/−0.45）：
`promo` 11 个里召回 2 个，**其余全部 0**。话题 embedding 表示不了文风，负标签只会拖累它恰好
挂靠的话题邻域——这正是笔记预言的纠缠病灶，第一次拿到了数据。

笔记要的「负样本只取 `reason IS NULL OR topic`」变体也跑了，**在这个数据量上不是解法**：只剩
4 个负样本，正判定看着 88% 精确其实是 30/34 的基率（分类器把所有东西都判正）。工具留在
`tmp/x_verdict_variants.py`（拆开正负阈值 + 按 reason 拆召回），下次回测直接复用。

### 原始设计（下文保留为实现依据）

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
- **本节的 dense kNN 定位是 v1 baseline / 回测对照组**，不是终局。它有一个**调参调不掉**的结构性缺陷（向量纠缠：话题 / 文风 / 作者挤在同一个向量里，见决策记录「踩的理由 chip」那一行），所以「把 D_MAX 和 ± 阈值定下来」只是把 baseline 标定好，不等于判定做完了。算法演进方向——多通道弱信号集成（A 作者先验 + B dense kNN + C LLM 属性提取 + D n-gram 贝叶斯 + 组合器）——见讨论笔记 `kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md`；**每个通道独立可关、独立留一法回测**，通道取舍由数据定而不是先定架构。笔记里唯一已落地的是 down-reason chips（2026-07-26，见「Phase 3 补记」），通道 A/C/D 与组合器仍在纸上。

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

## Phase 5 — iOS 完整适配 ✅ 已完成 2026-07-25

Phase 2 留下的空窗（X 条目在 iOS 聚合流里渲染成**空白行**）随本 phase 关闭。

### Kit（✓ = 与计划一致，△ = 实现期调整）

- ✓ `XTweet` payload 家族（`XMediaItem` / `XMetrics` / `XArticle` / `XQuote` /
  `XVerdict` + `XVerdictMeta` + `XVerdictNeighbor`）+ envelope 的 `x`；fixture 由
  `tmp/make_ios_fixtures.py x` 从 dev DB 生成真实 JSON（`timeline_page_x` /
  `x_shapes` 每种形态一份 / `x_record` 收藏快照）。
- △ **`feedback` 是 envelope 级字段**（`ItemFeedback`），不是 X payload 里的——表是源通用的，
  别的源长出按钮时直接接上。
- △ **`feed` 作用域贯穿 Kit**：`TimelineStore` / `NewContentChecker` / `timeline` /
  `timeline/new` 都多一个参数。计划里没预见到 iOS 也需要它——X 是第一个「一个信源多个
  feed」的源，HN 只有 `front`、TG 用 channel_id。
- △ **卡片的纯文本逻辑放在 Kit 而不是 View**（`XTweet.bodyText` 剥 RT 前缀 / 丢掉与长文
  标题重复的正文、`displayName`、`tweetURL` / `profileURL`、`photos`），这样它们进得了
  单测——分层规则本来就是「纯逻辑归 Kit」。
- △ **未知值降级而不是解码失败**：`XVerdict` / `ItemFeedback` 都有 `other`
  兜底（沿用 `ReactionCount.Kind` 的先例）。后端先长出新判定值时，旧 app 少画一个徽标，
  而不是整页 timeline 炸掉。
- ✓ `setFeedback` / `clearFeedback` + 两个 store 的乐观切换（点亮着的那一侧 = 撤销），
  失败回滚到点击前的标签。

### App

- ✓ `XCard`（+ `XQuoteCard` / `XMediaView` / `XMediaThumb` / `XAvatarView` / `XGlyph` /
  `XVerdictBadge` / `XFeedbackButtons`）与 `XDetailSheet`。
- △ **判定证据在详情里用中文展开**（打分、近邻的 handle + 距离、`model@dims`），卡片徽标
  沿用 web 的英文——与未决问题 6 的分工一致。neutral 卡片上不画、详情里写「未表态」：
  你专门点进来问「它怎么看这条」时，「没表态」本身就是答案。
- ✓ 订阅 tab 的 X 分组 → `XFeedTimelineScreen`（feed 作用域 store）。**For You 不进聚合流**
  这条在 iOS 上是服务端保证的，客户端只是没有别的入口。
- △ `ImageViewerItem` 泛化成 `ViewerPhoto`（`.telegram(cid,mid)` / `.proxied(url)`）——
  TG 媒体按消息寻址，推文媒体是原始 URL 走 `/api/preview/image`；两者都带 Bearer，
  客户端从不直连 X。
- △ `TruncatableText` 从 `MessageCard` 里解除 private，TG / X 共用同一套 8 行截断 + more。

### 测试与走查

`XSourceTests`（模型解码 12 + 卡片文本 8 + 资源 URL 2 + feed/反馈 5）+ `APIClientTests`
新增 2，共 161 Kit 场景绿，256 backend 绿。模拟器走查连本地 dev 后端（真实 bird 数据 +
真实 DashScope 判定）：For You / 关注人 feed / 订阅页 X 分组 / 判定证据 / 反馈读回 /
收藏 / 暗色，截图与说明 `tmp/2026-07-25-x-phase5-ios/`。

△ **走查手段的限制值得记下来**：本机模拟器窗口拿不到 `System Events` 句柄，合成点击
无从下手，所以「点拇指」这一下没法真点。写入路径拆成两段验证——按钮→store→API 由 Kit
行为测试盯，API→服务端→读回渲染用 app 同一个 device token curl 打标后重启 app 看渲染。
为此给 debug 深链补了 `x[/<feed>]`、`detail/x/<feed>[/<id>]`（X 条目要单独查一次网络，
因为 For You 根本不在 `reader.timeline.items` 里）和 `tab/subs/<source>`（订阅列表已经
一屏放不下）。

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
