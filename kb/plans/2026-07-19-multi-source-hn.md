---
created: 2026-07-19
tags:
  - plan
  - multi-source
  - hackernews
  - api-redesign
  - frontend
  - ios
---

# 多信源架构 + Hacker News 信源

condenser 立项定位是「压缩信息噪音的阅读器」，而非 Telegram 专用工具。本计划把架构升级为多信源，并落地第一个新信源：**Hacker News 每日 top 采样存档**（对标 hckrnews.com 的产品形态，但数据完全自采，不依赖第三方）。

## 决策记录

与用户讨论后确定（2026-07-19）：

| 决策点 | 结论 | 理由 |
|---|---|---|
| HN item 的 timeline 排序时间 | **首次上榜时间**（`first_seen_at`），非 story 提交时间 | append-only，不会插入 timeline 历史中间；cursor 分页、`/timeline/new` 轮询、unread 语义与 Telegram 完全一致；也是 hckrnews 的排法。卡片上仍展示提交时间 |
| 存储范围 vs top N | **全存进过首页的 story，读取时按配置筛** top 10 / 20 / 半数 / 全部 | 存档全量、读取压缩，符合 condenser 理念；N 事后可调；当日进行中 top N 本来就在变化，query-time 排名最自然 |
| read / saved 数据层 | **统一表 + 一次性迁移**（`read_items` / `saved_items`，废弃 `read_messages` / `telegram_records`） | 查询与 API 层最干净，后续加信源零改动；已有 `SCHEMA_VERSION` 机制承载迁移 |
| 全局关键词过滤器作用于 HN？ | **暂不**，维持仅 Telegram | HN 过滤（domain / 关键词）后续单独设计，见「后续方向」 |
| HN 采样的触发方式 | **订阅驱动**：用户添加 HN feed 订阅后才开始采样；退订停止采样但保留数据 | 与 Telegram 的订阅语义统一——信源下有订阅才产生数据；iOS 信源菜单、web 侧边栏都按「已添加的信源」渲染（2026-07-19 补充讨论） |
| `channel_id` 语义泛化 | 变为 RSS 意义上的 channel 概念：**订阅在其信源内的 id**，类型 any，按 `source` 解析（TG=int，HN=str `'front'`）；联合唯一 `(source, channel_id)` | 一列贯穿所有信源，不引入 `feed_key` 之类的平行列（2026-07-19 补充讨论） |
| 历史回填 | **做**，用 hckrnews `/data/YYYYMMDD.js` 回填最近 7 天；请求间隔数秒防限流 | 弥补自采样的冷启动；hckrnews 仅提供 id 列表，item 详情仍走官方 API（2026-07-19 补充讨论） |

技术选型（实现侧决定，理由如下）：

- **timeline 合并用联邦式归并**（federated merge）：各源保留独立查询模块（TG 的 album 逻辑原样复用），应用层 k-way merge + 复合 cursor。不做 SQL `UNION ALL`（TG 的 album buffer 逻辑难以塞进统一 SQL），也不做物化 timeline index 表（双写同步成本高，v1 不值得）。
- **API 直接 breaking 升级**，不留 v1 兼容层。单用户自托管，web 前端与后端同镜像发布天然同步；iOS 断档窗口见「部署顺序」。
- `source` 枚举用**小写**（`"telegram"` / `"hn"`），与现有 `LinkPreview.source` 风格一致。
- 统一 item key 字符串：`tg:{channel_id}:{message_id}` / `hn:{story_id}`，用于 API 出入参；DB 层用整数列（见 Phase 2）。

## 现状检查结论（多信源差距）

- ✅ URL 层已源中立：`/api/timeline`、`/api/read`、`/api/records` 不含信源字样。
- ❌ item 结构是扁平 `DisplayMessage`，Telegram 字段全在顶层。
- ❌ `read_messages` / `telegram_records` / `subscriptions` / `keyword_filters` 全按 `(channel_id, message_id)` 键。
- ❌ `timeline.py` 直接 JOIN telememo `messages`；cursor 编码 `(date, message_id)` 无法表达跨源位置。
- ❌ `days` / `unread_counts` / `/timeline/new` 隐含单源。

