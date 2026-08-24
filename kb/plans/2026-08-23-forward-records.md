# 转发记录：我转过哪些条目，当时写了什么

状态：**已完成**（2026-08-23，后端 + Web；iOS 按计划留给下一轮）。落地记录见
`kb/docs/status-and-gaps.md` 同日条目；验收截图 `tmp/2026-08-23-forward-records/`。
唯一没跑的验收项是「真转一条」—— 那会往 `@reorx_share` 真发消息，交给用户自己跑。
前情：2026-08-23 的转发预览排查（见附录，**结论是不改转发渲染**）
范围：后端 + Web。**iOS 本轮不做**（1.0.0 还在审核队列，RSS 卡片已在等下一个 build）

## 背景

转发功能自 2026-07-27 起是 source-generic 的（`POST /api/forward {key, comment?}`），
但它是**一次性动作**：消息发进 `@reorx_share` 之后，condenser 这边不留任何痕迹。

于是有两件事查不到：

1. **这条我转过没有** —— 只能去频道里翻。RSS 一天上百条，重复转发是迟早的事。
2. **当时我写了什么** —— 评论只存在于 Telegram 那条消息的文本里，和条目的对应关系
   靠人眼认。而这些评论恰恰是这个 app 里最贵的东西：条目是别人写的，评论是我写的。

本任务把转发变成**有记录的动作**。

## 已确认的事实（不必重新调查）

### 转发路径

`TgManager.forward_item(key, comment)`（`condenser/tg.py:452`）是唯一出口，三条分支：

- 非 TG 条目 → `forward.render(key, comment)` 渲染 HTML → `send_message(parse_mode='html')`
- TG + 有评论 → `send_message(f'{comment}\n\n{t.me 链接}')`
- TG + 无评论 → `forward_messages`（原生转发）

返回 `{'status', 'mode', 'link'}`，`mode` = `'quote' if comment else 'forward'`。
**`target`（当时配置的频道）和 `sent_id` 只存在于函数内部**，外面拿不到。

HTTP 层是 `routers/messages.py:_forward`，两个端点（`/api/forward` 与遗留的
`/api/messages/{cid}/{mid}/forward`）共用它，异常翻译也在那里。

### 表与 schema 约定

- `SCHEMA_VERSION` 目前 **16**（`condenser/db.py`）。**新表 → 直接 `create_tables`，
  不写迁移**（v6/v7/v8/v10/v11/v15 的先例）。动 schema 前必读 `kb/docs/database.md`，
  尤其 `init_db` 的两个 load-bearing 顺序约束。
- reader state 一律 `(source, ref1, ref2)` 三元组键（`read_items` / `saved_items` /
  `hidden_items` / `item_feedback`），转换在 `items.py`。

### 快照：为什么必须存

`cleanup.py` 的保留期会删 X / RSS 的旧行。`records.py` 的模块文档已经把这条写成设计
原则：**记录是用户资产，必须能在源表消失后照常渲染**。转发记录同理 —— 一条三个月前
转发的 tweet，源行大概率已经被清了。

现成的快照能力在 `records.py`，但**构建逻辑埋在 `save_item()` 里**（四个 source 分支
各自 `db.add_saved_item(...)`），拿不出来复用。渲染侧 `render_item()` 则把
`is_saved` **写死成 True**。两处都要动（见目标设计 §2）。

### envelope 的标志位是怎么来的

`is_read` / `is_saved` **不是**统一注入的，而是每个 source 各自在 SQL 里
`LEFT JOIN` 出来的：`sources/hn.py:210` 和 `:309`、`sources/x.py:141`、
`sources/rss.py:69`、`sources/telegram.py:33`，五处，然后各自传进四个
`*_envelope()` 函数。

**新标志不要走这条路** —— 五段 SQL + 四个函数签名的改动，换一个位数。转发是低频动作
（生产上一天个位数），全量 key 集合几百行封顶，所以走**事后盖章**：一次查询取全部
已转发三元组，在 envelope 组装完之后统一打标。落点只有四个：

