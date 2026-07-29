---
created: 2026-07-29
tags:
  - x-verdict
  - channel-c
  - attributes
  - qwen
  - credit-assignment
  - production-verification
---

# 通道 C：记账对称化 + 抽取器换代（qwen3.7-flash@v2），以及两次「文档说的不是真的」

## 概要

起点是两个纯解释性的问题：`promo_cta` 和 `promo` chip 有什么区别，以及 qwen-flash 到底
对每条推做了什么判断。答第一个问题时查出一个缺陷：`fit_flags` 把踩票**只**记给 chip
指认的 flag（这是设计），却把赞票**足额**记给推上的每一个 flag。这是单向的——chip 很少
够得着的 flag 只会攒正分、永远不掉分。104 条真实标注上，`ai_slop` 骑在 6 条被踩的推上
拿到 **+0.429**，`emoji_spam` 1 赞 6 踩拿到 **+0.200**；后者更彻底，它不在任何 chip 的
指控列表里，而 `REASON_FLAGS` 的测试只 pin 了 chip 一侧，所以这个洞测不出来。

用户拍板四件事：`emoji_spam` 归入 `engagement_farming`、记账规则用精确率数据定、改
`ai_slop` 的 prompt 定义、更新 AGENTS.md；外加把模型升级到 qwen3.7-flash。

**记账规则的测量给出了否定性结论。** 四种规则（directed / down-residue / symmetric-up /
undirected）跑完整留一验证后，条件的是**同一批 48 条推、每一条的驱动 flag 都是
`promo_cta`**——规则只改刻度，阈值网格跟着平移，精确率 79.6~81.2% 分不出高下。于是改按
机制定：**credit follows attribution，两侧一致**，不指认任何东西的标签一律均摊，而赞票
永远属于这一类。

**真正的病灶在上游。** 那 48 条里有 9 条是读者点赞或收藏的、全带 `promo_cta`——这是抽取
问题，记账规则够不着。进一步发现 `system_prompt()` **一直只发 flag 名字**：taxonomy 的
含义写在 Python 注释里，从未离开进程，`ai_slop` 是以一个裸词发给模型的。于是新增
`FLAG_GUIDE` 让定义随名字一起发出，`TAXONOMY_VERSION` 升 v2，模型换 qwen3.7-flash。

在快照副本上用真实调用重抽 104 条标签集，效果显著：

| | v1（qwen-flash，裸名字） | v2（qwen3.7-flash + 定义） |
|---|---|---|
| 带 flag 的推 | 60 / 104 | 30 / 104 |
| `promo_cta` 赞/踩 | 9 / 39 | **2 / 22** |
| 负面精确率 | 81.2%（48 次） | **91.7%（24 次）** |
| 误判收藏项 | 2 | **1** |
| `ai_slop` chip 对齐 | 0 / 3 | 1 / 3 |

覆盖率减半，但失效模式基本消除。§9 门槛 4 条达成 3 条，仍有 1 条收藏被判负，所以
`condenser_verdict_c_negative_enabled` 保持 false，C 继续做影子通道。402 后端测试全绿，
提交为 `3923dff`。

本次 session 还两次撞上「文档说的不是真的」，都已就地修正，详见「注意事项」。

## 修改的文件

| 文件 | 改动 |
|---|---|
| `condenser/attributes.py` | 新增 `FLAG_GUIDE`（每个 flag 的定义，随名字发进 prompt），`STYLE_FLAGS` 改为由它派生；`TAXONOMY_VERSION` v1 → v2；`REASON_FLAGS['engagement_farming']` 加入 `emoji_spam`；`fit_flags` 的赞票改为按 flag 数均摊；`system_prompt()` 渲染 `- flag: 定义` |
| `condenser/config.py` | `condenser_attr_model` → `qwen3.7-flash`；`condenser_verdict_c_min_observations` 一度降到 4 又放回 6（注释记下了往返的完整理由） |
| `tests/test_x_verdict_channel_c.py` | fixture 换用 `promo_cta` 作无辜旁观者（`emoji_spam` 不再是了）；新增赞票均摊测试；新增 **flag 侧**穷尽性测试 |
| `tests/test_x_attributes.py` | 新增「prompt 必须定义每个 flag」测试；taxonomy 测试的 monkeypatch 值改为不与真实版本冲突 |
| `.env.example` | 模型示例值更新，补充「换模型会触发重抽」的说明 |
| `AGENTS.md` | 划掉过期的生产状态断言并补实测方法；修正错误的「部署是手动的」说法；`attributes.py` 行补充 `FLAG_GUIDE` 与两侧一致的记账规则；新增「判定 v2 步骤 5c」段落 |
| `tmp/2026-07-29-channel-c-credit-extraction/` | 产物归档：v2 数据库副本、backtest、flag 统计、四规则对比 |

新增的只读分析脚本（`tmp/`）：`x_attr_show.py`（抽取结果 vs chip 对照）、`x_attr_credit.py`
（记账归属）、`x_attr_credit_variants.py`（四种规则的 flag 符号对比）、
`x_credit_rule_backtest.py`（用真实折叠机制跑四种规则）、`x_credit_rule_overlap.py`
（条件集合重合度）。

