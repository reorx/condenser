---
created: 2026-08-22
tags:
  - rss-source
  - post-launch
  - bugfix
  - plan
---

# RSS 开闸后的四个待办 —— 执行计划

> 起因：2026-08-22 `CONDENSER_RSS_ENABLED=true` 在生产开闸（deploy 仓库 commit `54b066d`），
> 用户导入 77 个 feed 的 OPML，观察了两轮真实轮询。**基础订阅功能验收通过**：坏源分类正确、
> 不沉整轮、幂等、304 路径成立。这份计划收的是同一次观察里暴露出来的四件事——两个真 bug
> （§1 §2）、一个当场拍板的设计决策（§3），和一个留到下个会话讨论的（§4）。
>
> 前序计划：[RSS 源 —— OPML 导入 + LLM 摘要](2026-08-20-rss-source-opml-llm-summary.md)。
> 那份计划的 Phase 4「开闸」这一步由本次完成，**但 iOS 侧载仍然欠着**（见 §6）。

## 0. 现场数据（这份计划的全部证据）

两轮真实轮询，日志与只读查询归档在 `tmp/2026-08-22-rss-prod-logs/`（可复跑）。

| | 冷轮 06:19:34 | 热轮 06:50:15 |
|---|---|---|
| 耗时 | 39s | **13s** |
| feeds / errors | 77 / 10 | 77 / 10 |
| new_entries | 1583 | **0** |
| HTTP 状态分布 | — | 41×304 · 29×200 · 9×301 · 5×404 · 4×308 · 1×403（共 89 次请求） |

生产库（两轮之后）：条目 1583 · **未读 15** · 搜索文档 1568 · `error_count` 分布干净地
分成 `0 → 67 个` 和 `2 → 10 个`。

**已经验证成立、不要在本计划里改动的东西**：

- 坏源四类失败分得清（DNS / 403 / 404 / 「不是 feed」），每个只打一条 WARNING、无 traceback、
  不沉整轮；10 个失败在同一秒内返回。
- 每源每轮**恰好一次**请求（`error_count` 两轮后恰为 2），轮内不重试，没有重试风暴。
- 幂等 ingest（第二轮 new_entries=0，条目/文档/未读三个计数一动不动）。
- **304 路径在真实流量上跑通**（41/67 = 61% 命中）——Phase 1 那个「httpx 把 304 归为重定向、
  `raise_for_status()` 会抛」的 bug 确认已修好，冷热轮 39s→13s 的差距就是它省下来的。
- 搜索文档比条目少 15 条，是 15 条**标题与正文都为空**的条目（`zak.ee` 的 stream 微博类），
  空文本不建文档是对的，且没有孤儿文档。

## 1. 【Bug】订阅页 5 秒轮询永不停止

**症状**：日志里 `GET /api/sources/rss/subscriptions` 从 06:19:38 一路 5 秒一次打到 06:22:34
（用户离开页面才停），而抓取轮 06:20:13 就结束了。

**根因是两个各自正确的设计撞在一起**：

- `condenser/db.py:1961` `record_rss_feed_error` 的 docstring 写得很清楚：失败时**刻意不动
  `fetched_at`**，因为它的含义是「上次真正见到这个源」，这才让陈旧的源看得出来。
- `frontend/src/components/subscriptions/RssSection.tsx:36`：
  `refetchInterval: (query) => (data.some((s) => !s.fetched_at) ? 5_000 : 60_000)`，
  上方注释断言「**the condition ends itself** — a feed only lacks `fetched_at` until its
  first round」。

对一个**永久失败**的源，这句断言是假的：它的 `fetched_at` 永远是 NULL。生产实测
`feeds_never_fetch = 10`，与出错的 10 个是同一批。所以订阅页只要开着，就永远 5 秒一次。

**方案**：改前端条件，不动后端。后端那条注释的语义是对的，不该为前端的轮询让步。

```ts
// 「还没有结论」才快轮询：启用中、没抓到过、且一次都没失败过
refetchInterval: (query) =>
  ((query.state.data ?? []).some((s) => s.enabled && !s.fetched_at && s.error_count === 0)
    ? 5_000
    : 60_000),
```

`enabled` 与 `error_count` 都已经在 `RssSubscription` 类型里
（`frontend/src/lib/types.ts:362,369`），无需动 API。语义变成「快轮询直到每个**在跑**的源都有了
**结论**（成功或失败）」——对坏源同样会结束。

