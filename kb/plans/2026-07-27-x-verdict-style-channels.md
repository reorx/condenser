---
created: 2026-07-27
tags:
  - plan
  - handoff
  - x-twitter
  - feedback-ranking
  - algorithm
  - recommendation
---

# X 判定 v2：文风通道（C / D）与多通道组合器

**这是一份 handoff**：接手的人只读这一篇 + 它引用的两个文件就能开工，不需要考古会话记录。

- 上游设计笔记（架构权威）：[2026-07-24-x-verdict-multi-channel-discussion.md](../notes/2026-07-24-x-verdict-multi-channel-discussion.md)
- 上游主计划（Phase 1–5 已全部完成）：[2026-07-24-x-source-local-probe.md](2026-07-24-x-source-local-probe.md)

---

## 1. 一句话背景

单通道 dense kNN（通道 B）已上线并于 2026-07-27 用真实标注回测完毕：**正判定可用（100% 精确），
负判定不可用（等同瞎猜），已默认关闭**。本计划要做的是让判负重新成为可能——不是调阈值，而是
补上能表示「文风」的通道。

## 2. 为什么判负失效（这一节决定了后面所有设计，别跳过）

回测事实（59 个标注，留一法，生产库快照）：

| 侧 | 最好一档 | 精确度 | 基率 | 结论 |
|---|---|---|---|---|
| 正 | D0.60 / M3 / `>=0.25` | **100%**（8 次） | 50.8% | 有真实信息，已上线 |
| 负 | 整个网格最好的一格 | **55.6%** | 49.2% | 没有信息，已关闭 |

按踩的理由拆召回（D0.60 / M3 / −0.45）：

| reason | 个数 | 被召回为 negative |
|---|---|---|
| `promo` | 11 | 2 |
| `engagement_farming` | 10 | 0 |
| `ai_slop` | 3 | 0 |
| `author` | 1 | 0 |
| `topic` | **1** | 0 |
| （无理由，chips 之前） | 3 | 0 |

**根因**：embedding 是按语义/话题训练的，向量编码「这条推在讲什么」。而 24/29 的踩说的是
「这条推怎么说话 / 谁说的」。于是「我讨厌这种腔调」被记成了「我讨厌这个话题」，双向都坏——
换个话题的同款营销推漏网，而你点过赞的、恰好同话题的推被判负（回测里 3 次错误判负全是这种）。

**推论（本计划的立论）**：判负要复活，需要一个**表示层能承载文风属性**的通道。这不是调参能到达
的地方；反过来，正判定不需要新通道，因为点赞的动机本来就是话题性的，和 embedding 对齐。

**副推论（数据侧的免费修复，值得同时做）**：如果用户开始多按「不感兴趣」（`topic`），通道 B 的
负向会自行恢复。所以 B 的负样本训练集将来应当**只取 `reason IS NULL OR reason='topic'`**——今天
这么做不行（只剩 4 个负样本），等 `topic` 踩攒到几十个再切。见 §7 的开关设计。

## 3. 现状清单（接手前先确认这些还成立）

代码与常量（`condenser/`）：

| 位置 | 现状 |
|---|---|
| `verdict.py` | `run_once` = 丢弃撤销 → 冷启动闸门 → 补索引 → 判定 → 清理；`score_neighbours` 是唯一打分点，负分支已被 `condenser_verdict_negative_enabled` 拦住 |
| `vectors.py` | sqlite-vec 封装（`x_vec_labeled` vec0 表），扩展不可用时全部 no-op |
| `embedding.py` | OpenAI 兼容嵌入，`CONDENSER_EMBEDDING_*`，`available()` 无 key 即 false |
| `config.py` | `positive_score=0.25`（回测定案）、`negative_enabled=False`、`max_distance=0.6`、`min_neighbors=3`、`k=15`、`min_down_neighbors=2`、冷启动 20/20、`window_hours=48`、`batch=100` |
| `db.py` | `x_labeled_samples()` = `item_feedback`(source='x') ∪ `saved_items`(source='x')，实时读表；`FEEDBACK_REASONS` = topic / promo / ai_slop / author / engagement_farming |
| schema | v9。`x_tweets` / `x_feed_items`(verdict, verdict_meta) / `x_embeddings` / `x_vec_labeled` / `item_feedback`(verdict, reason) |

