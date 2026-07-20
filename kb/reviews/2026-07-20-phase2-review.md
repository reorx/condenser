---
created: 2026-07-20
tags:
  - review
  - code-review
  - multi-source
  - phase2
---

# 多信源 Phase 2 code review 报告

**被审对象**：working tree 未提交的 Phase 2 改动（`git diff HEAD`，32 个文件）——
API envelope 化、`read_items`/`saved_items` v4 迁移、联邦 timeline 归并、端点改造、
web 前端机械适配。

**工具**：`/code-review high`（workflow 后端，25 个 agent：1 scope + 4 finder +
19 verifier + 1 synthesize；1.39M tokens / 231 tool calls / ~12.7 min）。

**结果**：22 个候选发现全部通过独立 verifier 对抗验证（0 refuted），报告 10 条 ——
7 个正确性问题 + 3 个清理项。

---

## 正确性问题

### F1. 旧 client contract 被移除而 iOS 未跟进 — `condenser/types.py:61`（另见 `routers/reading.py:61`）

`POST /api/read {items:[{channel_id,message_id}]}`、`DELETE /api/records/{cid}/{mid}`、
扁平 DisplayMessage 三个契约同时移除，但 `ios/` 未在本 diff 中改动 ——
`ios/CondenserKit/Sources/CondenserKit/APIClient.swift:66` 仍编码 `Body{items:[MsgRef]}`。

**失败场景**：部署后已安装的 iOS app：ReadReporter 收到 422（新 `ReadBody` 要求
`keys`），滚动已读全部静默丢失；timeline/records JSON 字段移入 `telegram` 信封，
Codable 解码失败 → 空/报错时间线；取消收藏命中已删除路由 → 404。

**判定**：**非代码缺陷，是计划内的分期**（部署顺序决策 (b)：Phase 2+3+4 一起上线）。
但 review 顺带暴露了真实风险：**master 有 hookploy 自动 CD**，push 即自动部署。
→ 归入 Phase 4，并在修复计划顶部立"流程闸门"。

### F2. `decode_cursor_map` 无容错，旧 cursor → 500 — `condenser/timeline.py:26`

cursor 格式从 `base64('date\x1fid')` 变为 `base64(JSON map)`，两者同为 urlsafe
base64，旧值能解出非 JSON 字符串 → 未捕获 `JSONDecodeError` → HTTP 500。

**失败场景**：跨部署仍开着的 web 标签页，其内存中的 `next_cursor` 是旧格式，
无限滚动连环 500 直到整页刷新；iOS 的 `SnapshotCache` 持久化 cursor 同理。

### F3. k-way merge 在 album 密集页破坏全局时序 — `condenser/timeline.py:83`

TG `fetch_page` 取 `fetch_cap = limit + 20` 行，album 折叠后可能返回**少于 limit 个
unit 且 `has_more=True`**；merge 耗尽后继续用 HN 的更旧 unit 填满页面。

**失败场景**：50 行 10 图相册折叠成 ~5 unit，剩余 ~25 个位置由更旧的 HN story 填充；
下一页 TG 从第 6 个 unit 恢复（比上页 HN 尾部更新）→ 跨页乱序、日期分隔重复出现。

### F4. 空结果源被 `/timeline/new` 永久跳过 — `condenser/timeline.py:102`

`head_cursor` 只收录"本页产出 ≥1 unit 的源"，`query_new` 对无 anchor 的源直接
`continue`。

**失败场景**：Unread 视图下 HN 全部已读（或刚订阅尚未采样）→ page-1 无 hn anchor
→ 此后新 story 永不触发 new-content banner，直到用户手动刷新。

### F5. HN `fetch_new` 的 count 被 poll limit 封顶 — `condenser/sources/hn.py:119`

SQL `LIMIT limit`，而 `useNewContent` 轮询传 `limit=1`；TG 路径则取
`limit + _ALBUM_BUFFER` 行再计数。

**失败场景**：15 条新 story 到达，banner 永远显示 "1 new message"；混合来源时总数
也错（TG_new + 1）。

### F6. `half` 模式吃掉只有一条 story 的日子 — `condenser/sources/hn.py:49`

`r.day_rank * 2 <= r.day_total` 在 `day_total=1` 时恒假。

**失败场景**：稀疏回填日/早期采样日仅存 1 条 story → 该 story 在 timeline、`days()`、
`unread_count()` 三处同时消失，该模式下永不可达。

### F7. All/Unread 头部未读数不含 HN — `frontend/src/pages/TimelineView.tsx:39`

头部计数仍只 sum TG-only 的 `/api/subscriptions`，而这两个视图现在渲染带独立已读
状态的 HN item。

**失败场景**：TG 全已读 + 20 条 HN 未读 → 头部显示 0，下方却是 20 张带蓝点的未读
HN 卡片；滚读 HN 也不会让数字变化。

---

## 清理项

> 编号与[修复计划](../plans/2026-07-20-phase2-review-fixes.md)一致（按修复优先级排，
> 非 reviewer 原始顺序）。

### C1. `/api/records` N+1 — `condenser/records.py:116`

`render_item` 每条 saved item 一次 `is_item_read` 单行 EXISTS；几百条收藏 = 几百次
串行 SQLite 往返。一次 JOIN 批量取即可。

### C2. `_hn_snapshot` 与 `items.hn_payload` 字段映射重复 — `condenser/records.py:57`

两处手写同一批字段（13 个重合，前者少 `day_rank` 多 `day`），含相同的
`iso_utc(...)`/`bool(...)` 变换。新增 HNStory 列须改两处，**漏改则快照永久丢字段**
——快照是持久副本，`hn_stories` 行被清理后不可恢复。

### C3. `_RANKED` 全表窗口函数扫描 — `condenser/sources/hn.py:24`

每次分页、每 30s 轮询、`days()`、`unread_count()`、`/api/sources` 每个订阅都对整个
`hn_stories` 跑 `ROW_NUMBER`/`COUNT` 窗口函数。archive-everything（~30+ 条/天，
按计划无限增长）下一年后 ~1 万行，延迟线性劣化。建议把 day 约束下推进 ranked
子查询，或写入时维护 rank。reviewer 按严重度把它排在清理项之首，但单用户 SQLite
短期无感 → 计划中标为可选推迟。

---

## 处置

全部 findings 已转成可执行的修复清单：
[Phase 2 code-review 修复清单](../plans/2026-07-20-phase2-review-fixes.md)
（F1 归 Phase 4 + 立 CD 闸门；F2–F7 必修，TDD 先红后绿；C1–C2 顺手修，C3 可选推迟）。

## 相关文档

- [Phase 2 code-review 修复清单](../plans/2026-07-20-phase2-review-fixes.md) — 本报告的修复计划
- [多信源架构 + Hacker News 信源](../plans/2026-07-19-multi-source-hn.md) — 被 review 的 Phase 2 所属计划
- [HN Phase 1 review 修复](../plans/2026-07-19-hn-phase1-review-fixes.md) — 上一轮同类 review→修复的先例