**`enabled` 这一项不是凑数**：§3 定的运维方式是「坏源由读者手动关掉开关」，而一个**加进来后
在首轮之前就被暂停**的源，三个字段恰好是 `fetched_at=null` + `error_count=0` +
`enabled=false`——它永远不会被抓，也就永远拿不到结论。不排掉 `enabled=false`，这个 bug 就换个
入口复发一次。

**测试（前端 vitest）**：四条——全新导入（无 fetched_at 无 error）→ 5000；混合（部分成功、
部分失败）→ 60000；全成功 → 60000；**未抓过但已暂停 → 60000**。第二条和第四条是复现用例，
现在都会红。

## 2. 【Bug】bozo 警告会在 304 轮被抹掉，徽标会闪

**症状**（热轮实测）：

| feed | 本轮 | `last_error` |
|---|---|---|
| `eurychen.me/index.xml` | 304 | **被清成 NULL** |
| `flyhigher.top/feed` | 200 | 警告保留 |

**根因**：`condenser/db.py:1949`，`record_rss_feed_success` 无条件把 `note` 写进 `last_error`：

```python
fields: dict = {RssFeed.fetched_at: at, RssFeed.last_error: note, RssFeed.error_count: 0}
```

而 304 分支（`condenser/rss.py:358-362`）**不传 `note`**（它没解析任何文档，无从产生警告），
于是 `note=None` 把上一轮记下的 bozo 警告覆盖掉了。同一个函数里紧接着的循环对
`title`/`site_url`/`etag`/`last_modified` 做的正是相反的事——`if value is not None` 才写，
docstring 也明说「a 304 carries no title and must not erase the one we learned」。`last_error`
漏在了这条规则外面。

**为什么这是 bug 而不是无所谓**：304 的含义是「**文档没变**」。文档没变、针对该文档的警告却
消失了，读者看到的徽标会在 200 轮和 304 轮之间来回闪——而 bozo 警告存在的全部意义就是告诉
读者「这个源的 XML 是坏的」，一个会自己消失的警告等于没有。

**方案**：让 `last_error` 服从同一条「NULL 不覆盖」规则，把它从无条件字段挪进条件循环；
调用方要**清除**警告时传空串 `''` 而不是 `None`。两个调用点都要跟着改：

- 200 成功且无警告 → 传 `note=''`（显式清除：新文档解析干净了）
- 304 → 不传（保留上一轮的结论）
- 失败 → 走 `record_rss_feed_error`，与本项无关

**测试（`tests/test_rss.py`）**：两条——「200(bozo) 后接 304，警告仍在」（复现用例，现在会红）；
「200(bozo) 后接 200(clean)，警告被清除」（防止改过头变成警告永不消失）。

## 3. 【已决策】坏源不加退避 —— 由读者确认后手动关闭开关

**现状**：`record_rss_feed_error` 只做 `error_count + 1`，**没有自动退订、没有退避、没有上限**。
10 个死源 × 48 轮/天 = **480 次/天**注定失败的请求。

**用户决策（2026-08-22 拍板，不再重议）**：**不做自动退避。** 确认一个源是坏的之后，读者
**手动关掉它的开关**（暂停），但**保留在订阅列表里**——不退订、不删归档。

这个决策的好处是它不需要新代码：`db.enabled_rss_subscriptions()`（`condenser/db.py:1899`）
本来就只取 `enabled == True`，暂停即刻停止轮询；`rss_polling_active()` 用同一个条件当轮询闸门。
留在列表里则保住了它的归档、`etag` 与错误记录——哪天源恢复了，打开开关就续上。
「只记录，不自动退订」这条原则因此原样成立：**判断谁是死源是读者的事，服务器只负责把证据摆清楚**。

**所以本节的实际工作量只有一件：让那 10 个源在 77 行里找得到。**

订阅行已经有证据了（`RssSubscriptionRow.tsx:28-55`：`error_count > 0` 显示失败徽标 +
`last_error` 的 tooltip，并且**刻意**把它与 `error_count = 0` 的 bozo 警告区分开）。缺的是
**顺序**：`db.list_rss_subscriptions()`（`condenser/db.py:1831`）按 `added_at desc` 返回，
77 行里 10 个坏源是散开的，要挨行翻。

