---
created: 2026-07-28
tags:
  - x-twitter
  - feedback-ranking
  - algorithm
  - recommendation
  - backtest
  - llm
---

# 判定 v2 步骤 0–3：回测框架重组、通道 D（n-gram）、LLM 属性抽取、通道 C 计分

## 概要

按 [判定 v2 计划](../plans/2026-07-27-x-verdict-style-channels.md) 推进，一次做完 6 步中的
前 4 步（0/1/2/3）。背景是 2026-07-27 的结论：单通道 dense kNN 的**正判定可用（100% 精确）、
负判定等同瞎猜（55.6% vs 49.2% 基率）已默认关闭**，而根因是 24/29 的踩说的是「怎么说话」
而不是「讲什么」—— 话题 embedding 结构上表示不了文风。本次补的就是能承载文风的通道。

**步骤 0** 把 `scripts/x_verdict_backtest.py` 重组为「通道 × 设置格 × 阈值」三层，
并入了原先散在 `tmp/` 的变体脚本；验收标准是**复现旧数字**（通道 B 的 13.6% coverage /
100% 正精确度 8 次 / promo 召回 2-of-11），一字不差。为此把 `verdict.score_neighbours`
拆成 `topic_score`（投票）+ `classify`（阈值），并新增 `condenser/channels.py` 作为各通道的
共同词汇 —— 回测包的是生产代码本身，不是复制品。

**步骤 1** 的通道 D（n-gram 贝叶斯）**前三版都停在基率上**，每版错法不同：求和给长度打分
（踩过的推平均 30.8 个有效 token vs 赞过的 15.3，于是没有一条赞过的推为正）→ 改均值后整条
尺度沉在零下 → 按 token 中心化又把排序毁掉（正精确度 36.4%）。翻案靠**换指标**：用 AUC 一测，
所有变体都在 0.78–0.85，说明信息一直在、坏的只是标定。终版（滤弱证据 → 取均值 → 用留一法
测出的语料零点整体平移）在 `neg <= -0.45` 上 **86.7% / 15 次**。

**步骤 2** 落地 LLM 属性抽取（schema v10 的 `x_attributes` + `condenser/attributes.py`），
用 DashScope 的 `qwen-flash`（约 $0.01/天）。真实 API 验证 12/12 可解析，且分布有区分度：
踩过的 6 条全部拿到 `promo_cta`，赞过的只有 2 条 —— 那 2 条「误伤」（推荐 YC 新品、开源发布）
恰好证明 flag 本身不代表好坏，必须按标注统计打分。

**步骤 3** 的通道 C 计分在 `neg <= -0.25` 上 **80.8% / 26 次 / 覆盖 44.1%**（基率 49.2%），
是目前负向覆盖最广的一档，但实际上是个 `promo_cta` 检测器。过程中有**两条设计被真实数据推翻**
（详见「注意事项」）。

**生产没有任何行为变化**：判负仍关闭，判定仍只跑通道 B，C/D 只在回测里可达（接线是第 4 步）。
后端测试 302 → **337 绿**（新增 52 个行为测试）。

## 修改的文件

| 文件 | 改动 |
|---|---|
| `condenser/channels.py` | **新增**。`ChannelScore`（score / confidence / corroborated / meta）+ `combine`，各通道的共同词汇。弃权是 `None` 而非 0.0 |
| `condenser/ngram.py` | **新增**。通道 D：分词（去 URL/@、保留 hashtag 词、latin unigram+bigram、CJK 字符 bigram、emoji 成词）、`fit` / `contributions` / `score`，以及留一法测出的语料零点 `offset` |
| `condenser/attributes.py` | **新增**。通道 C 的抽取（OpenAI 兼容、封闭 taxonomy、`model@taxonomy` 身份、`clean` 双重校验）+ 计分（`REASON_FLAGS` 定向记账、`fit_flags` / `score_flags`） |
| `condenser/verdict.py` | `score_neighbours` 拆为 `topic_score` + `classify`；新增 `_describe` 抽取步骤（排在判定之后）、`Extractor` 注入点、`RunResult.attributed`、status 的 `attributes` 块 |
| `condenser/db.py` | SCHEMA_VERSION 9 → **10**，新增 `XAttribute` 表 + `x_attribute_ids` / `x_attributes_for` / `x_attribute_count` / `upsert_x_attributes` / `x_describable_rows`（已标注优先） |
| `condenser/config.py` | 新增 `CONDENSER_ATTR_*`（6 个）与 `condenser_verdict_c_min_observations`、`condenser_verdict_d_*`（5 个） |
| `scripts/x_verdict_backtest.py` | 重写：通道抽象、`--channels b,c,d`、`--negatives topic`、组合报告、弃权率、基率、按精确度排序并自动检查 §9 门槛的操作点汇总 |
| `.env.example` | 属性抽取一节（强调它需要**独立的 key**，不设 key 就完全不花钱） |
| `tests/test_x_verdict_channels.py` | **新增** 23 个：通道 D 行为 + 组合器 |
| `tests/test_x_attributes.py` | **新增** 16 个：抽取的花钱闸门、不信任模型、schema v10、status |
| `tests/test_x_verdict_channel_c.py` | **新增** 13 个：定向记账、MIL 聚合、弃权、证据链 |
| `tests/test_hn.py` / `tests/test_x_feedback.py` | schema 版本断言跟到 v10（feedback 那条改成 `>= 9`，因为它测的是迁移不是当前版本） |
| `AGENTS.md` | 新增 3 个模块行、schema v10 段、判定 v2 步骤 0–3 的状态段 |
| `kb/plans/2026-07-27-x-verdict-style-channels.md` | 步骤 0–3 标记完成，新增 §10.1/§10.2/§10.3 实施记录，§9 第 4 条的定义澄清 |