生产数据（2026-07-27 晚）：标注 30 👍 / 29 👎 / 0 收藏；For You 存档 ~147 条；判定 17 正 /
71 中性 / 0 负；probe 每小时 20 条（`CONDENSER_X_HOME_COUNT=20`），只在 Mac 醒着时跑，
实际约 300–400 条/天。

⚠️ **数据量是本计划的前置条件**：通道 C/D 是统计模型，59 个标注喂不动。笔记给的量级是
**百到千**。按现在每天标 20~30 个的节奏，4~6 周能到几百。**可以先写代码、先攒属性数据，
但不要在几十个标注上宣布任何通道「有效」或「无效」**——那正是这次回测能做出结论的原因：
它做在一个已经能明确分出胜负的对比上（100% vs 基率）。

## 4. 目标架构（来自笔记，本计划落实其中的 C / D / 组合器）

```
新 For You 推文
   ├─ A 作者先验     （该作者的 up/down 计数，Beta 平滑）   ← 低优先，只有 1 个 author 踩
   ├─ B 话题 kNN     （已上线；正向可用，负向待 §7 的 reason 过滤后再议）
   ├─ C 属性通道     （LLM 抽 topics + style_flags，逐属性贝叶斯计分）  ← 第一优先
   └─ D 词面通道     （n-gram 贝叶斯，垃圾过滤血统）                    ← 第二优先
                     ↓
              组合器（v1 手调加权和 → 数据够后逻辑回归 stack）
                     ↓
        既有闸门体系原样保留：证据不足→neutral、不对称阈值、verdict_meta 可解释
```

**每个通道必须独立可关、独立可回测**——这是笔记的核心要求，也是这次能干脆关掉 B 的负向的原因。

## 5. 通道 C：LLM 属性抽取（第一优先）

### 5.1 为什么是它

24/29 的踩是文风判断，C 是唯一直接表示文风的通道。LLM 在这里**不是裁判，是特征工**：
只吐属性，不吐判断。判断仍由贝叶斯计分 + 既有闸门做出——这保证了可解释性和「标注越多越准」
的性质，也避免了「每轮 LLM judge」的成本与不可复现。

### 5.2 数据模型（schema v10，纯新增表，无迁移）

```sql
CREATE TABLE x_attributes (
    tweet_id     INTEGER PRIMARY KEY,     -- 与 x_tweets 同键
    topics       TEXT NOT NULL,           -- JSON 数组
    style_flags  TEXT NOT NULL,           -- JSON 数组，取值来自封闭 taxonomy
    model        TEXT NOT NULL,           -- 'qwen-flash@v1'：模型@taxonomy 版本
    created_at   TIMESTAMP NOT NULL
);
CREATE INDEX x_attributes_model ON x_attributes(model);
```

设计要点：

- **和 `x_embeddings` 同性质：可重建的缓存**。原文在 `x_tweets` 里，任何行都能重抽。
- `model` 字段编码 **模型 + taxonomy 版本**。taxonomy 改了 = 旧属性不可比 = 重抽而不是迁移
  （完全照抄 `embedding.model_tag` 的 `name@dims` 约定，理由相同）。
- **不做属性到标签的物化表**。计分时实时读 `item_feedback` ∪ `saved_items` 做计数——和 B 的
  训练集「实时读表」保持一致，取消标注即自动退出，无需同步代码。

### 5.3 taxonomy（先手写，别让 LLM 自由发挥）

`condenser/attributes.py` 里一个常量，**封闭集合**，非法值丢弃并计数。初版 style flags 建议
从已有的 reason chips 长出来（它们是用户亲口说过的四种毛病），再补笔记里点过名的几种：

