---
created: 2026-09-16
updated: 2026-09-16
tags:
  - x
  - article
  - probe
  - observability
  - status
  - proposal
---

# X 长文正文抓取的可观测性：`/api/x/status` 加文章计数（提议，待决定）

> ⚠️ **已被内联方案取代（2026-09-17）**，本提议不做。复核这份笔记时发现，失败没有声音的根源
> 是把抓正文从抓推文里拆了出去；[内联抓取计划](../plans/2026-09-17-x-article-inline-fetch.md)
> 把两者合回一步，失败在采集日志里当场可见，阅读界面对没正文的长文明说「未获取到正文」，
> 不加状态行 / 计数 / 重试按钮（该计划决策 3）。以下为原文，留作决策记录。

X 长文全文（schema v21，commit `005be8e`）落地后提出的后续建议。**状态：待决定。**
2026-09-16 晚复核了代码与本机 probe，结论在「现状」和「待决定」两节。

## 现状（2026-09-16 21:05 复核）

- v21 **还没部署**：master 领先 origin 一个 commit，没 push。
- 本机 probe（launchd `com.condenser.probe`）跑的是旧代码：21:05 那轮 For You 正常推送
  （9 条新推文），但没有任何 `articles/pending` 请求——服务端也还没有这个端点。
- 也就是说，笔记里「最可能发生」的第 1 种原因，此刻就是现实。这是预期内的（上线顺序
  第 1 步都没做），但它说明一件事：**新功能上线的第一天，恰恰是最需要这个信号的时候。**

## 问题：这条链路的失败没有声音

有意为之的设计：文章抓不到不该连累推文入库。副作用是失败不会报出来：

- **probe 侧**：`_run_articles` 不影响轮次成败、不计入退出码，出错只写本机日志
  （`~/Library/Logs/condenser-probe.log`）。而且日志本身也**有两处沉默**：工作单为空时一行不写；
  单条抓取全失败时 `articles` 为空、直接 return，连那行「N on the work order」的汇总都不写。
  所以 grep 日志只能看到显式报错，看不到「跑了但什么都没拿到」。
- **服务端侧**：工作单**发放时就扣次数**（`db.claim_x_article_backlog`），扣满
  `CONDENSER_X_ARTICLE_MAX_ATTEMPTS`（3）就永久跳过，不报错、不留痕。
- **推回时**：没正文的 `article` 块被跳过，只给 probe 回一个 `skipped` 数字，服务端打一条 info。

## 读者那边的现象都一样

你只会看到「这篇长文卡片上没有『查看全文』」。至少六种原因给出同一个画面：

1. probe 还没 `uv sync` + `launchctl kickstart`，旧代码根本不来要工作单（上线第 2 步忘了）
2. X 会话失效，或 TweetDetail 被限流——probe 来要了单，但每条都抓不到
3. X 改了 TweetDetail 的返回，`content` 为空，推回的全被跳过
4. 这篇首次出现已超过 7 天（`CONDENSER_X_ARTICLE_BACKFILL_DAYS`）
5. 3 次机会用完，被永久跳过
6. `CONDENSER_X_ARTICLE_ENABLED` 被关了

## 现有的状态信息为什么看不出来

`/api/x/status` 和订阅页 X 区块（`XSection.tsx` 的 `XStatusLine`）能显示 `last push` 和
`parse errors`。但**推文推送和文章抓取走两个不同的 X 接口**：HomeTimeline 和 TweetDetail，
xbird 里各有各的 query id，会分别失效。所以完全可能「last push 两分钟前、0 parse errors」，
而文章那边已经连续失败一周——现有指标给的是**假的健康信号**。

## 先例：RSS 摘要当初就是为同一个问题加的计数