---

## Phase 1 — HN ingest（后端 + 最小订阅入口，最先上线）

> ⚠️ **官方 API（hacker-news.firebaseio.com/v0/）只有当前快照，没有历史**。"每日上过首页的 story" 只能靠持续采样积累——**订阅一天才有一天的存档**。因此本 phase 独立于 API 改造，尽早合并部署并添加订阅。不含任何 breaking change。

### `subscriptions` 表泛化（SCHEMA_VERSION → 3，本 phase 迁移）

采样是**订阅驱动**的：用户添加 HN feed 订阅后才开始采样。订阅统一放进现有 `subscriptions` 表（用户决策 2026-07-19：不另建表，源专用字段标注即可）：

| 列 | 说明 |
|---|---|
| `source` | `'telegram'` / `'hn'`，迁移时存量行填 `'telegram'` |
| `channel_id` | **泛化语义**：订阅在其信源内的 id（RSS 的 channel 概念）。类型 any（peewee `BareField`，SQLite 无 affinity 列，值按插入类型原样存储）：TG 行存 int（timeline 的 `JOIN subscriptions ON channel_id` 与整数比较不受影响），HN 行存 str（v1 仅 `'front'` = Front Page）。API 层按 source 校验/转换实际类型 |
| PK | **复合主键 `(source, channel_id)`**（即用户要求的联合 unique）。原 PK 是单列 `channel_id` → SQLite 改 PK 要**重建表**（建新表 → 复制 → 改名），走 SCHEMA_VERSION 3 迁移 |
| `name` | 订阅显示名，可空。**TG 行保持 NULL**——title 仍从 telememo `channels` 表解析（源侧元数据，频道改名自动跟随，避免两处存名字变陈旧）；**非 TG 源在订阅时写入**（HN `'front'` → "Hacker News Front Page"；将来 RSS 从 feed 元数据取 title）。展示解析统一为 `COALESCE(sub.name, 源侧查询)`，顺带为将来「用户重命名订阅」留了覆盖位 |
| `config` | JSON，可空；HN front 的展示模式 `{"display_mode": "top20"}`（top10/top20/half/all） |
| `enabled` / `added_at` | 跨源通用 |
| `backfill_done` | **telegram 专用**（HN 行不使用） |

`db.py` 现有 TG 订阅 CRUD 全部加 `source='telegram'` 条件；以后 HN 加 Ask HN / Show HN 等 feed 只是多几行 `channel_id` 记录。

### 数据表：`hn_stories`（condenser 自有，peewee，绑定同一 db）

| 列 | 说明 |
|---|---|
| `id` (PK) | HN item id |
| `title` / `url` / `domain` / `author` / `text` / `type` | item 元数据；`url` 为 NULL 表示 self-post（Ask HN 等）；`text` 是 self-post 的 HTML；`type` = story/job（首页会出现 YC job，照存，UI 弱化） |
| `submitted_at` | HN 原生 `time`（UTC） |
| `first_seen_at` | 首次出现在首页的采样时刻（UTC）——**timeline 排序键** |
| `day` | `first_seen_at` 的 UTC 日期串（`YYYY-MM-DD`），归档日，建索引 |
| `score` / `comments_count` / `score_updated_at` | 最新快照（`descendants` → comments_count） |
| `peak_rank` | 观测到的最高首页名次（可选，展示用） |
| `is_dead` | item 被 HN 删除/标 dead 时置位，timeline 排除 |
| `backfilled` | 该行来自 hckrnews 历史回填而非实时采样（`first_seen_at` 为近似值） |

索引：`(first_seen_at)`、`(day, score DESC)`。

### 采集器：`condenser/hn.py` — `HNManager`