```
promo_cta          广告/推销，带行动号召
engagement_bait    钓互动：hook + FOMO + 「save this 🔖」+ 正文钓在评论区
thread_bait        🧵 1/N 长贴钓关注
ai_slop            AI 生成腔（模板化排比、空洞总结、emoji 小标题）
listicle           「5 个你必须知道的…」
emoji_spam         emoji 轰炸
humblebrag         凡尔赛 / 成功学
outrage            愤怒钓（rage bait）
poll_bait / giveaway / crypto_shill / dropshipping ...
```

topics 用开放短语（`['llm', 'rust', '创业']`），不封闭——话题空间本来就长尾，而且 B 通道已经
覆盖了话题，C 的 topics 主要用于 `verdict_meta` 的可解释性和将来的组合器特征。

⚠️ **chips 是 C 的监督信号**：`item_feedback.reason` 直接对应 style flag（`promo`→`promo_cta`，
`ai_slop`→`ai_slop`，`engagement_farming`→`engagement_bait`/`thread_bait`，`author`→通道 A）。
一条「踩 + 广告营销」的标注说的是「**这条推的 promo 属性**该被记负分」，而不是「这条推整体
该被记负分」——这正是笔记里 credit assignment 的正身，也是 chips 当初存在的理由。计分时应当
优先按 reason 定向记账，无 reason 的踩退化为「给该推所有 style flags 平摊」。

### 5.4 抽取管线

- 新模块 `condenser/attributes.py`，结构对照 `embedding.py`：OpenAI 兼容、`CONDENSER_ATTR_*`
  配置（base_url / api_key / model / batch / enabled）、`available(settings)` 无 key 即整条通道
  inert、批量 + 重试 + 结构化输出（JSON schema / function calling，解析失败按「无属性」丢弃并计数）。
- 触发点与 embedding 完全一致：`verdict.run_once` 里，**在冷启动闸门之后**（闸门关着不花钱），
  对「窗口内未判定的 For You 推文」+「所有已标注推文（补齐历史）」抽属性。
- **成本估算先算再写**：~400 条/天 × （推文 ~100 tok + 输出 ~50 tok）。选便宜模型（qwen-flash /
  haiku 级别）时约等于噪声；但**必须有 `CONDENSER_ATTR_BATCH` 上限和 `enabled` 开关**，
  并把当轮抽取数写进日志与 `/api/x/status`，否则这是本项目第一个「按条计费且无上限」的组件。
- **先补齐已标注的 59 条**（一次性，几十次调用），否则计分没有训练数据。

### 5.5 计分

对推文的每个 style flag `f`，用平滑计数：

```
score(f) = (down_f + α) / (down_f + up_f + 2α)   → 映射到 [-1, +1]
```

α = 1（拉普拉斯/Beta 平滑，防止「只出现过一次的属性」立刻笃定）。
推文的 C 分 = 各 flag 分数的加权聚合（建议取最负的那个 flag 主导，而非平均——**一条推只要
有一处明确的营销话术就该被记负，平均会把它稀释掉**，这正是 MIL 的直觉）。
无 flag 命中 = 通道弃权（abstain），不投 0 分——**弃权和「判断为中性」必须区分**，否则组合器
会把沉默当证据。

### 5.6 需要多少标注才谈得上有效

每个 flag 至少 ~20 条正负样本才有意义。按 `promo` 11 + `engagement_farming` 10 的现状，
最快见效的两个 flag 也还差一倍。**先上抽取、先攒数据，计分通道 default off。**

## 6. 通道 D：n-gram 贝叶斯（第二优先）

- 笔记的判断：C 是 D 的语义化版本，**未必都要**。但 `engagement_farming`（10 个踩）几乎是纯
  词面模式（「save this」「a thread 🧵」「1/」「你绝对不知道」），D 可能不必等 C 就有收益，
  而且**零 API 成本**。
