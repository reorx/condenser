---
created: 2026-07-19
tags:
  - session
  - hackernews
  - multi-source
  - bugfix
  - code-review
---

# HN Phase 1 code-review 修复：10 条 finding 全部 TDD 修复落地

## 概要

按 [修复 handoff 计划](../plans/2026-07-19-hn-phase1-review-fixes.md) 执行多信源 Phase 1（commit `f47e0f2`）code review 的 10 条修复。严格 TDD：先写 11 条复现测试（10 条红，B3 的唤醒机制无法在单测中观察到失败、仅锁定"不抛错"行为），再逐组修复到绿。最终 `uv run pytest` 95 passed（原 86 + 新增 10 - A2 改造 1 兼并），前端 `tsc` 通过。四组修复：A（存档持久性）——采样 loop 加兜底 guard、快照刷新不再把瞬时 null 误杀为 dead、pending 回填集加锁 + 逐日重读-删-写防竞态；B（订阅端点）——POST 语义定为"订阅并启用"（复活暂停行）、`CONDENSER_HN_ENABLED=false` 时订阅/启用返回 503 且 status 透出 `source_enabled`、`kick()` 改 `call_soon_threadsafe`；C（schema）——迁移 DDL 与 peewee 模型均加 `DEFAULT 'telegram'`（版本回滚安全）、`add_subscription` 强转 int；D（cleanup）——重订阅不再重跑 `schedule_backfill`、从未拉到数据的 null id 落 dead 占位行避免每轮重拉。

## 修改的文件

- `condenser/hn.py` — `_loop` 包兜底 try/except（A1）；`_refresh_snapshots` 仅显式 `dead`/`deleted` 置 dead，null 跳过重试（A2）；`_pending_lock` + `_discard_pending_day` 逐日读改写（A3）；`kick()` 经 `_loop_ref.call_soon_threadsafe` 唤醒、无 loop 时 no-op（B3）；`status()` 增 `source_enabled`（B2）；`_sample_front` 对 null item 落 dead 占位行（D2）
- `condenser/db.py` — `add_hn_subscription` 返回 `(sub, created)` 并对已存在的暂停行 re-enable（B1/D1）；`add_subscription` 开头 `int()` 强转（C2）；迁移 DDL + `Subscription.source` 模型约束加 `DEFAULT 'telegram'`（C1）
- `condenser/routers/hn.py` — `_require_source_enabled` 辅助：POST 与 PATCH enabled=true 在 master switch 关闭时 503；仅 `created` 时调 `schedule_backfill()`，`kick()` 保留（B2/D1）
- `tests/test_hn.py` — 新增 10 条测试 + 改造 `test_dead_item_marked_and_not_refreshed` → `test_transient_null_survives_but_dead_flag_marks_dead`；迁移测试补"旧代码无 source 列 INSERT"断言
- `frontend/src/lib/types.ts` — `HnStatus` 增 `source_enabled`
- `frontend/src/components/subscriptions/HackerNewsSection.tsx` — source 被禁用时显示红色警示行并禁用订阅按钮
- `AGENTS.md` — `hn.py` 行重写（null 语义、锁、kick、503 行为），status 段落补 review-fix 记录

## 注意事项

- **null ≠ dead 的双重语义**：Firebase 对存活 item 会瞬时返回 200 `null`。已有完整数据的行遇 null 只跳过（下轮重试）；从未成功拉到数据的首页 id 遇 null 则落 `is_dead=True` 占位行做跨轮去重。两处场景不同，勿合并处理。
- **pending 回填集是跨线程共享状态**：`schedule_backfill` 跑在 FastAPI threadpool，采样 loop 跑在事件循环线程。任何"整集读出→长 await→整集写回"都会覆盖并发写入；修复模式是 `threading.Lock` + 把写窗口缩到单日粒度的重读-删-写。
- **asyncio 原语不是线程安全的**：threadpool 里 `Event.set()` 虽能置位 flag，但不会唤醒正在 select 的 loop（最坏拖满整个轮询间隔）。跨线程唤醒必须 `loop.call_soon_threadsafe`；`_loop_ref` 在 `startup` 内取得，source 禁用时保持 None 使 kick 自然降级 no-op。
- **BareField 列失去类型 affinity**：v3 起 `subscriptions.channel_id` 无 affinity，`'123'` 与 `123` 可并存为两行且 timeline JOIN 双双命中。所有 TG 写入口必须 int 强转。
- **版本回滚安全**：新增 NOT NULL 列要带 SQL DEFAULT（DDL 与 peewee 模型 `constraints=[SQL(...)]` 两处都要——peewee 的 `default=` 只是客户端行为，不进 CREATE TABLE）。
- 顶层错误处理位置：`poll_once` 内 try 只负责把业务错误写进 `hn_last_error`；`_loop` 的兜底 guard 负责"任何异常都不许杀死 task"。两层职责不同，符合"只在顶层处理错误"的项目规则。

## 遗留问题

- B3 的唤醒时延无法用单测断言（跨线程 `Event.set()` 在测试里表现正常），`test_kick_safe_without_loop_and_wakes_across_threads` 只锁定 no-op 安全与 threadsafe 路径可用。
- 真被删除但只返回裸 null（无 `deleted: true`）的 item 现在永不置 dead，会一直留在 48h 刷新窗口内直到窗口过期——按计划接受，未做连续计数方案。
- 修复尚未部署；母计划的"尽早部署攒存档"仍待执行。

## 相关文档

- [HN Phase 1 code-review 修复清单](../plans/2026-07-19-hn-phase1-review-fixes.md) — 本次 session 依据的 handoff 计划
- [多信源架构 + Hacker News 信源计划](../plans/2026-07-19-multi-source-hn.md) — Phase 1 母计划（参考）
- [Phase 1 实施 session](2026-07-19-multi-source-phase1-hn-ingest.md) — 产生被 review 代码的 session（参考）