与 `TgManager` 并列，lifespan 里 spawn asyncio task（httpx AsyncClient，同一事件循环）：

每 `CONDENSER_HN_POLL_INTERVAL`（默认 600s）一轮，**先查是否存在 enabled 的 HN feed 订阅**（一次廉价 DB 查询），没有则本轮直接跳过——添加订阅后最迟一个周期内自动开始采样，退订即停，已积累数据保留（与 TG 退订不删消息一致）。有订阅时：

1. `GET /v0/topstories.json`，取前 `CONDENSER_HN_FRONT_SIZE`（默认 30，即首页）条 id。
2. 库中不存在的 id → `GET /v0/item/{id}.json`，插入，`first_seen_at = now`。**再次出现不重置 first_seen_at**（去重语义）。
3. 刷新快照：`first_seen_at` 在 `CONDENSER_HN_REFRESH_HOURS`（默认 48h）内的 story，重拉 item 更新 `score` / `comments_count`（asyncio.gather，并发 ≤10；分数 48h 后基本封顶，停止刷新）。
4. deleted/dead item → 置 `is_dead`。
5. 异常整轮 log + 跳过，不 crash；轮询状态写 `app_meta`（`hn_last_poll_at`、`hn_last_error`），供 status 端点读取。

请求量估算：每轮 ~30（首页 item）+ ~150（48h 刷新窗口）≈ 200 次轻量 GET / 10min，Firebase API 无官方限流，加 0.05s 间隔节流即可。

### 配置

`CONDENSER_HN_ENABLED`（默认 `true`）、`CONDENSER_HN_POLL_INTERVAL=600`、`CONDENSER_HN_FRONT_SIZE=30`、`CONDENSER_HN_REFRESH_HOURS=48`、`CONDENSER_HN_BACKFILL_DAYS=7`（0 = 关闭回填）。

### 端点 + 最小 web 入口（非 breaking）

采样要尽早开始，但完整的 `/api/sources` 和管理 UI 在 Phase 2/3 —— 所以本 phase 必须自带订阅的最小闭环（路径源通用，`channel_id` 按 source 解析）：

- `POST /api/sources/hn/subscriptions` `{channel_id: "front"}` — 添加订阅（开始采样 + 触发回填）
- `PATCH /api/sources/hn/subscriptions/front` `{enabled?, config?}` — 开关 / 改展示模式
- `DELETE /api/sources/hn/subscriptions/front` — 退订（停采样、留数据）
- `GET /api/hn/status` → `{subscribed, enabled, last_poll_at, last_error, stories_total, stories_today, backfill_pending_days}` — 验证数据在积累
- **web 最小入口**：订阅管理页（`/subscriptions`）加一个 "Hacker News" 区块——添加/移除 Front Page 订阅 + 状态展示。非 breaking 的小改动，完整的信源分组管理页在 Phase 3 重构。

### 历史回填：hckrnews `/data/YYYYMMDD.js`（订阅时，最近 7 天）

弥补自采样冷启动（用户决策 2026-07-19）。添加订阅时触发一次性回填任务：

- 数据源 `https://hckrnews.com/data/YYYYMMDD.js`（当天上过首页的 item 列表）。**只对 ≥2 天前的日期可用**，所以立即可回填的是 -7 ~ -2 天（约 6 个请求）；**昨天/今天记入待回填日期集**，采集器在这些日期满 2 天后自动补齐（避免这两天只有订阅后才开始的半截采样）。
- **限速**：对 hckrnews 的请求逐个串行，间隔 3~5s（asyncio.sleep），失败的日期留在待回填集下轮重试，不重试风暴。
- **hckrnews 只取 id 列表**（哪些 story 当天上过首页），item 详情（title/score/author/text…）仍逐条走官方 Firebase API 拉取——把第三方依赖压到最低，它挂了只影响回填不影响主线。
- 回填行 `first_seen_at` 取 story 提交时间夹到该日区间内（近似），`day` 取 hckrnews 的归档日，标记 `backfilled=1`（展示可区分）。回填 item 天然落在 timeline 历史位置（订阅时刻之前），不会冲到顶部。
- 配置：`CONDENSER_HN_BACKFILL_DAYS=7`（0 = 关闭回填）。

