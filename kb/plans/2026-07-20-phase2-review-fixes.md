---
created: 2026-07-20
tags:
  - plan
  - handoff
  - multi-source
  - code-review
  - bugfix
---

# Phase 2 code-review 修复清单（handoff）

多信源 Phase 2（API envelope 化 + 联邦 timeline 归并，见
[多信源架构计划](2026-07-19-multi-source-hn.md) §Phase 2）实现完成后跑了
high-effort 多 agent code review（25 agents，22 个候选全部经独立 verifier 确认），
报告 7 个正确性问题 + 3 个清理项。本文档是给下一个 session 的自包含修复计划。

**改动现状**：Phase 2 全部改动在 working tree 中**未提交**（`git diff HEAD` 即本次
diff）。后端 119 / 前端 17 测试全绿，但含下述已确认 bug。

## ⚠️ 流程闸门（先读）

1. **master 有 hookploy 自动 CD**（commit 0652a27）。Phase 2 是 breaking contract，
   iOS（Phase 4）未跟进——**push master = 自动部署 = 打挂线上 iOS/web**。修复完成后
   也只能提交到本地/分支，或先停 CD；上线必须等 Phase 3+4 齐（计划部署顺序决策 (b)）。
2. F1（iOS 旧协议不兼容）**不是本次要修的代码问题**，它就是 Phase 4 的内容；本清单
   只修 Phase 2 自身的缺陷。

## 修复方法论

按项目规约 TDD：**每项先写复现测试（红）→ 修复（绿）**。新测试统一放
`tests/test_multi_source.py`（延续现有风格：`seed_channel`/`seed_messages`/`seed_hn`
/`subscribe_hn` helpers 已在该文件）。全部修完跑 `uv run pytest` +
`cd frontend && pnpm test && pnpm build`。

---

## 必修（正确性，按严重度排序）

### F2. 旧/坏 cursor 导致 500 — `condenser/timeline.py:26`

`decode_cursor_map` 直接 `json.loads(base64...)`，无任何容错。旧格式 cursor
（Phase 2 前是 `base64('date\x1fid')`，同样是 urlsafe base64，能解码出非 JSON 字符串）
或任意垃圾输入 → 未捕获异常 → HTTP 500。跨部署仍开着的 web 标签页（内存中的
`next_cursor`）必触发。

**修法**：定义 `class InvalidCursor(ValueError)`；`decode_cursor_map` 把
base64/JSON/编码错误及"解出来不是 dict"统一转成 `InvalidCursor`；
`routers/reading.py` 三个端点 catch → `HTTPException(422, 'invalid cursor')`。

**测试**：`GET /api/timeline?cursor=<旧格式 encode('date\x1fid')>`、`cursor=garbage`、
`/timeline/new?after=<同上>` → 均 422（不是 500）。

### F3. k-way merge 在 album 密集页破坏时序 — `condenser/timeline.py:83`

TG provider `fetch_page` 取 `fetch_cap = limit + 20` 行；album 折叠后可能返回
**少于 limit 个 unit 且 `has_more=True`**（`len(rows) == fetch_cap`）。merge 循环
耗尽 TG 页内 unit 后，继续用 HN 的**更旧** unit 填满页面；下一页 TG 从第 N+1 个
unit（比上页 HN 尾部更新）恢复 → 跨页时间线乱序、日期分组重复。

**修法**：merge 时维护每个源的"地板"：若源 s 的页内 unit 已耗尽且
`pages[s].has_more`，则地板 = s 最后一个 unit 的 `sort_ts`；其他源的候选 unit
`sort_ts <` 任一地板时**提前结束本页**（页可短于 limit，`has_more=True`，
next_cursor 照常取 consumed 位置）。注意：TG `units` 非空才可能 has_more（rows 空
则 units 空且 has_more=False），地板始终可取。

**测试**：limit=3；TG 一个频道 seed 23 行组成 2 个大 album（12+11 行，两个
grouped_id，时间靠新）→ fetch_cap=23 命中、返回 2 unit + has_more；HN 一条更旧的
story。断言 page1 只有 2 个 TG unit（不含旧 HN story）；翻页收集全部 key，断言全局
`datetime` 严格降序、无重复无遗漏。

### F4. 空结果源被 `/timeline/new` 永久跳过 — `condenser/timeline.py:102`

`heads = {s: units[0].head for s in active if pages[s].units}` 只给"本页有 unit
的源"发 anchor；`query_new` 对无 anchor 的源 `continue`。场景：Unread 视图 HN 全部
已读、或 HN 刚订阅还没采到数据 → page-1 无 hn anchor → 之后新 story 永远不进
new-content banner，直到手动刷新。

**修法**：在 `query_timeline` 里给 active 但零 unit 的源合成"当前时刻" anchor：
`pack_pos(items.norm_ts(now_utc), 0)`（norm 19 字符串与两源存储格式做前缀比较均
安全；`_now` 参考 `db._now_naive()`）。副作用是良性改进：全已读视图现在也能收到
新内容提示。

**测试**：TG 有消息 + HN 已订阅但 `hn_stories` 为空 → 取 page-1 `head_cursor`；
seed 一条新 HN story → `/timeline/new?after=head` 的 count==1 且含 `hn:*` key。
再补一个"HN 全部已读 + unread_only 视图"的同构用例。