- 实现：不建表。每轮判定前从 `x_tweets.text` 现算已标注推文的 token 计数，缓存在
  `VerdictManager` 里（几百条标注 = 毫秒级）。表化等到标注上千再说。
- 分词：中英混杂。latin 用 unigram + bigram（小写、去 URL/@/#），CJK 用字符 bigram。
  停用词表要小而明确——**别引 jieba 之类的重依赖**，本项目的依赖洁癖是选 sqlite-vec 的同一个
  理由（见主计划的选型对比表）。
- 计分：朴素贝叶斯对数几率，取 top-k 最有区分度的 token 求和，再挤压到 [-1, +1]；命中 token
  数低于阈值 = 弃权。`verdict_meta` 里存最有贡献的几个 token——**这是 D 相对 C 的最大优势：
  它能直接告诉你「因为这条推里有 "save this 🔖"」**。

## 7. 组合器与开关

- 新增 `CONDENSER_VERDICT_CHANNELS=b`（逗号分隔，默认只有 b）。每个通道返回
  `(score, confidence) | abstain`；组合器只对未弃权的通道加权求和，权重先手调
  （建议初值 B 1.0 / C 1.0 / D 0.5），数据够后换逻辑回归 stack（4 个通道分作特征，标注作监督）。
- **既有闸门原样保留**：OOD、`min_neighbors`、不对称阈值、`min_down_neighbors`、
  `negative_enabled`。判负重新打开的条件写死在文档里（见 §9），不许「看着差不多就开」。
- **通道 B 的负样本过滤开关**：`CONDENSER_VERDICT_B_TOPIC_ONLY_NEGATIVES`（默认 false）。
  打开后 B 的负样本只取 `reason IS NULL OR reason='topic'`。今天打开只剩 4 个负样本
  （回测已验证：会退化成「全判正」的分类器，88% 精确度纯属基率），**等 `topic` 踩到 ~30 个
  再回测这个开关**。
- `verdict_meta` 升级：从「像你踩过的 3 条」变成
  `{"channels": {"b": {...}, "c": {"flags": [["engagement_bait", -0.8]]}, "d": {"tokens": [...]}}}`。
  这是 UI 上「为什么」那一栏的数据源，web/iOS 的 `XVerdictDetail` 需要相应扩展。

## 8. 回测框架（先扩这个，再写通道）

**这是本计划里最先该做的事**：没有它，任何通道的取舍都是拍脑袋。

现有 `scripts/x_verdict_backtest.py` 只会：留一法 + 网格（正负阈值绑在一起）+ 只测 B。
`tmp/x_verdict_variants.py`（本次会话产出）已经补了：正负阈值解耦、按 reason 拆召回、
负样本集变体。**把后者合并进前者**，并加上：

- `--channels b,c,d` 选通道与组合权重；
- 每通道单独报告 + 组合报告（同一批 fold，可直接比较）；
- **弃权率**单列（一个总弃权的通道在「精确度」上永远好看）；
- **基率**打印在每张表旁边——这次判负失效正是靠「55.6% vs 49.2%」看出来的，没有基率对照
  就会把它当成「还行」；
- 读数顺序固定：coverage → negative precision → positive precision（脚本 docstring 已写明）。

跑法（**必须对生产库副本跑**，sweep 每折都会砸掉重建 KNN 索引）：

```bash
ssh -p 1122 root@<hh-hk-01> 'sqlite3 /opt/apps/condenser/data/condenser.db ".backup /tmp/snap.db"'
scp -P 1122 root@<hh-hk-01>:/tmp/snap.db tmp/prod-snapshot.db
CONDENSER_DB_PATH=tmp/prod-snapshot.db uv run python scripts/x_verdict_backtest.py --sweep
```

## 9. 判负重新上线的门槛（写死，不许现场放宽）

留一法回测中，负判定同时满足才允许把 `CONDENSER_VERDICT_NEGATIVE_ENABLED` 改回 true：