### 测试（BDD 先行，mock httpx —— respx 或 monkeypatch）

- 无 enabled HN 订阅 → 整轮跳过、零外部请求；添加订阅后下一轮开始采样；退订停采但 `hn_stories` 数据保留。
- `subscriptions` 表迁移：存量 TG 行 `source='telegram'` 且原有字段无损，TG 订阅 CRUD/timeline JOIN 行为不变。
- 新 id 入库且 `first_seen_at` 正确；同 id 再次出现在首页不重置 `first_seen_at`。
- 刷新窗口内更新 score/comments，窗口外不再请求。
- `day` 键按 UTC 切日。
- dead/deleted item 置位且不再刷新。
- 单条 item 拉取失败不影响整轮。
- 回填：订阅触发后 -7~-2 天入库且 `backfilled=1`；昨天/今天进入待回填集、满 2 天后被采集器补齐；hckrnews 请求串行限速、单日失败留待下轮；`CONDENSER_HN_BACKFILL_DAYS=0` 时完全跳过。

---

## Phase 2 — API 多源化（breaking，与 web 前端机械适配同批落地）

### 2.1 统一 item envelope

`GET /api/timeline` / `/timeline/new` 的 items 变为：

```jsonc
{
  "source": "telegram",              // "telegram" | "hn"
  "key": "tg:1234567:89",            // 全局唯一 item key
  "datetime": "2026-07-19T15:21:01Z",// 排序时间，统一 ISO8601 UTC（TG=消息时间，HN=first_seen_at）
  "is_read": false,
  "is_saved": false,
  "telegram": { /* DisplayMessage，去掉 is_read/is_saved（已提升） */ },
  // source=hn 时改为：
  // "hn": { "id", "title", "url", "domain", "author", "type", "text",
  //          "submitted_at", "first_seen_at", "score", "comments_count",
  //          "day_rank", "peak_rank" }
}
```

不同信源用不同属性名装载 payload（`telegram` / `hn`），解析不易错、JSON Schema 好表达。`day_rank` 为 query-time 计算的当日分数排名（窗口函数），供 UI 展示"当日第 3"。HN 评论页 URL 客户端自拼（`news.ycombinator.com/item?id=`）。

新增 `condenser/items.py`：item key 的 format/parse（pydantic model `ItemKey`），envelope 组装。

### 2.2 read / saved 统一表 + 迁移（SCHEMA_VERSION → 4）

DB 层用整数列（SQL join 不走字符串拼接）：

```
read_items  (source TEXT, ref1 INT, ref2 INT, read_at)        PK(source, ref1, ref2)
saved_items (source TEXT, ref1 INT, ref2 INT, raw_data TEXT, created_at)  PK 同上
```

- TG：`ref1=channel_id, ref2=message_id`；HN：`ref1=story_id, ref2=0`。API 层做 key 字符串 ↔ 三元组转换。
- 迁移：`init_db` 检测 `schema_version < 4` → 建新表，`INSERT SELECT` 复制 `read_messages` / `telegram_records`，旧表重命名 `*_legacy` 保留一版（下个 schema version 再删）。
- `mark_read` 的 album sibling 展开逻辑保留（仅 source=telegram 分支走）。
- `records.py` 渲染按 source 分发：TG 走现有 snapshot 渲染，HN 的 `raw_data` = story JSON 快照（saved 与源数据解耦的原则不变）。

### 2.3 联邦式 timeline 归并

`condenser/timeline.py` 重构为 merge 层 + 两个 source provider：