**方案（纯前端，无后端改动）**：`RssSection` 渲染前对列表做一次客户端排序——
`error_count > 0` 的排最前，其余保持 `added_at desc` 的原序（稳定排序）。**不加筛选器、不加
分组标题**：读者要做的动作是「看一眼 → 关掉」，把它们顶到顶部就够了，多一层 UI 就是多一层
要维护的状态。

**取舍**：排序会让一个源在失败后「跳」到列表顶部，位置不稳定。这正是想要的——它就是在提醒
你有事要处理；而处理完（关掉开关）之后 `error_count` 仍 > 0，它会**留在顶部**，等于一份
「已处理但仍坏着」的清单。若这点在实际使用中变烦，退路是把已暂停的源排回原位（一行判断）。

**测试（前端 vitest）**：两条——坏源排到列表最前；同为坏源之间、以及正常源之间都保持
`added_at` 原序（钉住稳定排序，防止顺序在每次渲染时抖动）。

**留作观察、暂不实现**：读者手动关完之后，剩余的失败请求量应该归零。如果实际使用中发现
「源坏掉 → 读者注意到 → 手动关掉」这个回路太长（比如坏源频繁出现、每次都要人工介入），
再回来重议退避。**现在没有证据说明它太长，所以不写代码。**

## 4. 【待决策中】永久重定向不迁移 URL —— 13 个源每轮白吃一次往返

> **状态：未拍板，下一个会话再讨论。** 本节先把证据和三个提案摆齐，不写代码、不进分期。
> 下面的 A/B/C **都是待讨论的提案，没有一个是已定决策**。

**现状**：热轮 89 次请求服务 77 个 feed，多出来的是 **9 个 301 + 4 个 308**。
`_http_fetch_feed` 用 `follow_redirects=True` 跟过去拿到了内容（功能正常），但存库的 URL 从不
更新，所以这 13 次额外往返**每轮都付**，永远。日志里能直接看到搬了家的：
`tianxianzi.me/atom.xml` → `www.tianxianzi.me/...`、`zdyxry.github.io` → `blog.zhouyiran.link`
（后者搬完还 404，属于 §3 那批）。

**提案 A（待讨论）：做，但只在整条链都是永久重定向时做。**

- 判据：`resp.history` 非空**且每一跳都是 301/308**。混了 302/307 的不迁移——那是临时的，
  今天跟过去明天就错了。
- 迁移是**改键**，要在一个事务里同时改：`rss_feeds.url`（PK）、`subscriptions.channel_id`
  （复合 PK 的一半）、`rss_entries.feed_url`（该 feed 的全部行）。`read_items` /
  `saved_items` / `search_index` 都按 entry id 走，**不受影响**。
- 目标 URL 已存在（读者同时订阅了新旧两个地址）→ **不迁移**，只记一条 `last_error` 说明，
  让读者自己退订一个。合并两个 feed 的归档不是这里该做的决定。
- **已知会漂的一处**：`records.py` 的收藏快照存的是 envelope payload 本身，里面带着旧
  `feed_url`。快照的语义就是「当时的样子」，接受，不回填。
- 前端 `/s/rss/:feed` 路由用 `encodeURIComponent(url)` 做路径段，迁移后旧书签会 404 —— 单用户
  系统，接受。

**取舍**：省下 13 次/轮的往返，且让订阅行显示的 URL 与真实抓取地址一致（现在读者看到的是一个
已经搬走的地址）。代价是这是本计划里唯一动键的改动，事务写错就是数据不一致。

**提案 B（待讨论）：只在 UI 上提示「此源已永久重定向到 X，点此迁移」**——把决定交给读者，
实现小得多，且不会自动改键。代价是 77 个源里有 13 个要人工点。

**提案 C（待讨论）：什么都不做。** 13 次/轮的额外往返在 30 分钟周期上是可以忽略的成本，
而 §3 刚刚定下的「坏源由读者手动处理」是同一种取向——服务器摆证据，人做决定。

**讨论时要先答的三个问题**（下个会话从这里开始）：

1. **这 13 次往返到底值多少？** 一轮 13 次额外 HTTP、每天 624 次。它痛在哪里，还是根本不痛？
   若不痛，提案 C 就是答案，A 和 B 都不必谈。