- `timeline.py:173`（`query_timeline`）、`timeline.py:212`（`query_new`）
- `search.py` 的结果渲染
- `records.py:list_rendered_records`

### 前端位置

- 路由在 `frontend/src/App.tsx`（`/saved` → `RecordsView` 是最近的邻居）
- 侧栏顶部导航在 `components/Sidebar.tsx`（Unread / All / Saved / Search / Filters /
  Subscriptions）
- 跨天跨源的列表行形态是 `components/timeline/DatedItemRow`（Saved 和 Search 都用它）

## 目标设计

### 1. schema v17：`forward_records`（日志形态）

新表，**一次转发一行**，自增主键。不是 `(source, ref1, ref2)` 复合主键 —— 同一篇文章
换个评论再转一次是真实行为，覆盖掉旧行就等于把「我当时怎么想的」删了。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | AutoField | 记录 id，也是 `DELETE` 的键 |
| `source` / `ref1` / `ref2` | Char/Int/Int | 条目三元组，和其他表同构。**非唯一**，建索引 `(source, ref1, ref2)` 供盖章查询 |
| `comment` | Text, null | 用户写的评论。空评论存 **NULL**（= 原样转发），别存 `''` |
| `mode` | Char | `'forward'` \| `'quote'`，和 API 返回的 `mode` 同义 |
| `target` | Char | 转发**当时**的 `app_meta.forward_channel`。这个值会变，记录里必须是快照 |
| `message_id` | Int | 落地消息的 id |
| `link` | Char | t.me 链接。**故意和 target+message_id 冗余**：`link` 是 UI 要打开的东西，`target`+`message_id` 是将来「撤回这条已发布消息」（`client.delete_messages`）需要的东西。存 link 也避免了 `forwards.py` 反过来 import `tg.py`（`tg.py` 已经 import 了 `forward.py`，会成环） |
| `raw_data` | Text | 条目快照 JSON，`saved_items.raw_data` 的同款 |
| `created_at` | DateTime | 转发时间 |

`SCHEMA_VERSION` → 17，changelog 补进 `kb/docs/database.md`（最新在前）。

### 2. 快照能力从 `records.py` 里解出来

- 抽出 `build_item_snapshot(key: ItemKey) -> Optional[dict]`：现在 `save_item()` 里那
  四个 source 分支原样搬过去，`save_item()` 改成调它 + `db.add_saved_item(...)`。
  **RSS 那段 `with_content=True` 的注释和理由整段跟着走**（plan 2026-08-23 §5 (a)）。
- `render_item(rec, read_triples, feedback=None, is_saved=True)` 加参数：转发过的条目
  未必被收藏，写死 True 会让转发视图里每张卡都亮着书签。默认值保持 True，收藏路径
  一个字不用改。
- 两个函数都要能吃「只有 `source/ref1/ref2/raw_data`」的鸭子类型行（`SavedItem` 和
  `ForwardRecord` 都满足），别按 `db.SavedItem` 类型判断。

### 3. 写入点：发送成功之后，且**记账失败不能让转发失败**

在 `TgManager.forward_item` 里、`send_message` / `forward_messages` 返回之后写。

⚠️ **这里要开一个 try/except，与「低层函数不写 try/except」的项目规则相反，理由必须
写进注释**：消息已经发到 Telegram 了，外部副作用不可撤销。此时如果本地记账抛异常导致
接口 500，客户端会认为没发出去，用户点第二次 —— 于是频道里出现两条一样的消息。
所以：`except Exception: log.exception(...)`，接口照常返回 200。**丢一行记录，好过
多发一条消息。**

快照走 §2 的 `build_item_snapshot(key)`；拿不到（源行已消失）就存 `None`/`{}` 并
照常记录，转发本身不受影响（TG 原生转发路径根本不读源表）。

### 4. 新模块 `condenser/forwards.py`（`records.py` 的兄弟）

只放读侧和盖章，写侧在 `db.py`（避免 `tg.py` → `forwards.py` 的环）：

- `db.add_forward_record(...)` / `db.list_forward_records(limit, offset)` /
  `db.delete_forward_record(id)` / `db.forwarded_triples() -> set[tuple]`
  —— 一贯的「SQL 全在 db.py」。