## 注意事项

- **「用数据定」可能得到否定性答案，这也是结论。** 四种记账规则在精确率上完全无法区分，
  因为 `promo_cta` 支配了每一条判定。这时候不该硬凑一个数字排名，而应换判据（机制正确性），
  并把「数据无法区分」如实汇报。最优点表会掩盖这一点——必须看完整阈值曲线和**条件集合的
  重合度**才能发现「48 条完全一样」。
- **闭集 taxonomy 只有把定义一起发出去才算闭。** 常量里的注释是给人看的，模型看不到。
  `ai_slop` 0/3 的对不齐全部源于此。现在有测试 pin「prompt 必须包含每个 flag 的定义」。
- **双向 pin 你的映射表。** `REASON_FLAGS` 的旧测试只断言「每个 chip 都有条目」，
  `emoji_spam` 从 flag 一侧漏掉，且因为赞票足额记分而只涨不跌。任何 A↔B 映射都应两侧都 pin。
- **不对称的记账会单向漂移，且不会随样本增多自愈。** 一侧足额、另一侧定向，等价于给
  「够不着的一方」发免费正分。规则应表述为「credit follows attribution」而非分别描述两侧。
- **给安全闸门的改动，如果测不出差别，就该回到保守值。** `min_observations` 6→4 在 v1 下
  有理由（均摊让 `thread_bait` 掉出门槛），v2 重抽后完全无效，于是放回 6：`score_flags`
  取最负 flag，刚过闸门的瘦 flag 能单独决定一条推。
- **生产状态必须实测，AGENTS.md 已经两次骗人。** 一次是「schema v9 / pre-step-0 代码」
  （实际 v10、shadow c,d 已上线）——错在更早的段落没划掉、而更晚的段落已记录部署；一次是
  我自己写下的「部署是手动的」（实际 push master 即自动部署）。前者的教训是**发现过期
  就当场划掉**，后者的教训是**别把 deploy workspace 的旧注释当权威**，`.github/workflows/`
  才是。
- **多 session 并行改同一棵工作树时，`git add -A` 会捞到对方的半成品。** 本次
  `876c5f4`（通道 A）把本 session 的 `config.py` 和 `AGENTS.md` 一起提交了，却没带
  `attributes.py` 和测试，导致 master 一度「文档和配置声称、实现不存在」。提交前先用
  `git status` 对照 session 起点的快照，只 add 自己动过的文件。
- **backtest 的一个坑**：`scripts/x_verdict_backtest.py` 的 `report()` 在**非 `--sweep`**
  模式下用的是**全局** `condenser_verdict_negative_score`，不是通道自己的
  `condenser_verdict_c_negative_score`。看单通道真实操作点必须带 `--sweep`。

## 遗留问题

- **仍有 1 条收藏被判负**，§9 条件 4 未达成，所以 C 的负面侧不能准入。只能靠更多标注或
  更准的抽取。
- **C 实质上仍只是个 `promo_cta` 探测器**（23.0 观测），其余 flag 全在 1~3，阈值在
  −0.25…−0.45 之间完全不敏感；**正面侧从未开过一次口**。
- **`min_observations` 待复核**：现值 6 在 v2 下与 4 等价，等第二个 flag 攒起真实观测量后
  需要重新用数据定。注意均摊之后单位变小，6 现在要求的真实出现次数比改动前更多。
- **未部署，且有 2 个未推送的 commit**（`876c5f4` 通道 A + `3923dff` 本次）。**push 即部署**，
  上线后 `model_tag` 变为 `qwen3.7-flash@v2`，生产 256 条属性按 `condenser_attr_batch`=40/轮
  重抽（约 7 轮），期间 C 的影子分数会先变稀再恢复。
- **`engagement_farming` chip 的对齐率反而下降**（13/21 → 3/21），因为 v2 抽取保守得多。
  需要观察这是「少报」还是「原本就误报」。
- **deploy workspace 的 `ansible/playbook.yml` 注释仍然是错的**（声称 condenser 手动部署、
  CI webhook 已移除）。本次只在 condenser 侧的 AGENTS.md 注明了，deploy 仓库未改。

## 相关文档

- [判定 v2 通道 C/D 计划](../plans/2026-07-27-x-verdict-style-channels.md) — 本次 session 的
  上游计划（步骤 2/3 定义了 `x_attributes` 与通道 C 的计分），本次改动是对其步骤 3 的修正
- [X 判定多通道设计讨论](../notes/2026-07-24-x-verdict-multi-channel-discussion.md) — 参考，
  「一条推一个向量把话题/文风/作者揉在一起」正是本次 `promo_cta` 纠缠问题的同源解释
- [engagement_farming chip 的设计](../notes/2026-07-27-engagement-farming-chip.md) — 参考，
  本次 `emoji_spam` 归入 `engagement_farming` 沿用了它的划界理由
- [判定 v2 步骤 0–3 session 总结](2026-07-28-x-verdict-v2-style-channels.md) — 前序 session，
  本次修正的 `humblebrag` 记账 bug 即出自其步骤 3