2. **订阅行显示一个已经搬走的地址，算不算问题？** 这可能比省往返更重要——读者看到的 URL 与
   实际抓取的地址不一致，是个会误导人的显示。若这才是真痛点，提案 B 足够，不必动键。
3. **动键的风险接受度**：提案 A 要在一个事务里改三张表（`rss_feeds.url` PK、
   `subscriptions.channel_id` 复合 PK 的一半、`rss_entries.feed_url` 的全部行），这是本轮唯一
   动键的改动。与 §3 刚定的「不让服务器替读者做决定」这条取向，A 也隐隐相冲。

## 5. 分期与优先级

| 阶段 | 内容 | 为什么这个顺序 | 验收 |
|---|---|---|---|
| **P1** | §1 前端轮询条件 + §2 `last_error` NULL 不覆盖 | 两个都是 bug、都很小、互不相干，一起做一起发 | `uv run pytest` + `pnpm test` 全绿；生产开着订阅页看轮询退回 60s；下一个 304 轮后 `eurychen.me` 的警告仍在 |
| **P2** | §3 订阅行按失败优先排序（纯前端） | 依赖 P1 已经改过同一个组件，接着做省一次上下文 | `pnpm test` 全绿；生产订阅页 10 个坏源在最上面，读者关完开关后当日失败请求数归零 |
| — | §4 永久重定向 | **待决策，不进分期** | — |

两个阶段都是小改动，可以合成一次发。**注意 `git push` master 即生产部署**，且当前仓库里已经
躺着两个未推送的 commit（`803ee69` OPML 挑选器、`fb4cdc0` lxml 依赖），P1 一发会连它们一起上。

**P2 之后的人工动作**（不是代码，是运维）：读者在订阅页把那 10 个坏源逐个关掉开关。当前名单：

| feed | 失败原因 |
|---|---|
| `blog.extrawurst.org/feed.xml` | DNS 解析失败（域名没了） |
| `xdash.one/feed` | 403 |
| `blog.zhiheng.io/index.xml` · `camelliayang.com/blog/feed` · `tianxianzi.me/atom.xml` · `kittenyang.com/rss/` · `zdyxry.github.io/posts/atom.xml` | 404（后三个是跟随重定向后才 404 —— 搬了家又没了） |
| `feeds.feedburner.com/dim` · `feeds.feedburner.com/hc1983` · `pinfive.today/@hal9000/feed/` | 不是 feed（返回的是 HTML） |

## 6. 本计划之外、但欠着的事

- **iOS 侧载**（前序计划 §7 第 2 步）：现装的 1.0.0 不认识 `rss`，聚合时间线会给它画空行。
  目前生产已开闸且有 1583 条 RSS 条目，**这个雷已经埋下了**，只差用户打开手机。`make device`
  需要 USB 连机，人必须在场。
- **AI 摘要开关**：`CONDENSER_SUMMARY_API_KEY` 尚未配置。候选是「启用 feed 的未读条目」，
  实测只有 **15 条**（不是 1583）——一周未读窗口在博客类 feed 上就是这个形状。
- **`fb4cdc0` lxml 依赖**待发（生产每次链接预览打一条假 ERROR）。
- **`database is locked` 间歇失败**（`tests/test_rss.py` 的端点测试，干净 master 上可复现）：
  诊断指向 `db.add_rss_subscription` 的 deferred `atomic()` 里「先 SELECT 后 INSERT」，
  快照失效时 SQLite 跳过 busy handler 直接报 `SQLITE_BUSY`；建议改
  `atomic(lock_type='IMMEDIATE')`。**此诊断尚未独立验证**，值得单开一轮 TDD ——
  生产是同样形态（Telethon 事件循环写 + threadpool 请求写 + RSS ingest 线程写）。

## 7. 明确不做

- 空标题空正文的条目（全库 15 条）特殊处理：目前都是老条目、已自动标读，看不到。真落进一周
  窗口里再说——那时的正确做法是卡片回退显示 `link`，不是丢弃条目。
- 为 feedburner 那三个「不是 feed」的源做 HTML 探测/自动发现（`<link rel=alternate>`）：
  那是「添加订阅」时该做的事，不是每轮轮询该做的事。
- 自动退订、自动暂停、自动退避任何源（§3 已决策：判断谁是死源是读者的事）。
- 订阅页加坏源筛选器或分组标题：排序已经够了，多一层 UI 就是多一层要维护的状态。
