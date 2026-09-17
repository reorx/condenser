---
created: 2026-09-17
tags:
  - x
  - article
  - probe
  - review
---

# Code review：`195940b` X 长文正文改为 probe 采集时内联抓取

审查者：Fable agent（只读，2026-09-17）。审查对象 commit `195940b`，计划
`kb/plans/2026-09-17-x-article-inline-fetch.md`。三套测试审查时全绿（后端 920 / probe 59 / web 307）。
服务端拆分（`split_article` / `row()` 不带空列）、两端 UI、迁移（含带 `article_attempts` 死列的开发库）、
新旧版本兼容均核对无误。问题集中在 probe 侧的重试结构。

每条发现后面的「处理建议」是主会话看过报告后给出的建议，修复时照此执行。

## 发现（按严重度）

### 1. 高 — 单条确定性读失败的长文会让本轮之后所有长文正文停摆，且每轮重复，无上限

**位置**：`probe/condenser_probe/runner.py` `ArticleReader.read`（第一次异常即 `self.open = True`）+
`_run_feed` / `_read_articles`（失败的 id 不记缓存）。

**问题**：断路器把「会话 / 限流」这类全局故障和「这条推文的 detail 就是读不出来」这类单条故障当成同一件事。
一条 detail 确定性失败的长文——xbird `map_tweet_result` 对某种 content_state 抛 KeyError（正是
`except Exception` 要兜的场景），或 X 对这条回 tombstone → xbird `get_tweet` 返回
`'Tweet not found in response'` → `XSourceError`——因为不记 SeenCache，下一轮仍是「新推文」，仍第一个失败，
仍打开断路器：排在它后面的所有长文（同一 feed 的、以及后续所有 feed 的）每轮都被跳过、也都不记缓存。只要它还在
X 的 timeline 窗口里（低产作者的 user feed 可以是几周），整个正文功能等于关闭。计划删掉 attempts 上限时假设
失败是瞬时的，这个假设对单条推文不成立。

**复现**（Following 里一条 poison 长文排第一 + 一条正常长文，user feed 每轮再来一条新长文，跑 3 轮）：

```
round 1: failed=[2, 2] fetched=[0, 0] bodies so far=[]
round 2: failed=[2, 2] fetched=[0, 0] bodies so far=[]
round 3: failed=[2, 2] fetched=[0, 0] bodies so far=[]
cache following: [] | user: []
```

`195940b` 的端到端验证（「不存在的 id 读失败 → 断路打开；第 2 轮只有这一条被重读」）演示的正是这个行为。

**处理建议**（三项都做）：

1. **非 `XSourceError` 的异常**（xbird 解析崩溃，单条、确定性）→ error 日志、视为终态、**记缓存**、**不开断路器**。
   `XSourceError`（HTTP / 传输 / 限流 / not found，xbird 把传输错误包成它）才走结构性重试。
2. **断路器改为连续两条不同推文的 `XSourceError` 才打开**；中间一次成功（包括「详情无正文」这种有回应的读）清零。
   会话失效时每轮多付一次超时；单条 poison 每轮只浪费它自己一次读，不再拖累别人。
3. **本地有界失败记忆**：每条推文的真实失败次数记在本地（SeenCache 旁，或 SeenCache 同目录的一个文件，按 feed 或全局
   均可，按实现最简选），满 `ARTICLE_MAX_FAILURES = 5` 次就当作终态记入 SeenCache，不再读。**断路后被跳过的不计数**，
   只计真实发出去又失败的读。拦住 tombstone 推文在窗口里每 15 分钟被读一次。代价（写进计划 §10）：会话连续失效
   超过约 5 轮（≈75 分钟），每轮最先尝试的那一两篇永久拿不到正文。记忆要随时间修剪（同 SeenCache 的 24h 窗口即可），
   文件读写失败的处理与 SeenCache 一致（读不到 = 空，写不了 = warning，不沉轮次）。

这改变了计划决策 2「只做结构性重试」的一部分，修复后在计划顶部的偏差列表里写明。

### 2. 中 — ingest 失败后，本轮的 TweetDetail 读全部白费，且服务端不可用期间每轮重复

**位置**：`runner.py` `_run_feed`（`ServerError` → return，不记缓存）。

**问题**：正文读在 push 之前；push 失败时所有读都丢掉，且因为不记缓存，下一轮 `fresh` = 整个窗口，再读一遍。
服务端宕机 1 小时：Following + 各 user feed + For You，每 15 分钟一轮 → 几十次无意义 X 读。断路器对此无感（X 侧没抛异常）。

**复现**：`round 1 reads: ['11','12'] pushed: 0` → `round 2 reads: ['11','12','11','12']`。

**处理建议**：`_run_feed` 遇到 ingest 的 `ServerError` 时打开本轮 reader 的断路器（同轮后续 feed 不再花 X 读——
服务端不可用时读了也推不上去）；已读丢掉的那一个 feed 接受。注意这类「打开」不应计入发现 1 的失败记忆。

### 3. 低 — `raw` 在无正文重推后丢掉正文，与「档案」说法不符

**位置**：`condenser/x.py` `ParsedTweet.row()`（每次都带 `raw`）；计划 §1.1「`raw` 列照旧存整个原始推文，包括合并进去的正文……
留给格式漂移后重解析」。

无正文 timeline 重推后 `raw` 不再含正文，`article_detail` 仍在。`raw` 只反映最近一次推送。

**处理建议**：改文档措辞（计划 §1.1 加偏差说明、`kb/docs/database.md` v21 条目），明确 `article_detail` 才是正文档案，
`raw` 是最近一次推送的原样。不改代码。

