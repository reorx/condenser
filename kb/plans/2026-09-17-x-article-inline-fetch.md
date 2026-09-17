---
created: 2026-09-17
tags:
  - x
  - article
  - probe
  - ingest
  - plan
---

# X 长文正文：采集时内联抓取，取代服务端工作单

> **状态：已实现（2026-09-17）**，未部署（上线顺序见 §8）。实现与本文的偏差：
> - §1.1 / §4 断路器：§4 写的是「`_run_feed` 内一个局部布尔」，与 §1.1「一轮一个断路器」矛盾——局部
>   布尔会让会话失效时每个 feed 各撞一次超时。按 §1.1 实现：`runner.ArticleReader`（节流计数 + 断路
>   状态）由 `run_round` 建、各 feed 共享，下一轮是新的 reader。
> - §1.2「抛异常」取字面：捕获任何 `Exception`，不只 `XSourceError`——xbird 的 `get_tweet` 对详情
>   响应的映射异常不做包装，正文不连累推文才成立。
> - §4 日志：`articles_failed` 也计入断路后被跳过的长文（本轮没拿到、下一轮再读的都算），断路时另打一条 warning。
> - §7「两个 articles 端点不存在（404）」：GET 是 404，POST 在本地有 `frontend/dist` 时是 405
>   （SPA 挂载点接住未路由的 POST），断言放宽为 404/405。
> - §6 详情页：未承诺正文（`has_content: false`）的请求**失败**时也显示「未获取到 article 正文」而非
>   什么都不说——列表已经说了没有，请求失败不改变这一点；「正文加载失败」只给承诺了正文的情况。
>
> **2026-09-17 code review 后的修正**（`kb/reviews/2026-09-17-x-article-inline-fetch-code-review.md`）：
> - **决策 2「只做结构性重试」部分改变**（发现 1）。三条新规则，都在 `runner.ArticleReader`：
>   1. 只有 `XSourceError`（会话 / 传输 / 限流 / not found——xbird 把远端失败包成它）走结构性重试；
>      其他异常是 xbird 对这条详情的映射崩溃，单条且确定性，视为终态：error 日志、**记缓存**、不开断路器。
>   2. 断路器改为**连续两条**不同推文的 `XSourceError` 才打开（`BREAKER_FAILURES = 2`）；中间任何一次
>      有回应的读（含「详情无正文」）清零。单条 poison 推文每轮只浪费自己一次读，不再拖累后面的长文。
>   3. **本地有界失败记忆** `cache.ArticleFailures`（`~/.cache/condenser-probe/article-failures.json`，全局
>      按推文 id，24h 窗口修剪，读不到 = 空、写不了 = warning）：真实发出去又失败的读满
>      `ARTICLE_MAX_FAILURES = 5` 次就当终态记入 SeenCache；断路后被跳过的不计。`--no-cache` 同时忘掉它。
> - **ingest 失败打开本轮断路器**（发现 2）：服务端不可用时读了也推不上去，同轮后续 feed 不再花 X 读；
>   这种打开不计入失败记忆，下一轮全部重读。已读丢掉的那一个 feed 接受。
> - §1.1 `raw` 的说法改口（发现 3）：`raw` 是**最近一次推送的原样**，无正文的 timeline 重推后不再含正文；
>   正文的档案是 `article_detail`。
> - `split_article` 改 allowlist（发现 8）：`article` 只留 `ARTICLE_CARD_KEYS = (title, previewText)`，
>   其余键全归 `article_detail`（有正文时）——xbird 以后加的正文类键不会静默进列表载荷。
> - 收藏快照回放（发现 4）：快照没带 `content_html` 时 `has_content` 回 **null** 而非 false，两端对 null
>   都是两句提示都不挂；详情端点先读活行，所以正文到了之后面板照样能取到。
> - §10 白读清单补齐（发现 7），以及失败记忆的代价。

推翻 [2026-09-16 X 长文全文计划](2026-09-16-x-article-full-content.md) 的决策 2
（「轮次末尾问服务端要工作单」），其余三项决策（服务端渲染 HTML、7 天概念改为不需要、
全文进搜索不进判定）与已落地的渲染 / 搜索 / 两端详情页**全部保留**。v21 尚未部署
（master 领先 origin 一个 commit），所以这是改一个未发布的设计，不是迁移一个线上的。

## 0. 起因