### F5. HN `fetch_new` count 被 poll limit 封顶 — `condenser/sources/hn.py:119`

SQL `LIMIT limit`，而前端 `useNewContent` 轮询传 `limit=1` → HN 的新内容数永远
最多 1（banner 永远"1 new message"）。TG 路径是 `limit + _ALBUM_BUFFER` 行再数。

**修法**：与 TG 对齐，`_fetch(..., limit=limit + 20)`（常量可提到
`sources/base.py`，如 `NEW_COUNT_BUFFER = 20`，TG 的 `_ALBUM_BUFFER` 语义不同但数值
沿用即可，注释说明是 count 余量）。

**测试**：seed 5 条新可见 story，`/timeline/new?after=head&limit=1` → `count == 5`
（items 仍只 1 条，符合 limit 语义）。

### F6. `half` 模式吃掉单条 story 的日子 — `condenser/sources/hn.py:49`

`day_rank * 2 <= day_total` 在 day_total=1 时恒假 → 该天唯一 story 在 timeline、
days()、unread_count() 全部消失。

**修法**：向上取整：`r.day_rank * 2 <= r.day_total + 1`。

**测试**：单 story 日 + half 模式 → 可见；**同时更新现有断言**：
`test_hn_display_mode_top_n` 中 25 条 half 模式的期望从 12 改为 **13**（ceil）。

### F7. All/Unread 头部未读数不含 HN — `frontend/src/pages/TimelineView.tsx:39`

聚合视图头部 `unreadCount` 只 sum TG `/api/subscriptions`，列表却渲染 HN 未读卡片
→ 数字与内容矛盾（HN 20 条未读时头部显示 0；滚读 HN 不减数）。

**修法（最小改动）**：新增 `useSources` hook（`GET /api/sources`，后端已就绪，
`api.ts` 加 `listSources`，类型 `SourceGroup { source; subscriptions: SourceSub[] }`
对齐 `routers/sources.py` 返回）；聚合视图 `unreadCount` = 所有源 enabled 订阅的
`unread` 之和；频道视图不变。缓存一致性：`useScrollToRead.applyReadOptimistic` 对
HN key（`channelId == null`）做 `['sources']` 失效（TG 走现有 subscriptions 乐观
减数即可，同时在 flush 后 invalidate `['sources']`），`useBulkRead.onSettled` 加
`invalidateQueries({queryKey: ['sources']})`。Phase 3 侧边栏会复用这个 hook。

**测试**：前端无对应测试基建，验证方式 = `pnpm build` + preview/手测；后端
`/api/sources` 的 unread 口径已有测试锁定（`test_hn_unread_counts_only_visible_top_n`）。

---

## 顺手修（清理项）

### C1. `/api/records` N+1 — `condenser/records.py:116`

`render_item` 每条 saved item 一次 `is_item_read` EXISTS。改为一次 JOIN 批量取：
`SELECT s.source, s.ref1, s.ref2 FROM saved_items s JOIN read_items r ON r.source=s.source AND r.ref1=s.ref1 AND r.ref2=s.ref2`
→ set，`list_rendered_records` 查一次传入 `render_item(rec, read_triples)`。
现有 records 测试保绿即可，可加一条"saved+read 的 item 渲染 `is_read: true`"断言
（目前这个行为没有测试锁定）。

### C2. `_hn_snapshot` 与 `items.hn_payload` 字段映射重复 — `condenser/records.py:57`

两处手写同一批字段（快照是持久副本，漏改即永久丢字段）。改为单一来源：
`row = story.__data__`（peewee 模型 dict）→ `payload = items.hn_payload(row)` →
`payload['day'] = story.day` 存为 raw_data。`hn_payload` 会带 `day_rank: None`，
无害。现有 `test_record_save_and_render_by_key_hn` 保绿。

### C3.（可选，不阻塞）`_RANKED` 全表窗口函数 — `condenser/sources/hn.py:24`

每次分页/30s 轮询/days/unread 都对整个 `hn_stories` 跑 ROW_NUMBER。单用户 SQLite
一年 ~1 万行内无感，暂不修；若要做：把 day 约束（date 过滤、cursor 的 day 上界）
下推进 ranked 子查询。**已推迟（2026-07-20）：单用户量级下无感知，等 hn_stories
行数上万后再做 day 下推优化。**

---

## 验收

- [x] F2–F6 各有先红后绿的测试；F7 完成 `pnpm build`（2026-07-20 完成）
- [x] `uv run pytest` 全绿 — 126 passed（F6 的 half 断言 12 → 13 已更新）
- [x] `cd frontend && pnpm test && pnpm build` 全绿 — 17 passed + build 成功
- [x] C1、C2 完成；C3 标注推迟（见上）
- [x] 更新根 `AGENTS.md` 状态段（Phase 2 条目追加 review 修复完成 + 模块行更新）
- [x] **不 push master**（CD 闸门，见顶部）；本地两个 commit（fixes / cleanups）

## 相关文档

- [Phase 2 code review 报告](../reviews/2026-07-20-phase2-review.md) — 本清单的来源（完整 findings + 失败场景）
- [多信源架构 + Hacker News 信源](2026-07-19-multi-source-hn.md) — 被 review 的 Phase 2 所属计划
- [HN Phase 1 review 修复](2026-07-19-hn-phase1-review-fixes.md) — 上一轮同类修复的先例（风格参考）