1. negative precision **≥ 85%**，且
2. 负判定次数 **≥ 15**（样本量太小的高精确度没有意义），且
3. 该精确度**显著高于基率**（负样本占比），且
4. 错误的负判定里**没有一条是用户收藏过的**（这是最贵的错误类型）。

   > **2026-07-28 定义澄清**（原文写的是「点过赞或收藏」，在留一法里无法按字面满足：
   > 回测集全是标注过的样本，所以每个错误的负判定按定义就是一条点过赞的推，
   > 那样第 4 条等价于要求 100% 精确度、前三条全成多余）。**采用的读法：只禁收藏过的**
   > —— 收藏是权重 ×2 的强正样本，把它判负是最贵的错误；点过赞的误判由第 1~3 条的
   > 精确度门槛约束。回测脚本已自动检查这一条（`summarize` 只给同时满足
   > ≥85% / ≥15 次 / 零收藏误判的负操作点打星）。⚠️ 注意目前收藏数为 0，所以这条今天
   > 自动成立，它约束的是未来 —— 见 §13.2。

即便全部满足，**也只开徽标，不开折叠/隐藏**——「先攒信任再放权」是主计划的既有决策，
本计划不推翻它。要开隐藏，另起一轮观察期并再次回测。

## 10. 实施顺序（每步独立可交付、可回滚）

| 步 | 内容 | 依赖 | 默认状态 |
|---|---|---|---|
| 0 | ✅ **已完成 2026-07-27** 回测框架扩展（§8） | 无 | —— |
| 1 | ✅ **已完成 2026-07-27** 通道 D（n-gram），含回测报告 | 0 | off |
| 2 | ✅ **已完成 2026-07-28** 属性抽取管线 + taxonomy + `x_attributes`（schema v10），补齐已标注推文 | 无 | 抽取 on、计分未接 |
| 3 | 通道 C 计分 + reason 定向记账，含回测报告 | 2 | off |
| 4 | 组合器 + `verdict_meta` 升级 + web/iOS 证据面板扩展 | 1,3 | 权重手调 |
| 5 | 按 §9 的门槛决定是否重开判负；同时回测 B 的 `topic_only_negatives` 开关 | 4 + 足够标注 | —— |
| 6 | 通道 A（作者先验），近零成本，可随时插队 | 无 | off |

**D 排在 C 前面是刻意的**：零成本、零依赖、能立刻拿到一张回测报告，用来验证扩展后的回测框架
本身是对的；C 涉及外部 API 与费用，值得在框架被验证过之后再接。

## 10.1 步骤 0 / 1 实施记录（2026-07-27）

**步骤 0**：`scripts/x_verdict_backtest.py` 重写为「通道 × 设置格 × 阈值」三层，
`tmp/x_verdict_variants.py` 已并入（正负阈值解耦、按 reason 拆召回、`--negatives topic`
变体）。新增：`--channels b,d`（同一批 fold）、组合报告、弃权率单列、每张表旁打印基率、
结尾按精确度排序的操作点汇总（自动给够到 §9 门槛的负操作点打星）。性能上把「取证据」和
「按设置打分」分开，sweep 只跑一遍贵的部分。
**验收标准是复现旧数字**：通道 B 的 13.6% coverage / 100% 正精确度（8 次）/ promo 召回
2 of 11、其余全 0 —— 全部一致。

`verdict.score_neighbours` 拆成 `topic_score`（投票，返回 `ChannelScore`）+ `classify`
（阈值），新增 `condenser/channels.py`（`ChannelScore` + `combine`，弃权是 `None` 而不是 0.0）。
回测的通道包的是**生产代码本身**，不是复制品。

**步骤 1**：`condenser/ngram.py` + 23 个行为测试。**前三版都是基率**，每一版错法不同，值得记住：