工作单模式把「抓正文」从「抓推文」里拆了出来：probe 推完 feed 之后再向服务端要一份清单，
逐条抓 TweetDetail 推回。2026-09-16 晚复核它的可观测性时
（[笔记](../notes/2026-09-16-x-article-status-observability.md)）发现两件事：

1. **失败没有声音，而且没有声音的原因是拆分本身。** 推文推送和长文抓取走 X 的两个不同
   接口，会分别失效；拆开之后服务端只看得见前者，「last push 正常、长文一周没抓到」是一个
   假的健康信号。于是要加计数、时间戳、重试按钮来补——为一个过渡性的防御在管理界面堆功能。
2. **发放即扣次数在真实故障里是一场火。** 文章步骤两条调度 lane 每轮都跑（约每小时 5 轮），
   每轮发 5 条、每条 3 次机会：X 会话一失效，每小时约 8 篇被判永久放弃，7 天窗口约 6 小时
   烧光，会话恢复后也不补。「重试三次」名义上有、实际上等于没有。

从第一性原则看：probe 采集 timeline 时就能认出长文（`article.title` 在），当场调 TweetDetail
把正文合进这条推文，随同一次 ingest 推上去。失败的重试不用另写——probe 对 timeline 抓取
本来就没有重试代码，它的重试是**结构性的**：SeenCache 只在推送成功后记录，下一轮窗口里
的同一条推文会再被当作新推文处理。长文抓取沿用这个结构即可。

当初否决内联方案的三条理由，逐条对照：

| 当初的理由 | 现在的解法 |
|---|---|
| SeenCache 24 小时不重推，失败永不重试 | 正文抓失败的推文**不记入缓存**，下一轮自然重来 |
| 存量文章永远进不了 `fresh` | 部署后跑一次 `condenser-probe run --no-cache`，整个当前窗口重推一遍、内联补抓 |
| 抓失败永远不会重试 | 同第一条 |

## 1. 决策（四项，2026-09-17 与用户确认）

1. **采用内联抓取，删除工作单。** `_run_feed` 里首见即抓；服务端 ingest 直接收带正文的
   `article` 块；`GET /api/sources/x/articles/pending`、`POST /api/sources/x/articles`、
   `x_tweets.article_attempts`、四个 `CONDENSER_X_ARTICLE_*` 设置全部删除。
2. **只做结构性重试。** 抓正文抛异常 → 推文照常推上去（正文不连累推文入库），但这条不记
   SeenCache；下一轮它还在窗口里就再抓一次。不在一轮内重试：会话失效时一轮内重试没有意义，
   偶发网络错误等 15 分钟也够。
3. **不加任何状态行 / 计数 / 重试按钮。** 感知放在阅读界面：卡片本来就带 `has_content`，
   没正文的长文在卡片和详情上明说「未获取到正文」，浏览时自然看见。X 状态行没人看，
   为过渡性防御加管理功能是过度防御。
4. **接受 For You 长文抓失败基本不重试。** For You 每次都是新样本，失败的那条大概率不再
   出现；它是不进聚合 timeline 的可选 feed。

### 1.1 附带决策

- **一轮一个断路器。** 本轮第一次 TweetDetail 抛异常（会话、限流、超时）就跳过本轮其余
  长文（都不记缓存，下一轮再来）。否则会话坏掉时一轮里连撞五次 30 秒超时，把 feed 推送
  拖慢几分钟。
- **「详情有回应但没有正文」是终态，不重试。** `fetch_tweet_article` 返回 None，或返回的
  块里 `content` / `plainText` 都为空——这是 X 的回答，不是网络故障，下一轮不会不同。
  记入缓存、warning 日志，卡片显示未获取到。只有异常才走结构性重试。
- **`raw` 列照旧存整个原始推文**，包括合并进去的正文——但它只反映**最近一次推送**：下一轮无正文的
  timeline 重推会把它覆盖成不含正文的版本（`row()` 每次都带 `raw`）。正文的档案是 `article_detail`
  （无正文重推不写这一列）；`raw` 是「上一次推送的原样」，留给格式漂移后重解析的是这个含义。
  存储翻倍只发生在长文（约 8% 的推文）上。（措辞经 2026-09-17 review 发现 3 改口，代码不变。）
- **不设每轮上限。** 自然量小（Following 每轮新推文里通常零到两篇长文），断路器已经兜住
  故障态；`--no-cache` 重推整窗也只是每个 feed 四五篇。

## 2. 数据流

