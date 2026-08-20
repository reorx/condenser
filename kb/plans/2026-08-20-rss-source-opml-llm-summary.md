---
created: 2026-08-20
tags:
  - rss-source
  - multi-source
  - llm-summary
  - plan
---

# RSS 源 —— OPML 导入 + LLM 摘要 实施计划

> 起因：在多源架构（Telegram / HN / X）上增加第四个源 RSS，支持 OPML 批量导入与
> 手动按 URL 添加，并对文章自动生成 LLM 摘要。设计目标场景是 **100 个 feed 订阅**。
>
> 可行性结论（2026-08-20 头脑风暴定案）：架构上是现成的——`subscriptions` 复合主键、
> item envelope、`SourceUnit` 联邦合并、cleanup 规则对象、attributes 的 LLM 计费围栏，
> 每一块都有可直接照抄的先例。RSS 比 HN 和 X 都简单：标准协议、无 probe、无判定、
> 无反爬。总量估计 4-6 个 session。

## 0. 已定决策（用户拍板，不再重议）

1. **摘要原料只用 feed 自带内容**，纯文本长度 > 200 字符才触发摘要；短文直接显示原文。
   全文抓取（readability/trafilatura）**不做**，留作后续增强——这把新依赖、付费墙、
   反爬失败面整个砍掉。
2. **RSS 条目全部进聚合时间线**（All/Unread），与 Telegram/HN 同等地位。无 admission、
   无 verdict。
3. **存量条目处理**（OPML 导入与单个新订阅一视同仁）：条目**全部入库归档**；
   `published_at` 距今**超过 7 天**的直接标已读；一周内的保持未读。**只有未读条目做
   摘要**，且摘要按每轮 batch 上限限流逐步消化，避免导入时并发爆炸。
4. **卡片只显摘要**（标题 + 摘要），详情抽屉/原文链接看全文；无摘要（短文、失败、
   未开启）退化为原文截断。

## 1. 数据模型（SCHEMA_VERSION 15，两张新表，纯 `create_tables` 零迁移）

### 1.1 `rss_feeds` —— feed 级抓取状态

| 列 | 说明 |
|---|---|
| `url` TEXT PK | feed URL，也是订阅的 `channel_id`（"读者输入什么就用什么作键"，X handle 先例） |
| `title` / `site_url` | 首次成功抓取回填（X `_learn_user_identity` 先例） |
| `etag` / `last_modified` | 条件请求凭据（`If-None-Match` / `If-Modified-Since`） |
| `fetched_at` | 最近一次抓取（无论 200/304） |
| `last_error` TEXT / `error_count` INT | 最近错误与连续失败计数，成功清零；只记录，不自动退订 |

订阅行：`subscriptions(source='rss', channel_id=<feed url>)`。`channel_id` 是
BareField，HN 已存字符串键，无迁移。`name` 由首次抓取回填 feed 标题，回填前前端
显示 URL（`XSubscriptionRow` 的 `@handle` 回退先例）。

### 1.2 `rss_entries` —— 条目归档

| 列 | 说明 |
|---|---|
| `id` INTEGER PK AUTOINCREMENT | item key 的 ref1 |
| `feed_url` TEXT | 归属 feed |
| `guid` TEXT | 去重键，三级回退：feed 的 `<guid>`/`id` → `link` → `sha256(title + published)` |
| `title` / `link` / `author` | 元数据 |
| `content` TEXT | feed 自带 HTML（`content:encoded` 优先，回退 `description`/`summary`） |
| `published_at` DATETIME | feed 声明的发布时间，可空 |
| `first_seen_at` DATETIME | 我们首次见到的时间 |
| `summary` TEXT / `summary_model` TEXT / `summary_attempts` INT | LLM 摘要，非规范化落在条目行（`hn_stories.preview` 先例）；`summary_model` 即 `model_tag` 契约——换模型时旧摘要重做、不迁移；`summary_attempts` 上限 3（`PREVIEW_MAX_ATTEMPTS` 先例） |

唯一索引 `(feed_url, guid)`，ingest 以此幂等（insert-or-skip；RSS 条目编辑不常见，
v1 不做 update-in-place，条目以首见版本为准）。

### 1.3 item key