| 版本 | 结果 |
|---|---|
| top-k 对数几率**求和** | 78% 都判负、54.3% 精确度（基率 49.2%）；**没有一条赞过的推为正** —— 求和随长度增长，而踩过的推平均 30.8 个有效 token，赞过的只有 15.3 |
| 改**均值** + `min_weight` 下限 | 69.7%，但整条尺度沉在零下（up 最高才 -0.05） |
| 再按 **token** 中心化 | 尺度对了、**排序毁了**（正精确度 36.4%）—— 偏移改变了「谁算最强证据」 |
| 改为对**分数**中心化，偏移用留一法在 fit 时测 | up 中位数 +0.07 / down -0.31；`neg <= -0.45` → **86.7% / 15 次** |

翻案靠的是换指标：`tmp/x_ngram_variants.py` 用 **AUC** 一测，所有变体都在 0.78–0.85 ——
信息一直在，坏的只是标定。「阈值上的精确度」同时在回答「排序好不好」和「尺度对不对」，
于是两个都没回答。通道 D 的**正向**也可用（`top5 |w|0.0` 下 100% / 9–10 次），
这不在预期内（原以为它只做文风判负）。

**没有任何东西上生产**：`negative_enabled` 仍是 false，判定仍然只跑通道 B，D 只在回测里
可达（按计划，接线是第 4 步）。除计划顺序外还有两个理由：

1. 那个 86.7% 是从 **88 个负操作点**里挑出来的，而挑选和评分用的是同一批 59 条标注
   （选择偏差；15 次判定上 86.7% 的 95% 区间大约是 60–98%）。
2. ⚠️ **§9 的第 4 条在留一法回测里无法满足**：回测集全是标注过的样本，所以「错误的负判定」
   按定义就是「用户点过赞的推」。最严读法 = 要求 100% 精确度（那前三条就多余了）；
   大概率的本意是「不许有**收藏**过的」。**这条需要先定义清楚，否则谁都没法宣称门槛达标。**

## 10.2 步骤 2 实施记录（2026-07-28）

`condenser/attributes.py` + schema v10 的 `x_attributes` + `verdict.run_once` 里的
`_describe` + `/api/x/status` 的 `attributes` 块，16 个行为测试（注入假抽取器，不联网）。

与计划的三处偏差，都是为了「部署本身不会开始花钱」：

1. **独立的 `CONDENSER_ATTR_API_KEY`，不回退到 embedding 的 key**。同一家 DashScope，
   本可以复用，但那样一部署就自动开跑。现在设 key 这个动作**就是**开关。
2. **一条推一个请求**，不做批量 prompt。批量省的那点开销换来一整类静默错位 bug
   （5 条推回 4 个答案，缺口之后的属性全挂错推）。并发度补延迟。
3. **抽取排在判定之后**。属性目前不参与任何打分，凭什么让一个慢的/挂掉的 provider
   拖住用户真正会看到的判定。

其他要点：先抽**已标注**的推（那是通道 C 的训练数据，且是有限存量，未标注的推源源不断）；
taxonomy 是封闭集，且在**解析**和**写库**两处都校验（`attributes.clean`），
表里不可能出现没人能打分的 flag；答案读不懂就丢掉、下轮再来，不存猜测。
模型选 `qwen-flash`（$0.05/$0.4 每百万 token，约 400 条/天 ≈ **$0.01/天**）。

**真实 API 已验证**（`tmp/x_attr_smoke.py`，生产快照，正负各 6 条，只读不写库；
输出存档在 `tmp/2026-07-28-x-verdict-v2-steps012/attr-smoke-balanced.txt`）：
**12/12 可解析**，0 条读不懂。关键是分布，不是能不能跑：

| | 拿到 `promo_cta` |
|---|---|
| 踩过的 6 条 | **6/6** |
| 赞过的 6 条 | **2/6** —— 分别是「推荐一个刚上 YC 的服务」和「我们开源了 X」 |