`condenser/summary.py:counts()` 的注释原话：「"nothing is summarized" 和 "nothing needs
summarizing" 在 timeline 上无法区分」。所以 `/api/rss/status` 带 `summary.{enabled, pending,
done, failed}`，订阅页 `RssSummaryLine` 一行显示；HN 摘要在 `/api/hn/status` 同理。长文正文
和它们是同一类东西：后台补上的内容，缺了不报错。

## 量不算小，而且坏起来很快

**量**：7 月 29 日生产快照（`tmp/prod-0729-v2.db`）3.5 天 293 条推文里 23 条长文（约 8%，21 个
作者），每天六七篇。当时还没 Following feed，现在只多不少。

**烧完的速度**（复核时新算的，比「一周静默丢四五十篇」更要紧）：文章步骤**两条 lane 每轮都跑**
（For You 每小时 + 其余每 15 分钟 ≈ 每小时 5 轮），每轮发 5 条，每条 3 次机会。X 会话一旦失效
（第 2 种），每小时约 8 篇被判 given up；**7 天窗口里的全部存量（约 50 篇）大约 6 小时烧光**。
会话过期在本机是真会发生的事（日志里 xbird 关于 Safari cookie 的告警就是同一类问题）。
所以计数器如果只是「事后确认损失」，价值有限；它得配一个**恢复动作**才闭环。

## 提议的形状（复核后修订）

`/api/x/status` 加一个 `articles` 块，仿 RSS 的 `summary`：

- `enabled`：`CONDENSER_X_ARTICLE_ENABLED`——直接消掉第 6 种原因。
- **计数**（一条 SQL，都在 7 天首见窗口内，和工作单同一个 WHERE）：
  - `pending`：没正文、还有次数
  - `with_body`：已有正文
  - `given_up`：没正文、次数用完
- `last_order_at`：**最近一次发工作单的时间**（`article_pending` 被调用时写 `app_meta`，空单也写）。
  这是笔记原版没有的一项，也是分辨第 1 / 2 / 3 种的关键：它记录的是「probe 来问了没有」。
- `last_push`：最近一次推回的 `{at, received, stored, skipped}`，照 `x_push_stats` 存 `app_meta`。
- **订阅页**：`XStatusLine` 加一段，风格跟现有英文一致，如
  `articles 12 fetched · 3 pending · 2 given up`，given up > 0 用 amber（RSS 的 `failed` 同色）。
  iOS 没有 X 状态面，不涉及。

修订后的判断表：

| 现象 | 原因 |
|---|---|
| `enabled` false | 第 6 种 |
| `last_order_at` 为空、`pending` 持续 > 0 | 第 1 种：probe 没更新，从没来要过单 |
| `last_order_at` 在走、`given_up` 上涨、`last_push` 为空 | 第 2 种：要了单、每条都抓不到、无物可推 |
| `last_push.skipped` > 0 且 `stored` = 0 | 第 3 种：X 改了返回 |
| 全部正常、单篇没按钮 | 第 4 / 5 种，看那条推文的 `article_attempts` 和首见时间 |

**可选配套**（见「待决定」）：

- **恢复动作** `POST /api/sources/x/articles/retry`：把窗口内 `given_up` 行的
  `article_attempts` 清零，订阅页 given up 旁边一个「重试」按钮。对应 RSS 的手动 Refresh：
  修好会话之后把烧掉的补回来，而不是看着数字认损失。
- **probe 侧止血**：本轮 feed 一个都没成功时跳过文章步骤（会话坏了 TweetDetail 也不会好），
  少烧次数。一行判断，probe 单测一条。不改「发放即扣次数」的设计。

成本估计：后端 40 行左右 + 6 个测试，前端一行 + 类型；retry 端点再加 20 行 + 一个按钮；
probe 止血几行。

## 反方理由

- **单用户场景**：可以 grep probe 日志，或者发现最近长文都没按钮再去查。但如上所述，日志对
  「跑了没拿到」也是沉默的，而且给 up 6 小时就烧光窗口，「晚几天发现」等于全丢。
- **只加 API 不加 UI，价值减半**：没人会主动 curl。要做就连订阅页那行一起。
- **更便宜的替代**：把服务端「推回全被跳过」那条日志（`x.store_article_details`）从 info 升成
  warning。只覆盖第 3 种；第 1、2 种 probe 根本没把请求打到服务端。

## 待决定

1. **范围**：A = 计数 + `last_order_at` + `last_push` + 订阅页一行（推荐，最小闭环）；
   B = A + retry 端点与按钮；C = B + probe 止血。
2. **时机**：v21 还没部署。在同一次部署里把它带上（上线第一天就有信号），还是按原计划先部署
   观察一两天？倾向前者，理由是第 1 种原因发生的时点恰好就是部署当天。
3. `with_body` 是否要同时给一个不限窗口的总数（"历史共抓到多少篇"）。倾向不要，窗口内三个数
   已经能读成比率，多一个数反而要解释。

## 相关文档

- [X 长文全文计划](../plans/2026-09-16-x-article-full-content.md) — 本提议针对的功能；工作单、发放即扣次数的设计
- [RSS 源 + OPML + LLM 摘要计划](../plans/2026-08-20-rss-source-opml-llm-summary.md) — 摘要计数挂在状态接口上的先例
- [RSS 坏源退避 + 手动 Refresh](../plans/2026-09-16-rss-failure-backoff.md) — 「计数 + 恢复动作」配对的先例
- `kb/docs/probe.md` — 「The article step」一节：probe 侧的四条规则、两条 lane 都跑、kickstart 部署坑
- `kb/docs/status-and-gaps.md` — 2026-09-16「X 长文全文（schema v21）」落地记录