`rss:{entry_id}` ↔ `(rss, entry_id, 0)` —— HN 的形状。read / save / hide /
feedback（表是通用的，v1 不接 UI）/ 搜索 / 详情面板全部免费继承。唯一例外是
**收藏快照**：`records.py` 的 `save_item`/`render_item` 按 source 分发（else 落到
hn），需要加显式 rss 分支——快照存 envelope payload 本身（X 先例）。

## 2. 抓取（`condenser/rss.py`，`RssManager`，`HNManager` 同款）

- 挂 `app.state.rss`，lifespan 启停；`CONDENSER_RSS_ENABLED=false`（**默认 false**，
  部署顺序需要，见 §7）时循环不启动、订阅端点 503（HN 先例）。
- 轮询间隔 `CONDENSER_RSS_POLL_MINUTES`（默认 30）。每轮遍历启用订阅的 feed，
  `asyncio.Semaphore(CONDENSER_RSS_FETCH_CONCURRENCY)`（默认 5）限并发；条件请求下
  多数轮次 304 零成本，100 个 feed 摊在轮内对共享 asyncio loop 是零负担。
- HTTP 经可注入的 `fetch_feed`（HN `fetch_json` 先例，测试不碰网络）；超时默认 20s。
- 解析用 **feedparser**（唯一新增依赖，纯 Python，容错是它的本职）。RSS 2.0 / Atom /
  RDF 都由它兜住；`bozo` 但有条目时照常入库并记 `last_error`。
- **单 feed 失败只记 `last_error`/`error_count`，绝不沉整轮**；`_loop` 外层 catch-all
  守护（HN Phase 1 review 教训）。
- `kick()`：订阅/导入后立即触发一轮（`call_soon_threadsafe`，HN 先例）。
- **排序时间戳**：`published_at`，两种情况钳到 `first_seen_at`——缺失，或超前于
  `first_seen_at + 30min`（feed 里未来时间戳的垃圾数据不允许长期霸占时间线顶部）。
  钳制在 provider 的 SORT SQL 层做（`COALESCE`/`MIN`），不改写归档值。
- **入库即执行未读窗口规则**（§0.3）：新条目 `published_at`（缺失用 `first_seen_at`）
  距今超过 `CONDENSER_RSS_UNREAD_WINDOW_DAYS`（默认 7）→ ingest 时同事务写
  `read_items`。规则对首轮和日常轮一视同仁——日常轮里正常新文章都在窗口内，该规则
  实际只在导入/新订阅时起作用，但不需要为"首轮"单设分支。
- 每轮尾部挂摘要管道（§3），再更新 `app_meta` 的轮次统计（`x_*` 键先例：
  `rss_last_poll_at`、new/error 计数）供 status 端点读取。

## 3. 摘要管道（`condenser/summary.py`）

跟在 `poll_once` 尾部，**不单开循环**——RSS 内容只随轮询到达，尾挂即可（
`_fill_previews` 的位置；将来抓全文再升级成独立 worker）。

- **候选**：未读（无 `read_items` 行）+ `summary IS NULL` + `summary_attempts < 3` +
  HTML 剥离后纯文本长度 > 200 字符。新→旧排序，每轮最多
  `CONDENSER_SUMMARY_BATCH`（默认 20）条——OPML 导入的积压（100 feeds × 一周窗口内
  约 3 条未读 ≈ 300 条）在几小时内自然排完。
- **计费围栏照抄 attributes 四件套**：
  1. `CONDENSER_SUMMARY_ENABLED`（默认 true，但没有 key 等于关）
  2. 独立 `CONDENSER_SUMMARY_API_KEY`，**不回落到 embedding/attr 的 key**——设 key
     即是开机动作，部署代码不产生花费
  3. 每轮 batch 硬上限
  4. `/api/rss/status` 报待摘要计数与已花费计数
- **一条一请求，绝不批发**（attributes 的错位教训：四个答案对五篇文章，gap 之后
  全部错位）。
- 模型/端点：`CONDENSER_SUMMARY_MODEL`（默认 qwen-flash 档）+
  `CONDENSER_SUMMARY_BASE_URL`（默认 DashScope OpenAI 兼容端点），复用
  `embedding.py` 的 OpenAI 兼容客户端形状。输入截断到
  `CONDENSER_SUMMARY_MAX_INPUT_CHARS`(默认 8000) 字符。