这两条误伤恰恰**验证了通道 C 的设计**：flag 本身不代表好坏。用户确实喜欢某些形式上是
推广的推（熟人的新品、开源发布），所以第 3 步必须按 flag 的**标注统计**打分
（这里 promo_cta 是 6:2 偏负），而不能把任何 flag 当成绝对负面。
噪声也有：`listicle` 打在了一条没有清单的售票推上，`humblebrag` 打在了一条产品介绍上
—— 便宜模型的正常水平，正好由平滑计数吸收。

## 11. 开发约定（本项目的，别踩）

- **BDD 先行**：新功能先写行为测试再实现（`tests/test_x_verdict.py` 是既有范例，
  35+ 个场景，`FakeEmbedder` 模式可照抄给 LLM 抽取器——测试绝不联网）。
- 低层可复用函数**不写 try/except**，错误只在顶层处理。
- 扩展列/新表遵循「可重建的缓存」原则：能重算的东西不做迁移，改版本号重抽。
- 任何按条计费的组件必须有 `enabled` 开关、批量上限、以及 `/api/x/status` 上的可见计数。
- 提交信息用中文，说清「为什么」而不只是「改了什么」（见 `git log` 近几条的风格）。

## 12. 本次会话留下的资产

| 文件 | 用途 |
|---|---|
| `tmp/x_verdict_variants.py` | ~~解耦正负阈值 + 按 reason 拆召回的回测变体~~ 已并入 `scripts/x_verdict_backtest.py`（2026-07-27），保留作参考 |
| `tmp/x_ngram_variants.py` | 通道 D 的估计量选型：按 **AUC** 比较 df/mnb 加权 × sum/mean/max 聚合 × 门槛。换估计量时先跑这个，别看阈值精确度 |
| `tmp/x_ngram_diagnose.py` | 通道 D 的留一法分数分布（分类别的分位数）+ 判错最狠的赞过的推及其证据词。标定跑偏时先看这个 |
| `tmp/check_ngram.py` | 玩具语料上的通道 D 手感检查（分数、证据词、有无标定的对照） |
| `tmp/x_prod_labels.sh` / `x_prod_gate.sh` / `x_prod_verdicts.sh` / `x_prod_unread.sh` | 生产库只读快照查询（标注量、闸门时序、判定分布、未读积压） |
| `tmp/x_prod_rejudge.sh` | 清空窗口内 verdict 让下一轮重判（换阈值后用；向量已缓存，不重复付费） |
| `tmp/x_probe_burst.sh` | 连跑 N 轮 probe 灌数据（`bash tmp/x_probe_burst.sh 6 20`） |
| `tmp/x_status.sh` | 用 probe 的 device token 读生产 `/api/x/status` 的判定块 |
| `tmp/prod-snapshot.db` | 2026-07-27 的生产库快照（回测基准） |

## 13. 遗留问题 / 待定

1. **标注量是唯一的硬约束**。C/D 都是统计模型，几十个标注做不出结论。中间期唯一能做的事就是
   继续标 + 让 chips 覆盖率提高。
2. **正样本仍然全部来自 👍，收藏为 0**。收藏是权重 ×2 的强正样本，目前完全没被使用——
   值得在 UI 上想想为什么没人按（可能只是「收藏」在读的语境里没有动机）。
3. **`topic` 踩只有 1 个**。这不只是 B 通道的问题：它意味着当前的标注体系里，「话题不感兴趣」
   这个最自然的负反馈几乎没被表达。是 chip 排序问题、还是 For You 的内容本来就不是话题不对味
   而是质量不行？值得看一眼实际数据再决定要不要动 UI。
4. **通道 A 的价值存疑**：只有 1 个 `author` 踩。但作者先验也可以不依赖 chip——直接用「该作者
   历史 up/down 计数」，这在关注账号 feed 上可能比 For You 更有用。
5. **多语言**：实测跨语种同话题距离 0.18，B 通道不需要分语言建模；但 D 的 n-gram 明确需要
   （中英混杂），C 的 LLM 天然不需要。