- `forwards.list_rendered(limit, offset)`：记录 → `{record: {...}, item: envelope}`，
  倒序。envelope 从 `raw_data` 渲染，**不查源表**。快照缺失的行渲染成 `item: null`，
  由前端退化显示（评论和链接仍然有，那才是记录的主体）。
- `forwards.stamp(items: list[dict])`：给 envelope 打 `forwarded_by_me`。

⚠️ **字段名不能叫 `is_forwarded`** —— telegram payload 里已经有一个
`is_forwarded`，意思是「这条消息是从别处转发来的」（`MessageCard` 的转发框就靠它）。
两个含义正相反的同名字段一定会被读错。定名 **`forwarded_by_me: bool`**，顶层
envelope 字段，和 `is_read` / `is_saved` 并列，缺省 `false`。

### 5. API（`routers/` 里新开 `forwards.py`，`require_auth`）

- `GET /api/forwards?limit=30&offset=0` → `{'items': [{record, item}], 'has_more': bool}`
- `DELETE /api/forwards/{id}` → 删本地记录，**不动 Telegram 上那条消息**（文案要说清）
- envelope 多出的 `forwarded_by_me` 对老客户端无害（Swift `Codable` / TS 都忽略未知键）

### 6. Web

- **`/forwards` 视图** + 侧栏一项（放在 Saved 下面，图标 `Repeat2` —— `MessageStatsRow`
  已经用它表示转发数，保持同一套语汇）。
- 新组件 `components/forwards/ForwardRecordRow`：包住 `DatedItemRow`，在条目**上方**
  渲染这次转发的元信息 —— 转发时间、评论原文（无评论则显示「原样转发」）、「打开」
  链接、删除按钮（`ConfirmDialog`，文案点明只删记录）。评论是记录的属性不是条目的属性，
  所以画在条目外面。
- 分页：offset 无限滚动，照 `SearchResults` 的形状。
- **卡片角标 `ForwardedBadge`**：`forwarded_by_me` 为真时在时间那一行画一个小
  `Repeat2`（native `title` 提示「已转发到我的频道」）。四个卡片
  （`MessageCard` / `HnCard` / `XCard` / `RssCard`）各引一次。
- 转发成功后 invalidate `['forwards']` + 各 item cache（`lib/itemCaches.ts` 的
  `patchItem`，把 `forwarded_by_me` 打成 true），角标立刻亮。
- `frontend/CLAUDE.md` 的组件清单要在同一次改动里补行（那份文件的维护规则）。

## 实施顺序（BDD：先写行为测试）

1. `tests/test_forward_records.py` —— 先写，全红：
   - 转发成功 → 落一行，`mode` / `comment` / `target` / `link` / 快照都对
   - 空评论 → `mode='forward'`，`comment` 为 NULL
   - 同一条目转两次 → **两行**，各带各的评论
   - **记账抛异常 → 接口仍 200**，且 `send_message` 只被调用一次（回归护栏）
   - 源行删掉后 `GET /api/forwards` 仍能渲染（快照生效）
   - `DELETE /api/forwards/{id}` 删记录，且**没有**调用 Telegram 的 `delete_messages`
   - timeline envelope 的 `forwarded_by_me`：转过的 true，没转过的 false
   - 老端点 `/api/messages/{cid}/{mid}/forward` 走同一条路，同样落记录
   （复用 `tests/test_forward_multi_source.py` 的 `_armed()` mock 夹具）
2. schema v17 + `db.py` 的表和 CRUD
3. `records.py` 的两处解耦（§2），跑一遍 `tests/` 确认收藏路径没回归
4. `forward_item` 的写入 + `forwards.py` + router
5. 四个盖章落点
6. 前端：视图 → 侧栏 → 角标 → 组件清单
7. `kb/docs/database.md` 补 v17 changelog；`CLAUDE.md` 补 `forwards.py` 模块行；
   `kb/docs/status-and-gaps.md` 追加本次落地记录

## 验收

