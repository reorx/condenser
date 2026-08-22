---
created: 2026-08-22
tags:
  - rss-source
  - post-launch
  - bugfix
  - plan
---

# RSS 开闸后的四个待办 —— 执行计划

> **状态（2026-08-23 更新）：§1 §2 §3 §4 全部完成，P1–P3 三期已提交，未推送。**
> 提交：`7649d97`（P1 = §1+§2）、`d413f51`（P2 = §3）、`da942d0`（P3 = §4）、
> `29662a8`（§4 拒绝措辞对上「已退订但归档还在」+ 一条测试）。
> 712 backend + 179 frontend 全绿；本地验收（种了六种抓取状态的临时库 + 真实轮询）
> 在 `tmp/2026-08-22-rss-post-launch-fixes/`。三件事在真实流量上证过：轮询退回 60s、
> bozo 警告在真实 304 后仍在、真实 301 整体迁移（含目标已存在时的拒绝）。
> **未做的只剩 §6 那三项**（iOS 侧载、摘要开关、`database is locked` 诊断），它们本来
> 就在本计划之外。

> 起因：2026-08-22 `CONDENSER_RSS_ENABLED=true` 在生产开闸（deploy 仓库 commit `54b066d`），
> 用户导入 77 个 feed 的 OPML，观察了两轮真实轮询。**基础订阅功能验收通过**：坏源分类正确、
> 不沉整轮、幂等、304 路径成立。这份计划收的是同一次观察里暴露出来的四件事——两个真 bug
> （§1 §2）和两个设计决策（§3 当场拍板；§4 于当日稍后的讨论中拍板，过程记在该节）。
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

## 4. 【已决策】永久重定向自动迁移 URL（提案 A）

> **2026-08-22 拍板：做提案 A。** 讨论过程与否掉 B/C 的理由记录在下，然后是定稿设计。

**现状**：热轮 89 次请求服务 77 个 feed，多出来的是 **9 个 301 + 4 个 308**。
`_http_fetch_feed` 用 `follow_redirects=True` 跟过去拿到了内容（功能正常），但存库的 URL 从不
更新，所以这 13 次额外往返**每轮都付**，永远。日志里能直接看到搬了家的：
`tianxianzi.me/atom.xml` → `www.tianxianzi.me/...`、`zdyxry.github.io` → `blog.zhouyiran.link`
（后者搬完还 404，属于 §3 那批）。

**决策依据**（原「三个问题」的答案，外加讨论中新增的一条）：

1. 13 次/轮的往返**本身不痛**——轮询并发，跳转摊在并发里对轮耗时无影响。性能不是做的理由。
2. 订阅行显示搬走的地址是真瑕疵，但单用户系统里单独不足以动手。
3. **真正的理由是转发地址会过期**（讨论中补上的论据）：301 这条「新地址在哪」的信息只在旧
   主机还活着时拿得到。`zdyxry.github.io` 是标本——旧址还在转发但目标已 404；
   `blog.extrawurst.org` 是另一种结局——域名直接没了，线索全无。今天不跟着走，旧域名到期后
   这个源就从「搬家了」退化成「死了」，要人肉重新找地址。迁移是趁转发还在时保住订阅连续性。
4. **B 被否是因为它不是更小的方案而是 A 的超集**：「点此迁移」按下去要执行的正是同一个三表
   事务——不走事务的替代（退订+重订）会让旧 `feed_url` 下的归档从时间线消失（时间线是
   `rss_entries JOIN subscriptions ON channel_id = feed_url`），还重吃一遍未读窗口。B 的危险
   部分一点没少，只多了端点、按钮和 13 次人工点击。
5. 与 §3 取向**不冲突**：§3 里服务器不做的判断是「源死没死」（主观）；301/308 是发布者自己
   的机器可读声明，内容已经跟过去成功 ingest，迁移只是让键追上事实——没有决定被代替、没有
   信息被丢弃，订阅行 URL 的变化读者看得见。

**定稿设计**（改动全落在已有缝隙里，无 schema 迁移、无前端改动、无 iOS 改动）：