- `sources/telegram.py`：现有查询逻辑原样搬移（album buffer、unit 切分不动）。
- `sources/hn.py`：查 `hn_stories`，`WHERE is_dead=0 AND day_rank <= N`（`ROW_NUMBER() OVER (PARTITION BY day ORDER BY score DESC)`，N 来自展示模式配置），按 `first_seen_at DESC` 分页。
- merge：复合 cursor = `base64(json {"tg": "<tg cursor>", "hn": "<hn cursor>"})`。每页向各活跃源取 `limit` 个 unit，按 `datetime` 归并取前 `limit`；各源 next cursor 停在本页实际消费到的位置，未消费的源 cursor 原样带回。`head_cursor` 同理复合，`/timeline/new` 逐源轮询后归并。
- 参数：`source`（可选枚举，缺省=全部启用的源）；`channel_id` 仍为 TG 专属（隐含 source=telegram）；`date` / `unread_only` / `limit` 跨源通用。
- `/timeline/days`：各源按日计数后求和合并。
- 已知副作用：HN 的 score 持续更新会让当日 top N 集合变动，item 可能掉出/进入视图，unread 计数轻微波动 —— 可接受，文档注明。

### 2.4 端点变化清单（breaking）

| 端点 | 变化 |
|---|---|
| `GET /api/timeline` / `/timeline/new` | items 变 envelope；cursor 变复合；新增 `source` 参数 |
| `POST /api/read` | body → `{keys: ["tg:...", "hn:..."]}` |
| `POST /api/records` | body → `{key}`；`DELETE /api/records/{key}`（path 单段，key 无 `/`） |
| `GET /api/records` | 返回 envelope 列表 |
| `GET /api/sources`（新增） | **只列已添加（有 ≥1 订阅）的信源**：`[{source, subscriptions: [...]}]` —— TG 列频道（含 unread），HN 列已订阅的 feed（含 unread、config）。订阅显示名按 `COALESCE(sub.name, 源侧查询)` 解析（TG → `channels.title`），实现用一次 JOIN 或批量 `IN` 查询（现有 `/api/subscriptions` 是逐条 `get_channel` 的 N+1，SQLite 下无实害但新接口别延续）。是 web 侧边栏二级结构与 iOS 信源菜单/订阅页的唯一数据源 |
| HN 订阅管理端点 | Phase 1 已就位（`POST/PATCH/DELETE /api/sources/hn/subscriptions*`），本 phase 无新增 |
| `GET /api/subscriptions` 等 TG 管理端点 | 不动（读的是泛化后 `subscriptions` 表的 `source='telegram'` 行） |

HN 的 unread 计数必须与展示筛选一致（只数当前 top N 模式下可见且未读的），否则角标永远清不掉。

### 2.5 web 前端机械适配（同批必须落地，否则页面全挂）

`types.ts` envelope 化、`api.ts` key 出入参、`useScrollToRead` / save 按 key 上报、`MessageCard` 等从 `item.telegram` 取数。**不含新 UI**，只保证现有功能在新 contract 上跑通。

### 测试（BDD 先行）

- 复合 cursor：跨源排序正确、翻页无缝无重复无遗漏、单源耗尽后另一源继续、纯单源（`source=` 参数）行为与旧版等价。
- key parse/format 双向。
- 迁移：造旧表数据 → init → 新表数据完整、旧表更名保留。
- 跨源 unread：HN top-N 视图内计数、read 后清零。
- `/timeline/new` 复合 head 轮询不重复吐已见 unit。
- 现有 31 个后端测试全部迁移到新 contract 后通过。

---

## Phase 3 — Web UI