```
probe 每轮（每个 feed）：
  timeline 抓取 → fresh = SeenCache 过滤
  for t in fresh:  if t.article.title:
      detail = TweetDetail(t.id)              ← 1s 节流；第一次异常 → 断路，其余本轮跳过
      t.article = {**t.article, **detail}     ← 只合并 article 块，text 保持 timeline 版本
  POST /api/sources/x/ingest (fresh 全部)
  SeenCache.record(fresh − 抓正文时抛异常的那些)

服务端 ingest：
  parse_tweet 把 article 块拆成
      article        = {title, previewText, …非详情键}   → x_tweets.article（列表载荷照旧）
      article_detail = {content, plainText, coverMedia, media, publishedAt, modifiedAt}
                        （仅当 content / plainText 非空）→ x_tweets.article_detail
  upsert 时 article_detail 为 None 就**不写这一列**（重推不能把已有正文清掉）
  search.index_x_tweets 照旧跑在 feed 行之后 → 全文自动进 FTS，不需要额外一步
```

## 3. Schema

`SCHEMA_VERSION` 保持 21（未发布）。`_migrate_x_article_v21` 只加 `article_detail TEXT`，
`article_attempts` 从迁移里删掉。本机跑过未发布 v21 代码的开发库会留着一个死列
`article_attempts`，迁移是按形状判断的（有 `article_detail` 就跳过），死列无害，不为它
写迁移。`kb/docs/database.md` 的 v21 条目相应改写。

## 4. probe（`probe/condenser_probe/`）

| 文件 | 改动 |
|---|---|
| `runner.py` | 删 `_run_articles`。`_run_feed` 加 `fetch_article` / `delay` / `sleep` 参数：在 `fresh` 算出后、ingest 之前做内联抓取（§2），返回值 `FeedOutcome` 记 `articles_fetched` / `articles_failed`；`cache.record` 只记正文没抛异常的推文。`run_round` 把 `fetch_article` 等透传给 `_run_feed`，删掉轮次末尾的调用。断路器是 `_run_feed` 内一个局部布尔 |
| `client.py` | 删 `pending_articles` / `push_articles` |
| `xsource.py` | `fetch_tweet_article` 不变 |
| `__main__.py` / 文档字符串 | 「轮次以文章步骤收尾」的描述改掉 |

日志：每个 feed 那行汇总加 `articles N fetched, M failed`；单条失败 error 级；断路触发一条
warning。这就是 probe 侧全部的可观测性，失败发生在采集这一步，日志里当场可见。

## 5. 服务端（`condenser/`）

| 文件 | 改动 |
|---|---|
| `x.py` | `ParsedTweet` 加 `article_detail: Optional[dict]`；`parse_tweet` 按 `ARTICLE_DETAIL_KEYS` 拆块（保留现有 `article_detail()` 判空逻辑，改名为拆分辅助）；`row()` 仅在非 None 时带 `article_detail` 键。删 `article_pending` / `store_article_details`、模块顶部的工作单说明；`status()` 不动 |
| `db.py` | 删 `claim_x_article_backlog` / `set_x_article_details`；`XTweet.article_attempts` 字段与迁移里的那行删掉。`upsert_x_tweet` 不改（它只更新传入的键，`row()` 不传就不清） |
| `routers/x.py` | 删两个 articles 端点与 `XArticlesBody` |
| `config.py` | 删 `condenser_x_article_enabled` / `_backfill_days` / `_batch` / `_max_attempts`；`.env.example` 同步 |
| `items.py` / `sources/x.py` / `xarticle.py` / `records.py` / `search.py` | **不动** |

## 6. 客户端：没正文的长文要说出来

现状：web 卡片只在 `has_content` 时给「查看全文」，否则什么都不显示；web 详情面板与 iOS
sheet 在没正文时停在标题 + 预览卡，不说话。内联之后 `has_content=false` 不再是「还在路上」
的常态，而是「probe 没拿到」（老 probe、会话失效、X 没给），所以要明说。

- **web `XCard`**：「查看全文」的位置在 `has_content === false` 时改为一段 muted 的
  「未获取到正文」（非按钮，不可点）。这是浏览时的感知点。
- **web `ItemDetailBody`**：列表说没有、详情端点也回 `content_html: null` 时，预览卡下方
  一行「未获取到 article 正文」。现有「正文加载失败」（请求出错）保留，两者不同。