- 产出**中文摘要，2-3 句**，prompt 固定指令"无论原文语言，用中文摘要"。存入
  `summary` + `summary_model`。
- 失败 `summary_attempts += 1`，≤3 次后放弃，卡片永久退化为原文截断——**逐条降级**，
  不影响其它条目（t.co 展开的 per-entry degradation 先例）。API 整体不可用时整轮
  跳过且**不 bump attempts**（HN preview 的"新鲜负缓存不烧重试"教训的同类：不为
  环境故障消耗条目的重试预算）。
- 量级预估（推测值，上线后以 status 计数核实）：稳态 300-800 条/天 × ~2K token，
  qwen-flash 档每天几分钱。

## 4. 时间线（`condenser/sources/rss.py` provider）

- 注册进 `items.py` 的 source 模式 + `timeline.SOURCES`。分页/游标/day 分组/未读计数/
  `/timeline/new` 锚点全部照 `sources/hn.py` 的形状实现，anti-join `hidden_items`。
- envelope payload `rss`：`{feed_url, feed_title, title, link, author, content,
  summary}`。`datetime` = 钳制后的排序时间戳（§2）。
- **聚合**：全量进入（§0.2）。`bulk_read_scope` 烧全部 RSS 未读——视图显示什么就烧
  什么，这里视图=全部。
- `GET /api/sources` 的 RSS 组：每 feed 一行（name/unread），100 行侧栏可滚动，
  v1 不做折叠分组之外的特殊处理（源组折叠已有 `useCollapsedSources`）。

## 5. 订阅 API + OPML（`condenser/routers/rss.py`）

- `/api/sources/rss/subscriptions` CRUD，HN router 同构：POST = 建订阅 + 建/复活
  `rss_feeds` 行 + `kick()`；重复订阅 → 复活暂停行；PATCH enable/pause；DELETE 退订
  （保留归档，`delete_channel_messages` 的"言明保留什么"docstring 惯例）。
  `CONDENSER_RSS_ENABLED=false` → 503。
- `POST /api/sources/rss/opml`：body 为 OPML 文本（前端读文件后作为 text 上传）。
  `xml.etree` 手解——只认 `outline[@xmlUrl]`，递归展开嵌套分组（分组层级丢弃，
  v1 不做文件夹）；逐条走与单订阅相同的建订阅路径；返回
  `{added, skipped_existing, invalid}`。导入后一次 `kick()`。
- OPML **导出**留作后续（~20 行，v1 不做）。
- `GET /api/rss/status`（对齐 `/api/hn/status` / `/api/x/status` 的路径惯例）：
  `source_enabled`、feed 总数/错误 feed 数、`rss_last_poll_at`、待摘要/已摘要计数、
  summary enabled（key 是否配置）。

## 6. Web UI（`frontend/`）

- 订阅页 `RssSection`（`HackerNewsSection`/`XSection` 并列）：URL 手动添加框、
  OPML 上传按钮（`<input type=file>` 读文本 POST）、feed 行 = 标题（回退 URL）/
  未读/暂停/退订/错误徽标（`last_error` tooltip）。
- 侧栏 RSS 源组（`SidebarSourceGroup` 已通用，接数据即可）。
- **`RssCard`**：feed 名 + 相对时间为 header（字母色块头像，favicon 代理留作后续）；
  标题加粗链接原文（in-app 打开走 `openURL` 惯例）；正文 = `summary`，无摘要则
  DOMPurify 消毒后的 `content` 截断（HN self-post 的 `lib/sanitize.ts` 先例 + 字符
  阈值 more 展开）。摘要角落一个小标识（如「AI」微标）与原文截断作视觉区分。
- 详情抽屉 `ItemDetailPane`：基本信息 + 消毒全文 + 链接预览（`preview.py` 通用，
  entry 的 `link` 即 PaneTarget URL）+「打开原文」。转发走 `forward.py` 的 HN 形状
  （标题行链原文；RSS 没有第二个讨论链接，单行即可）。