- **侧边栏二级结构**（`Sidebar` 重构）：数据源为 `GET /api/sources`，**只渲染已添加的信源**；信源为一级分组（Telegram / Hacker News），可折叠（折叠态持久化 localStorage）；点击信源标题 → 该源全部内容视图（`/?source=hn` 或 `/source/hn`）；二级为订阅项（TG 频道沿用 `SidebarChannelLink`；HN 下为已订阅 feed）。顶级 Unread / All / Saved 保持跨源聚合不动。
- **订阅管理页重构**（`/subscriptions`）：从"Manage channels"升级为按信源分区的两级管理页——Telegram 区（现有频道管理原样迁入）+ Hacker News 区（feed 订阅/退订、展示模式配置、采样状态；替换 Phase 1 的最小入口）。未添加的信源展示"添加"引导。
- **HN 卡片**（`components/timeline/HnCard.tsx`）：标题为主体（点击 → 原文新标签页；self-post 展开 text HTML），domain 徽标、score / 评论数（点击 → HN 评论页）/ 作者 / 提交时间 / 当日排名。时间戳仍走 `LinkPreviewPane` 入口，pane 底部 "Open original" 对 HN 变为评论页链接。job 类型弱化样式。
- **Timeline 渲染分发**：按 `item.source` 选 `MessageCard` / `HnCard`；day 分组、scroll-to-read、日历过滤（days 已跨源）对 HN 同样生效。
- **HN 视图头部**：`PageHeader` 加 top N 模式切换（top10 / top20 / 半数 / 全部，PATCH `/api/hn/feed`）。
- Filters 页不动（本期不作用于 HN）。
- 组件清单更新 `frontend/CLAUDE.md`（维护规则）。

## Phase 4 — iOS

- **Models envelope 化**：`TimelineItem` 顶层结构（source/key/datetime/is_read/is_saved + `telegram?` / `hn?`），真实 JSON fixture 驱动测试；`ReadReporter` / save 按 key 上报；`SnapshotCache` 版本号 bump（旧快照 decode 失败按 miss 处理，不 crash）。
- **信源切换器**：顶部操作区**左侧**（用户指定位置）加 Menu，选项 = "All" + `GET /api/sources` 返回的**已添加信源**（不硬编码）；选择驱动 `TimelineStore` 的 `source` 参数；Unread toggle、new-content 轮询按当前 source 生效。
- **第二个 tab「频道」改名「订阅」**：进入后按 信源 → 订阅 两级结构展示（section = 信源，行 = 订阅项，数据源 `/api/sources`）；TG 频道行进入现有 `ChannelTimelineScreen`，HN feed 行进入对应 feed 的 timeline。iOS 仍为只读客户端，订阅的增删改留在 web。
- **HN 卡片 + 详情**：列表卡（标题/domain/score/评论数/当日排名），点击标题 → in-app Safari 开原文，评论数 → HN 评论页；detail sheet 适配 self-post text。
- **Saved 页**：`RecordsStore` 处理 HN envelope。
- 渐进细节（channels tab、pull-to-load-older 等 TG 专属功能）在 source=hn 时隐藏对应入口。

---

## 部署顺序与风险

1. **Phase 1 尽早独立部署**（无 breaking），开始积累存档。⏰
2. Phase 2+3 是 breaking：backend + web 同镜像天然同步；**部署后旧 iOS app 会解析失败**。两个选项：(a) 接受断档，Phase 4 尽快跟上；(b) Phase 4 完成后与 2+3 一起部署。建议 (b)——本地跑通 2+3 后先不发版，等 iOS 就绪一起上，单用户没有发布压力。
3. 迁移前部署脚本侧确认 SQLite 有备份（deploy 目录的既有机制）。
4. HN API 无鉴权无限流承诺，但属 Firebase 托管、多年稳定；采集器已按"单条失败不毁整轮"设计。

## 后续方向（本计划不含）

- HN 专属过滤规则（domain 黑名单 / 标题关键词），及全局过滤器跨源语义升级。
- HN 多 feed（Ask HN / Show HN / best）作为 source 下的多订阅 —— `subscriptions` 表已泛化，只需新增 `channel_id`（如 `'ask'` / `'show'`）+ 对应采集逻辑。
- HN 评论抓取 / 摘要（现阶段跳转 HN 官网）。
- 第三个信源（RSS？）验证抽象的普适性。