### 4. 低 — 收藏快照的 `has_content` 冻结，Saved 列表会永久显示「未获取到正文」

**位置**：`condenser/records.py` 快照回放 → `condenser/items.py` `_x_article`（无 `has_article_content` 列时从存的字段读回）；
`frontend/src/components/timeline/XCard.tsx`、iOS `XCard.swift`。

**场景**：读失败那轮用户收藏了它（快照 `has_content: false`）→ 下一轮正文到了 → timeline 卡片显示「查看全文」，
Saved 里同一条永远显示「未获取到正文」（面板打开仍能取到正文，因为 `GET /api/x/tweets/{id}` 先查活行）。

**处理建议**：快照回放（row 里没有 `has_article_content`）且没有 `content_html` 时，`has_content` 给 `None`
（JSON null）而非 `False`——两端对「无字段 / null」都已是「两句都不挂」。有 `content_html` 的快照照旧 `True`。
先写后端测试钉住。核对 web `types.ts` 与 iOS Kit `XArticle.hasContent` 能解 null（iOS 已是可选）。

### 5. 低 — 代码注释残留旧设计（工作单 / 轮次末尾）

- `frontend/src/lib/types.ts:154`：「fetched by the probe in a second step (plan 2026-09-16)」
- `ios/CondenserKit/Sources/CondenserKit/Models.swift:348-349`：「正文由 probe 在轮次末尾经 TweetDetail 补抓」
- `kb/docs/ios.md:371`：「正文比推文晚到（probe 轮次末尾才抓）」

**处理建议**：改成内联抓取的描述。修完再 grep 一遍「轮次末尾 / second step / work order / 工作单」确认只剩历史说明。

### 6. 低 — 测试缺口

- **web**：「未承诺正文 + 请求失败 → 显示『未获取到 article 正文』而非『正文加载失败』」
  （`ItemDetailBody.tsx`）没有用例；把两个分支都写成「正文加载失败」也不会红。
- **probe**：没有钉住「ingest 失败 → 本轮断路 / 下一轮重读」，也没有跨 feed 的节流（`sleeps` 只测了同一 feed 三条）。
- **后端**：没有「无正文重推后全文仍可搜」。

**处理建议**：三处都补；发现 1、2 的新行为先写失败用例再实现。

### 7. 低 — 计划 §10 的「白读」清单不全

For You 的语言过滤和 Following 的广告过滤会把整条推文丢掉，但 probe 已经为它们各花了一次 TweetDetail（§10 只提了年龄过滤）。
量可接受（For You ≈ 4 次读 / 小时）。

**处理建议**：补进计划 §10 与 `kb/docs/probe.md` 的代价说明。不改代码。

### 8. 建议 — `split_article` 的键方向

`x.py` `split_article` 用 denylist：不在 `ARTICLE_DETAIL_KEYS` 里的键全留在 `article` 列 → 进列表载荷。
xbird 以后给 detail 加一个新的正文类键（如 `contentState`），列表就会静默变大。

**处理建议**：改成 allowlist——`article` 只保留 `title` / `previewText`（定义成常量），其余键全部归
`article_detail`；「有实际文本才算正文」的判空规则不变（`content` / `plainText`），`ARTICLE_DETAIL_KEYS`
若不再有读者就删掉。先改测试：新增一个未知键出现在推送里时，列表载荷不带它、`article_detail` 带它（有正文时）。

## 已核对、无问题的点

- `upsert_x_tweet` 只更新传入键，`row()` 无正文不带 `article_detail`：无正文重推保留正文、带正文重推覆盖，测试钉住。
- `split_article` 边界：非 dict → `(None, None)`；`{}` → `({}, None)`；只有正文键 → `({}, detail)`；正文键值 None / 空白 → detail None。
- `{**article, **detail}` 合并：xbird 序列化丢 None，detail 不会用 None 盖掉 timeline 的 `previewText`。
- SeenCache id 类型：`unread` 与 `t.get('id')` 取同一个值，`_entry_id` 统一 `str()`。
- 断路器 / 节流跨 feed：一轮一个 `ArticleReader`，两条调度 lane 各自 `run_round` 各自 reader。
- body-only 路径（Following 年龄过滤、内嵌引用）：`insert_x_tweet_if_absent` 带 `article_detail` 可写；已有无正文行时正文被忽略（与计划 §10 一致）。
- 搜索：`index_x_tweets` 在 upsert 之后跑、从 DB 读 `article_detail`；verdict 仍只读 title + preview。
- 列表载荷：`_COLS` 只有 `has_article_content`，`_x_article` 只加 `has_content`。
- 迁移：pre-v21 库只加 `article_detail`；带死列 `article_attempts INTEGER NOT NULL DEFAULT 0` 的开发库 init + ingest 正常、integrity ok。
- `raw` 读者：DB 里的 `raw` 没有任何读者（`condenser/`、`scripts/`），只有 ingest 内存里的 `tweet.raw.get('quotedTweet')`。
- 部署顺序 / 兼容：新 probe → 老服务端会把整块存进 `article`（文档已写「服务端先上」）；老 probe → 新服务端 = 全部 `has_content: false`；老 iOS 忽略新键。
- web `ItemDetailBody` 六种状态走读正确；iOS `articleSection` 三条加载路径都置 `articleLoaded`。
- `ArticleReader.read` 的 `except Exception` 理由成立（xbird `get_tweet` 的映射在任何 try 之外）——但正因为这类异常是单条确定性的，不该开断路器（发现 1）。