`tmp/` 下的一次性脚本（都是只读或只写快照库）：`x_ngram_variants.py`（AUC 选型）、
`x_ngram_diagnose.py`（分数分布）、`x_flag_stats.py`（每 flag 计数）、
`x_flag_drivers.py`（每条标注的驱动 flag）、`x_attr_smoke.py`、`x_attr_backfill.py`、
`check_ngram.py`。验证产物存档在 `tmp/2026-07-28-x-verdict-v2-steps012/`。

## 注意事项

### 换指标，而不是换参数

通道 D 卡在基率上时，连试三版都没突破。真正解决问题的是**换一个能分离两个问题的指标**：
「阈值上的精确度」同时在回答「排序好不好」和「尺度对不对」，于是两个都没回答。
AUC 只回答前者 —— 一测 0.78–0.85，立刻知道该修标定而不是换模型。
**任何分类器调不动的时候，先用一个 threshold-free 的指标确认信息量。**

### 两条被真实数据推翻的设计（都是先写对了理由才改的）

1. **「chip 指控不到就谁都不记账」是错的**。赞永远全额记到每个 flag（赞没有 chip，
   也不可能有），踩却只在 chip 对得上时才记 —— 于是 chip 够不着的 flag 只进不出。
   实测 `humblebrag` 出现在 **7 条踩过的推**上却拿到 **+0.600**，模型学到了
   「凡尔赛是个好兆头」。改成回退分摊后 +0.043。
2. **「薄证据叫得响」是我对负向尾部的错误诊断**。加收缩之前先写了这个理由，
   查驱动 flag（`tmp/x_flag_drivers.py`）后发现：全库最负的 5 条**全是赞过的 promo 推** ——
   抽掉一条赞过的 promo 推，`promo_cta` 就只剩 4 条赞，比率恰好在「它判错的那一折」变得更负。
   这是留一法方差，打分规则够不着。**收缩保留了，但理由改成真正成立的那条。**

教训相同：**改动前先测出因果，别用一个听起来合理的解释去证成一个改动**；
合成语料复现不了的现象（本次试了三次），它的证据就只能是真实数据 + 文档里的实测数字。

### 花钱组件的四道围栏

属性抽取是本项目第一个按条计费的组件。围了四道：`enabled` 开关、每轮硬上限
（`condenser_attr_batch`）、`/api/x/status` 上的可见计数，以及**独立的 API key、
不回退到 embedding 的** —— 同一家 DashScope 本可复用，但那样一部署就自动开跑；
现在「设 key」这个动作**就是**开关。抽取还排在判定之后、冷启动闸门之内。

### 一条推一个请求，不做批量 prompt

批量省的那点开销换来一整类静默错位 bug（5 条推回 4 个答案，缺口之后的属性全挂错推）。
并发度补延迟即可。

### 回测要包生产代码，不能复制一份

`TopicChannel` 调 `verdict.topic_score`、`AttributeChannel` 调 `attributes.score_flags`。
另外把「取证据」和「按设置打分」分开，sweep 只跑一遍贵的部分（59 折 × 1 遍，
而不是 59 × 网格数）。

## 遗留问题

1. **组合器不能直接取均值（第 4 步的前置问题）**：各通道尺度不可比 —— C 的实际范围约
   [-0.4, +0.1]，B/D 是 [-1, +1]。当前加权均值把利的通道稀释了，b+c+d 组合在 `pos>=0.25`
   上 100%/7 次，**还不如 B 单独的 100%/8 次**，负向一次都不敢开口。
   需要每通道校准（把分布拉到同一尺度）或改用投票。
2. **通道 C 目前实际是 `promo_cta` 检测器**：26 次判定全由这一个 flag 驱动（18 次观测），
   其余 flag 观测量都不到 3。要更多标注才能长出第二个可用 flag。
3. **chip 与抽取器对不齐**：`promo` 11/11，`engagement_farming` 4/10，`ai_slop` **0/3**。
   reader 说的「AI 味」和 qwen-flash 说的 `ai_slop` 不是一回事 —— 下一轮该改 taxonomy 或 prompt。
4. **选择偏差还在**：通道 D 的 86.7% 是从 88 个负操作点里挑的，评分用的又是同一批 59 条标注
   （15 次判定上的 95% 区间约 60–98%）。真要重开判负，得留出从不参与调参的留出集。
5. **`.env` 里已写入 `CONDENSER_ATTR_API_KEY`**（复用 DashScope key），本地 dev 后端跑起来
   就会开始抽属性；**生产未部署、未设 key**，暂不花钱。
6. **步骤 4（组合器 + 接线）、5（判负门槛复核）、6（通道 A 作者先验）未开始。**

## 相关文档

- [X 判定 v2：文风通道（C/D）与多通道组合器](../plans/2026-07-27-x-verdict-style-channels.md) —
  本次 session 依此计划实施，并更新了步骤 0–3 的完成状态、§10.1–§10.3 实施记录与 §9 定义澄清
- [多通道判定设计讨论](../notes/2026-07-24-x-verdict-multi-channel-discussion.md) —
  架构权威，本次实现的通道 C/D 出自这里
- [engagement_farming chip 的取舍](../notes/2026-07-27-engagement-farming-chip.md) —
  参考：通道 C 的 taxonomy 从 chip 长出来，`humblebrag` 归到 `engagement_farming` 依据此文的划线
- [X 源本地 probe 主计划](../plans/2026-07-24-x-source-local-probe.md) — 上游主计划（Phase 1–5 已完成）