- **判据 + 安全阀**：`resp.history` 非空**且每一跳都是 301/308**（混 302/307 不迁——临时的，
  今天跟过去明天就错了）；且**只在「200 + 解析成功 + ingest 完成」的轮次迁移**，304 轮与失败
  轮一律不动——保证迁的一定是「新地址确实在正常出 feed」的源，顺手挡掉「服务器配错一天 301」
  的大半风险。（曾议「同一目标连续两轮才迁」，判定为有了前一条后不必加。）
- **改动点**：
  1. `FetchResult` 加 `permanent_redirect_to` 字段；`_http_fetch_feed` 按上述判据填
     `str(resp.url)`。可注入边界的契约变更，测试的假 fetcher 顺手能造。（~10 行）
  2. `db.migrate_rss_feed_url(old, new)`：一个 `atomic()` 里三条 UPDATE——`rss_feeds.url`
     （PK）、`subscriptions.channel_id`（`source='rss'`，复合 PK 的一半）、`rss_entries.feed_url`
     （全部行）。入口先查**目标键已存在**（feed 或订阅任一）→ 放弃迁移，只写一条 `last_error`
     说明，让读者自己退订一个——合并两个 feed 的归档不是这里该做的决定。（~25 行）
  3. `_poll_feed` 200 路径尾部挂钩：**ingest 与 `record_rss_feed_success` 都完成之后**才调
     迁移——顺序是关键，先按旧 URL 记完状态再改键，反过来那条 UPDATE 会打空。（~5 行）
- `read_items` / `saved_items` / `search_index` 都按 entry id 走，**不受影响**。
- **已知会漂的一处**：`records.py` 的收藏快照存的是 envelope payload 本身，里面带着旧
  `feed_url`。快照的语义就是「当时的样子」，接受，不回填。
- 前端 `/s/rss/:feed` 路由用 `encodeURIComponent(url)` 做路径段，迁移后旧书签会 404 —— 单用户
  系统，接受。

**测试（`tests/test_rss.py`，TDD）**：四条——迁移成功（三表齐动、旧键查无）；混 302 链不迁；
目标已存在不迁且 `last_error` 有说明；304 轮携带重定向信息也不迁。

**风险**：本计划唯一动键的改动，事务写错即数据不一致——但事务本体只有三条 UPDATE + 一个
存在性检查，TDD 面积很小。

## 5. 分期与优先级

| 阶段 | 内容 | 为什么这个顺序 | 验收 |
|---|---|---|---|
| **P1** | §1 前端轮询条件 + §2 `last_error` NULL 不覆盖 | 两个都是 bug、都很小、互不相干，一起做一起发 | `uv run pytest` + `pnpm test` 全绿；生产开着订阅页看轮询退回 60s；下一个 304 轮后 `eurychen.me` 的警告仍在 |
| **P2** | §3 订阅行按失败优先排序（纯前端） | 依赖 P1 已经改过同一个组件，接着做省一次上下文 | `pnpm test` 全绿；生产订阅页 10 个坏源在最上面，读者关完开关后当日失败请求数归零 |
| **P3** | §4 永久重定向自动迁移（后端） | 唯一动键的改动，单独成期、单独发，出问题好归因 | `uv run pytest` 全绿（§4 的四条测试）；生产下一轮后 301/308 数归零（`zdyxry` 那类目标 404 的除外——它们迁不过去，归 §3 手动关），订阅行 URL 显示新地址 |

两个阶段都是小改动，可以合成一次发。**注意 `git push` master 即生产部署**，且当前仓库里已经
躺着两个未推送的 commit（`803ee69` OPML 挑选器、`fb4cdc0` lxml 依赖），P1 一发会连它们一起上。

**实际执行（2026-08-22/23）**：三期按顺序做完，各自一个 commit，**都还没有推送**。P3 的
「目标已存在」判据在本地真跑时发现措辞不准（退订会保留 `rss_feeds` 行与归档，所以占着目标键
的可能是一份**没有订阅**的归档），补了措辞与一条测试（`29662a8`）。§5 里写的生产验收要等推送
之后才能做，届时按这张表逐项核对。

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