- 乐观更新/已读/收藏/隐藏全部走既有 key 驱动 hooks（`lib/itemCaches.ts` 三处缓存
  同步已通用）。

## 7. iOS 与部署顺序 ⚠️

聚合=全部 ⇒ 服务端一开闸，现装 iOS 在聚合时间线渲染**空行**（X Phase 2 教训：卡片
dispatch 不认识的 source）。且 `git push` 即生产部署。因此：

1. 服务端各阶段**随时可 push**——`CONDENSER_RSS_ENABLED` 默认 false，生产不启用
   就没有 rss envelope，在审的 App Store 1.0.0 不受影响。
2. iOS 补 `RssCard` + detail sheet（Kit：`RssEntry` payload 模型 + 测试；App：卡片
   dispatch 加 rss 分支；`hnPlainText` 同类的 HTML→纯文本已有先例），`make device`
   侧载到用户手机——单用户系统，不依赖 App Store 审核。
3. 侧载完成后才在生产 compose 模板加 `CONDENSER_RSS_ENABLED=true` + summary key，
   ansible 跑一遍（env 在 role 模板，hookploy 只 repin 镜像——既有运维事实），
   然后导 OPML。

## 8. 搜索 / 清理

- **搜索**：`search.index_rss_entry`（title + 剥离 HTML 的 content + summary），
  ingest 时写入；`TOKENIZER_VERSION` 不变（文档管道无 tokenizer 改动）。
  `search.ensure_index` 的重建路径加 `_rebuild_rss`（与既有各源 rebuild 并列）。
  退订不删归档故文档保留；被清理规则删除的条目**同事务删文档**（"删除必须三处强制"
  的政策：这里是清理一处 + 无 rebuild 复活路径——重建只读存活行，天然一致）。
- **清理**：`RssRetentionRule` 加入 `cleanup.DEFAULT_RULES`（规则对象即插）。X 语义
  原样：`first_seen_at` 超过 `CONDENSER_CLEANUP_RSS_RETENTION_DAYS`（默认 30）且
  无 read/save/hide/feedback 行 → 删；读过/收藏/隐藏永久保留。已知接受：导入时
  标已读的存量永久保留（文本 KB 级/条，~百 MB/年 上限，接受；`cleanup/status`
  可观测）。

## 9. 测试（BDD，行为先行）

新增 `tests/test_rss.py` + `tests/test_rss_summary.py` + `tests/test_rss_timeline.py`，
fixtures 取自真实 feed 样本（RSS2.0 / Atom / 带 `content:encoded` / 无 guid /
未来时间戳 / bozo 各一）。必须覆盖的行为：

1. ingest 幂等（guid 三级回退各一例；同 guid 重推 0 新增）
2. 一周未读窗口：旧条目入库即已读、新条目未读；窗口规则对 OPML 导入与日常轮一致
3. 条件请求：304 轮不触碰条目；etag/last_modified 回写
4. 单 feed 失败不沉轮、`error_count` 累积与清零
5. 摘要：>200 字符才触发；只摘未读；batch 上限；一条一请求；失败 bump attempts、
   API 整体故障不 bump；无 key 全程不调用（围栏）
6. 排序钳制：缺失/未来 `published_at` 钳到 `first_seen_at`
7. timeline：聚合含 RSS、游标翻页、`/timeline/new`、bulk-read、hidden anti-join、
   read/save/hide 经 `rss:{id}` key 全通
8. OPML：嵌套分组展开、坏 XML 400、重复 skip、返回计数
9. 503 门（`CONDENSER_RSS_ENABLED=false`）
10. 清理规则：老未读删、读过/收藏保留、搜索文档同事务删
11. 搜索：标题/正文/摘要可搜、中文 bigram 路径复用

## 10. 分期

| 阶段 | 内容 | 验收 |
|---|---|---|
| **Phase 1** 后端 ingest | schema v15 + `RssManager` + OPML + 订阅 API + status | 真实 feed 样本端到端入库；`uv run pytest` 全绿 |
| **Phase 2** 时间线 + Web UI | provider + 注册 + `RssSection`/`RssCard`/详情/侧栏 + 搜索接入 | 浏览器 walkthrough（截图归档 `tmp/<date>-rss-phase2/`） |
| **Phase 3** 摘要管道 | `summary.py` + 围栏 + status 计数 + 卡片摘要展示 | 真实 DashScope 小批量端到端；限流实测 |
| **Phase 4** iOS + 开闸 | Kit payload + `RssCard`/sheet + 侧载；生产 enable + 导 OPML + 清理规则观察 | 真机聚合时间线正常渲染；模拟器 walkthrough 归档 |