- **iOS `XDetailSheet`**：同样的一行，放在预览卡下方；`XCard` 同 web 加 muted 文字。
  Kit 层不需要新逻辑，`hasContent` 已经在。

措辞两端统一：卡片「未获取到正文」，详情「未获取到 article 正文」。

## 7. 测试（BDD：先写行为用例，再改实现）

**服务端 `tests/test_x_article.py`**（工作单一节整段替换）：

- 推文带正文块 ingest → `article` 仍是标题 + 预览对、`article_detail` 存下六个键
- 列表载荷的 `article` 只多 `has_content: true`，绝不带 `content`
- 同一条推文再次推送、这次不带正文 → 已有正文保留（现有用例改造）
- 推文带的正文块 `content` / `plainText` 都为空 → `article_detail` 不写、`has_content=false`
- 全文在 ingest 后即可搜到（现有用例改成走 ingest）
- 详情端点 / 收藏快照 / retention 相关用例不动
- v21 迁移用例：只断言 `article_detail` 列存在，删掉 `article_attempts` 的断言
- 两个 articles 端点不存在（404）——防止残留

**probe `probe/tests/test_probe.py`**（文章步骤一节整段替换）：

- 带 `article.title` 的新推文在 ingest 前被抓详情，推上去的 `article` 已合并正文块
- 没有 `article` 的推文不触发详情请求
- 抓详情抛异常 → 推文仍被推送、但不记 SeenCache；下一轮同一条再抓一次
- 第一次异常后本轮其余长文不再请求详情（断路器），且它们都不记缓存
- 详情返回 None 或无正文 → 推文推送、记缓存、不再重试
- 详情请求之间有 1s 节流；抓详情永远不沉 feed
- 轮次末尾不再有任何 articles 请求

**web**：`XCard.test.tsx` 加「无正文时显示未获取到正文、不是按钮」；`ItemDetailBody.test.tsx`
把「promises nothing」用例改为断言那一行提示。**iOS**：Kit 无新逻辑，构建通过即可，
sheet 与卡片截图走查一次。

## 8. 上线顺序

1. push master → 服务端先上（新服务端收老 probe 的推送零变化）。**顺序不能反**：老服务端
   会把整个带正文的 `article` 块存进 `x_tweets.article`，列表载荷当场带三千字。
2. 探针机 `cd probe && uv sync && launchctl kickstart -k gui/$(id -u)/com.condenser.probe`。
3. `condenser-probe run --no-cache` 一次，把当前窗口里已推过的长文补上正文。
4. 验证：打开 timeline 最近的长文卡片看有没有「查看全文」；probe 日志 `articles N fetched`。
5. iOS 随下个 build（卡片 / sheet 的提示文字）。

## 9. 文档

- 本计划；原计划 `2026-09-16-x-article-full-content.md` 顶部加一段「决策 2 已被本计划推翻」
- `kb/notes/2026-09-16-x-article-status-observability.md` 顶部标「已被内联方案取代」
- `kb/docs/probe.md` 「The article step」整节重写为内联抓取的四条规则
- `kb/docs/database.md` v21 条目去掉 `article_attempts`
- `CLAUDE.md` 的 `x.py` 行、probe 段、`kb/docs/status-and-gaps.md` 新条目

## 10. 已知代价

- For You 长文失败即失去（决策 4）。
- 已滚出 timeline 窗口的老长文永远只有预览（和原计划 §9.5 一样，只是不再有 7 天这个数）。
- **白读**：probe 不知道服务端会丢掉什么，照样为它们各花一次 TweetDetail——Following 年龄过滤
  （过老的推文降为无 feed 行的 body-only 存档）、Following 的**广告过滤**（作者不在关注列表，整条丢弃）、
  For You 的**语言过滤**（整条丢弃）。量可接受（For You 约 4 次读 / 小时）。
- **失败记忆的代价**（review 发现 1 第 3 项）：会话连续失效超过约 5 轮（≈75 分钟），每轮最先尝试的那
  一两篇（断路前的两次真实读）会被记满 5 次、永久放弃正文。`condenser-probe run --no-cache` 同时忘掉
  失败记忆，是补救办法。
- **ingest 失败那一轮**（review 发现 2）：失败 feed 之前已读到的正文随推送一起丢掉，下一轮重读；
  同轮后续 feed 不读正文。
- 2026-09-16 写的工作单代码与约 20 个测试作废。v21 未发布，无迁移包袱。
