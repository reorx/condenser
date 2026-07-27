# `engagement_farming`「钓互动」——第五个 down-reason chip

**日期**：2026-07-27
**改动**：常量级（`reason` 是可空 TEXT 列，无迁移、不动 SCHEMA_VERSION）
**上游**：`kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md`（算法归宿）、
`kb/plans/2026-07-24-x-source-local-probe.md` 的「Phase 3 补记」（chip 为什么存在）

## 起因

一条 For You 推文（`tmp/2026-07-27-engagement-farming-chip/00-source-tweet.md` 存档）：
拆解开源 agent 项目 Pi（77k star、四个工具、agent-loop.ts 792 行），论点是「不做 MCP
不是洁癖，是 context 预算」。技术内容属实且可核验，但整条推的落点是三个——评论区的
22 分钟 YouTube、作者自己的 harness repo、以及 "Save the diagram 🔖" + 个人签名口号。

用现有四个 chip 都不对：
- `topic` **错得最危险**——agent harness 内部实现恰恰是想看的话题。打了它，
  topic-kNN 的负样本邻域会被污染成「Pi / agent 实现」，以后真正想看的同类被判掉。
- `ai_slop` 不成立——有 LLM 味的句式（否定式排比、单句成段），但内容有信息量，
  不是机器水文。这个通道该留给真正的空洞。
- `promo` 勉强能用，但它和「卖东西」混在一起了。
- `author` 是人的判断，不是这一条的判断。

## 结论：加 `engagement_farming`，标签「钓互动」

X 平台操纵条款里的正式术语（不是社区黑话），指的就是这套：钩子 → FOMO →
"save this 🔖" → 正文钓在评论区（外链压推荐量）。

三条理由，第一条是决定性的：

1. **和 `promo` 正交。** clout chasing 在语义上是 promo 的子集，`promo` vs `clout`
   每次标注都要纠结——**会让人犹豫的分类法产出噪声标签**，而噪声是训练集唯一
   无法事后修复的东西。engagement farming 切的是另一个轴：卖东西（意图） vs
   钓互动（手法）。一条推可以只钓不卖，也可以只卖不钓。
2. **落在最便宜的通道上。** 钓的话术基本是词汇级的（`save this` / `🔖` /
   `link in comments` / `thread 🧵` / 结尾反问），规划中的 n-gram Bayes 通道几乎白送
   就能学会；`clout` 要推断动机，得等最贵的 LLM 属性抽取通道。
3. **超集反而是优点。** 它顺带罩住 rage bait、投票钓、giveaway。样本量是眼下真正
   卡脖子的约束（每侧 ~50 标签才够调 baseline），一个每天都会按的 chip 比一个
   一周按两次的先到达可训练量级。

代价：一条克制、无钩子、纯给自己课程导流的推抓不到——但那条本来就是 `promo`。

## 被否掉的候选

| 候选 | 否掉的理由 |
|---|---|
| `clout` | 语义上是 `promo` 的子集，标注时二选一会犹豫（见上） |
| `content_farm` | ① 组织级名词套在单条上是范畴错误——未来 LLM 通道 prompt 问 "is this a content farm?" 会去判断**账号**并对一个真人技术号答 no；② 它编码的是**质量**判断，而订阅里喜欢的论文速递 / changelog 摘要 / 周报**本质也全是二手搬运**，区别只在不吹不钓——学「搬运」的通道会把它们一起打下去；③ 这条推自己就不低质，按定义标不下去 |
| `rehash` / `secondhand` | content_farm 的 item 级正确写法，但仍是质量判断，同②ᅟ|
| `self_promo`（拆分 promo） | 最保守，不引入新概念，但丢掉「夸大 + FOMO」这一维——而那正是不适感的来源 |

## 落地

| 层 | 改动 |
|---|---|
| `condenser/db.py` | `FEEDBACK_REASONS` 加值 + 为什么不并进 promo 的注释 |
| `condenser/types.py` | `FeedbackBody.reason` 的 Literal |
| `frontend/src/lib/types.ts` / `lib/sources.ts` | 联合类型 + chip 标签「钓互动」 |
| `ios/CondenserKit/.../Models.swift` | `case engagementFarming` + `offered` + `label` |
| `scripts/x_verdict_backtest.py` | 负样本变体的说明——`engagement_farming` 是「不是话题判断」里最锋利的一个，变体该**最先**丢掉这批负样本 |

**新增两道防漂移测试**（这次真正值钱的部分）：

- 后端 `test_the_request_schema_and_the_stored_taxonomy_cannot_drift`：把 pydantic
  Literal 钉在 `db.FEEDBACK_REASONS` 上。只改一边的后果是最坏的一种——端点收下并
  **存下**一个没人会路由的标签，而标签是永久数据。
- iOS `everyReasonIsOffered`：`offered` 必须覆盖除 `.other` 外的每个 case，
  否则新值后端收得下、读者却选不到。
- web 的 chip 断言改成从 `FEEDBACK_REASONS` 派生，不再手写四个字符串。

## 遗留

- **chip 行现在换行成两行**（第五个把「不喜欢作者」挤到第二行）。`flex-wrap` 早就
  在，属于预期降级而不是溢出，视觉可接受。真要一行放下，得让 reason row 脱离
  footer 右侧那一列、占满卡片宽度——那是 `XCard` 的结构改动，不是一行 CSS。
- **2026-07-26 之前的标签 `reason` 为 NULL**，2026-07-27 之前没有 `engagement_farming`。
  训练集有两道断层，是数据的真实属性，不要补。
- 这仍然只是**记录**：没有任何东西按 reason 隐藏或排序。它等的是多通道模型。