- `uv run pytest` 全绿（当前基线在 `kb/docs/status-and-gaps.md` 尾部）
- `cd frontend && pnpm test` 全绿
- 浏览器走查（`scripts/dev-browser-login.sh`，**确认后端带 `--reload`**）：
  真转一条 → 侧栏「转发」里出现，评论原文在 → 时间线上那张卡出现角标 →
  删除记录后角标消失、频道里的消息还在
- 截图归档到 `tmp/2026-08-23-forward-records/`，报告里写出路径
- 走查完 `mac-dev-cleanup --only browser`

## 未采纳 / 待定

- **详情抽屉里列明细**：`ItemDetailPane` 里转发按钮的正下方列出这条的历史转发，是最
  自然的位置，而且字段已经在 envelope 里、成本接近零。本轮没选，留给下一轮判断。
- **iOS**：Kit 的 `TimelineItem` 加 `forwardedByMe`、卡片角标、转发记录 tab。等
  1.0.0 出审核队列后和 RSS 卡片一批发。
- **把 `link` 换成纯函数算**：`tg._sent_message_url(target, message_id)` 是纯函数，
  理论上不必存 `link`。没这么做的理由见 §1 表格（import 成环 + 记录即快照）。
- **转发时自动标记已读/收藏**：没做。转发是发布动作，不是阅读状态。

---

## 附录：转发预览为什么不生成（2026-08-23 调查结论，**不改代码**）

起因：转发到频道的消息，链接的原文经常不出预览卡片。怀疑是发送时漏了控制预览的参数。

**不是参数问题。** Telethon 的 `send_message(link_preview=True)` 是默认值，
`tg.py:476` 没有覆盖它，请求里 `no_webpage=False`。

证据链：

1. **现场**（`@reorx_share` id=7013，2026-08-23 03:44:59，一条带评论的 RSS 转发）
   的 media 是 `MessageMediaWebPage(WebPageEmpty)`。没请求预览的消息是 `media=None`
   （同频道 7006、6990 就是），`WebPageEmpty` 的意思是**请求了、Telegram 去抓了、
   抓回来是空的**。
2. 用 MTProto 的 `messages.getWebPage`（服务端生成预览跑的就是这个）单独探测同一个
   URL，不发消息：`https://www.kawabangga.com/posts/7314` → `WebPageEmpty`，
   整站首页也是。同一时刻 `github.com/...` 正常出卡片。
3. **隐藏链接不是原因**：`<a href>`（`text_url` entity）照样能出预览 —— 同频道
   id=6988 那条 HN 转发，标题是隐藏链接，出了完整的 GitHub 卡片。
4. **规模**：从生产库取最近 400 条 RSS entry，按域名去重探测 24 个站 —— **9 个站
   拿不到预览**；按条目数加权，**302 条里 154 条（51%）的链接 Telegram 生成不出
   卡片**。挂掉的是 `blog.xinshijiededa.men`(73)、`blog.est.im`(20)、
   `blog.codingnow.com`(15)、`sinyalee.com`、`kawabangga.com`、`shuiba.co`、
   `blog.xulihang.me`、`tumutanzi.com`、`yachen.com` —— 基本都是**页面没有
   `og:*` / `meta description` 的个人博客**。对照组：`danluu.com`（无 og，美国主机）
   同样空，`rfc-editor.org`（无 og 但有 meta description）正常出卡。所以是**目标站
   给不出元数据**，不是地域封锁，也不是我们的消息形态。

客户端能控制的只有「要/不要预览」，抓不抓得到是 Telegram 服务端的事，**没有参数能修
这件事**。要让消息不难看只能自己把描述写进正文（RSS 有 AI 摘要 + `content_excerpt`，
HN 有 ingest 预取的 `link_previews`），**本轮明确不做**。

复现工具留在 `tmp/`（一次性，不进版本库）：`tmp/inspect_forward_previews.py`
（只读拉某频道最近 N 条，报告每条的 entities 和 webpage 状态）、
`tmp/probe_webpage.py`（对任意 URL 跑 `messages.getWebPage`，不发消息）。