每阶段独立可部署（enable 关着），plan 完成后按惯例更新根 CLAUDE.md 的模块表与
Status 段。

## 11. 明确不做（YAGNI，留作后续）

- 全文抓取 + readability 抽取（摘要质量增强的第一候选）
- favicon 头像代理（v1 字母色块）
- OPML 导出、feed 文件夹/分组
- 按 feed 的 `aggregate` 开关（全进聚合是决策；若 100 feed 实测淹没时间线，X 的
  `config.aggregate` 模式是现成的退路，一个 PATCH 即可加）
- RSS 条目的 verdict/feedback UI（表已通用，接 UI 是一次独立决策）
- 条目编辑跟踪（update-in-place）

## 12. 阶段 1 实施记录（2026-08-20）

**已完成，628 后端测试全绿（新增 33 个），真实 feed 端到端跑通。** 验收物料
`tmp/2026-08-20-rss-phase1/`（可复跑，见其 README）。落地的东西：schema v15
（`rss_feeds` / `rss_entries`，纯 `create_tables`）、`condenser/rss.py`（`RssManager`
+ feedparser 解析 + OPML 手解）、`condenser/routers/rss.py`、`items.py` 的 `rss:{id}`
键、config 五个开关、app 接线。**没**落地的（按分期，且都有硬理由）：时间线 provider
与搜索接入留 Phase 2 —— `search.render` 不认识 `rss`，现在写文档等于让搜索结果
指向空气；`records.py` 的 rss 分支同理；status 的摘要计数留 Phase 3。

### 计划没写、实现时定的（都在代码注释里说明了理由）

1. **PATCH/DELETE 用 `?url=` 查询参数，不用路径段。** 这个源的键是 URL，自带斜杠
   和查询串，做不成路径段。其余（订阅即启用、暂停、503 门、退订保留归档）与 HN/X
   同构。OPML 走 JSON 字段 `{opml}` 而不是裸 text body，跟本项目其它端点一致。
2. **`parse_feed` 扔到 `asyncio.to_thread`。** feedparser 是纯 Python，100 个 feed
   一轮会把这个进程唯一的事件循环（FastAPI + TG 监听 + HN 采样 + 判定共用）卡住。
3. **「不是 feed」是独立错误类。** 实测确认：一个 HTML 错误页在 feedparser 里解析得
   干干净净——**不设 bozo**、零条目。不单独判，订阅就会永远表现成「这个 feed 从不
   发文」。判据是 `没有条目 且 没有 version`。
4. **bozo 但有条目 → 记 `last_error`、`error_count` 保持 0。** 坏 XML 里 feedparser
   照样能捞出条目，为一个野生 `&` 丢掉真内容是更糟的失败；它是警告不是待重试的故障。
5. **无法成键的条目丢弃并计数**（抄 `x.py`）：`guid`/`link`/`sha256(title+published)`
   三级全空的条目连下一轮都认不出自己，归档到「空值的哈希」下会让这类条目全部变成
   同一条。
6. `rss_feed_error_count` 只数**已订阅**的 feed —— 退订保留抓取状态（etag 留着，
   重新订阅可续传），已丢掉的 feed 上的陈年错误不是读者的问题。

### 实跑抓到的 bug —— 注入式单测看不见的那类

**httpx 把 304 归为重定向，`raise_for_status()` 会抛。** 一轮健康轮询最常见的结果
「没变化」因此被记成 feed 失败，几轮后每个正常 feed 都挂错误角标。单测注入了
`fetch_feed`，天然绕过抓取器，所以只有真网络那一跑能发现。已修（304 在
`raise_for_status` 之前返回），并补了传输层回归测试（`httpx.MockTransport`），
连带把「5xx 必须抛」的另一半也扎住。**教训可推广：凡是可注入的 I/O 边界，注入之外
必须另有一条真实现的测试路径。**

### 实测数据（下阶段调参的基线）

三个真实 feed：冷轮 0.71s / 111 条入库，热轮 0.20s / 新增 0（两个 304）。一周未读
窗口在真数据上正是预期形状——simonw 30 条跨窗口边界、一半自动已读；reorx 51 条全是
二月的，全部归档零未读；HN 30 条全在窗口内。**这三个 feed 里有一个（HN）既不给
etag 也不给 last-modified**，所以「多数轮次 304 零成本」是趋势不是保证，Phase 3 估
摘要量时别按 100% 命中算。

## 13. 阶段 2 实施记录（2026-08-20）

**已完成，649 后端 + 169 前端全绿（新增 21 + 10），八个真实 feed 的浏览器 walkthrough
跑通。** 验收物料 `tmp/2026-08-20-rss-phase2/`（可复跑，见其 README）。落地的东西：
`condenser/sources/rss.py` provider、`items.py` 的 rss envelope、`timeline.py` 注册、
`db.mark_read_bulk` 的 rss 分支、`records.py` / `forward.py` 的 rss 分支、搜索接入
（ingest 钩子 + rebuild + 渲染 + 按 feed 收窄）、`cleanup.RssRetentionRule`、
`/api/sources` 的 RSS 组，以及前端整套（`RssCard` / `RssSection` / `RssSubscriptionRow` /
`SidebarRssFeedLink` / `RssGlyph` / 详情抽屉 / 搜索范围菜单 / `/s/rss/:feed` 路由）。

### 计划没写、实现时定的

1. **排序时间戳算在 SQL 里，算完的值随 envelope 走（`rss.sort_at`）。** §2 说钳制在
   provider 的 SORT SQL 层做，但收藏快照是脱离源表回放的——规则活在 SQL 里，快照就
   必须带着**结论**，否则 Python 里要再实现一遍同一条规则，两份迟早会漂。
2. **`feed` 参数放宽到 2000 字符，并且必须跟 `source` 一起出现。** 这个源的 feed key
   是 URL，塞不进原来 64 字符的上限；而两个多 feed 源的 key 形状完全不同（X 是 handle，
   RSS 是 URL），服务端脱离 source 读不懂 feed。搜索端点因此从「feed 不给 source 就当
   成 x」改成 422，`normalize_feed` 也只对 x 做——对 URL 做小写化会改掉它指向的东西。
3. **清理规则一并落在本阶段。** §8 把搜索和清理写在同一节，而 Phase 4 的验收里写的是
   「清理规则观察」——它得先存在。X 的语义原样搬：`first_seen_at` 超 30 天且没有
   read/save/hide/feedback 行才删，删的时候同事务扫搜索文档。
4. **`search.TOKENIZER_VERSION` 3 → 4。** §8 说 tokenizer 没改所以不用动，但那个版本号
   实际的含义是「索引在当前这套管道下重建过」——加一个源，存量归档就以完全相同的方式
   缺失：悄无声息，而且只对没人想到去查的那些行。加个源就 bump，注释里写清楚了。
5. **`/s/rss/:feed` 用 `encodeURIComponent(url)` 做路径段。** 编码后没有字面斜杠，正好
   占一个 segment。地址栏难看，但为了好看的路由再造一个 id 就等于永远要维护两套键。

### walkthrough 抓到的两个前端问题

都是「测试全绿但用起来不对」的那类，详情见验收 README：导入后订阅行不会自己刷新
（`refetchInterval` 改成函数，还有 feed 没抓过就 5 秒一轮，抓完退回 60 秒，条件自己
会结束）；feed 正文里的图片按原尺寸铺满、一条比一屏还高（`[&_img]:max-h-80` 封顶）。

### 实测数据

八个真实 feed 一轮冷抓：280 条入库、7 成功 1 失败（matrix67 的 SSL 证书链坏了，真坏
不是安排的）、**未读 3 条**、搜索文档 280。那个 3 就是一周未读窗口在博客类 feed 上的
样子——博客不是新闻源，280 条里只有 3 条是最近一周的。Phase 3 估摘要量要按这个来：
**稳态下需要摘要的是「一周内的未读」，不是归档总量**。
