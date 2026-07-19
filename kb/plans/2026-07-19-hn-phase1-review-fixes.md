---
created: 2026-07-19
tags:
  - plan
  - hackernews
  - multi-source
  - code-review
  - bugfix
---

# HN Phase 1 code-review 修复清单（handoff）

多信源 Phase 1（commit `f47e0f2`，见[实施 session](../sessions/2026-07-19-multi-source-phase1-hn-ingest.md)）合并后跑了 high 档多 agent code review：22 条候选全部通过独立验证，收敛 16 个缺陷，上报最严重的 10 条（9 CONFIRMED / 1 PLAUSIBLE，0 refuted）。本计划是给下一个 session 的修复 handoff——每条含位置、失败场景、修复方向与测试要求。

**方法论**：TDD——先为每条写复现测试（扩展 `tests/test_hn.py`，沿用其可注入 `fetch_json` / `_now` 覆盖 / 限速置零三件套），再修到绿。行号基于 `f47e0f2`，改动后会漂移，以描述定位为准。

**优先级分组**：A（存档持久性，丢数据不可逆）> B（订阅端点状态）> C（迁移/schema）> D（cleanup）。各条相互独立，可单独提交；建议整批一个 commit 或按组提交。

---

## A. 存档持久性（最高优先级——HN 官方 API 无历史，采样丢了就是永久丢）

### A1. 采样循环无兜底异常保护 → loop task 静默死亡

- **位置**：`condenser/hn.py` `_loop`（~L87-94）与 `poll_once`（~L114-127）
- **问题**：`poll_once` 的 try 块只包住采样三步；`db.hn_sampling_active()`（try 之前）、尾部两个 `db.set_meta`、except 分支里的 `db.set_meta` 都不受保护。任一抛错（典型：TG ingest 持有 WAL writer 时的 `database is locked`）会逃出 `poll_once`，`_loop` 无 try → task 死亡，`add_done_callback` 只做 discard，无重启无上报。采样静默停止直到进程重启，期间首页 story 永久丢失，而 `/api/hn/status` 还显示旧的 `last_poll_at`、`last_error` 为空。
- **修复**：把整个 `poll_once` 调用包进 `_loop` 的 try/except（log + 继续下一轮）；或把 `poll_once` 内所有 DB 访问纳入统一 guard。推荐前者——`_loop` 是顶层函数，符合项目"只在顶层处理错误"的规则；`poll_once` 现有 try 结构可保留（负责把业务错误写进 `hn_last_error`），`_loop` 的 guard 兜住其余一切。
- **测试**：monkeypatch `db.hn_sampling_active`（或 `set_meta`）抛一次 RuntimeError → 断言 `_loop` 不死、下一轮照常执行（可直接测 "poll_once 抛错时 _loop 存活"：跑两轮，第一轮注入异常，第二轮正常采样成功）。

### A2. 快照刷新把瞬时 null 当删除，永久标 dead 无复活路径

- **位置**：`condenser/hn.py` `_refresh_snapshots`（~L193-195）
- **问题**：Firebase 对**存活** item 偶发瞬时返回 null（HTTP 200 body `null`）是已知行为。刷新阶段 `item is None → mark_hn_story_dead`，而 `hn_stories_to_refresh` 过滤 `is_dead==False`，一次抖动就把 story 永久踢出刷新集：分数冻结、后续展示阶段按 dead 排除——单次 flaky 响应造成 append-only 存档的静默数据损坏。对比 `_sample_front` 对 null 只是跳过下轮重试，两处语义不一致。
- **修复**：null（`item is None`）不再立即置 dead。方案：只有显式 `dead`/`deleted` 字段才置位；null 视为瞬时失败跳过（与 `_sample_front` 一致）。若想覆盖"真被删除"的情况，可加连续计数（如连续 3 轮 null 才置 dead），但 v1 简单跳过即可——真 deleted 的 item 通常带 `deleted: true` 而非裸 null。
- **测试**：改造现有 `test_dead_item_marked_and_not_refreshed`——story 1 的 null 改为**不**置 dead（下轮恢复正常响应后分数继续更新）；story 2 的 `dead: true` 仍置位。新增：null 一轮后恢复 → score 正常刷新。

### A3. `hn_backfill_pending` 读-改-写竞态丢日期

- **位置**：`condenser/hn.py` `_backfill_eligible_days`（~L227-241）与 `schedule_backfill`
- **问题**：回填循环开头 `pending = self._pending_days()` 拿内存快照，随后跨多个长 await（每日 4s 间隔 + 逐条 item 拉取，整轮可达分钟级）逐日 `pending.discard + _save_pending(pending)` 盲写回。期间用户退订再订阅，`schedule_backfill`（FastAPI 线程池线程）写入 8 个新日期 → 循环下次回写用陈旧副本整个覆盖，新日期静默丢失；窗口过期后（hckrnews 只保留近期）永久无法回填。
- **修复**：不整集回写——把"删一个日期"改成读-改-写最小化：每完成一天，重新 `_pending_days()` 读最新集、discard 该天、立即保存（read-modify-write 窗口缩到微秒级，且两个写入方都跑在… 注意 `schedule_backfill` 在线程池线程、循环在事件循环线程，SQLite 层面串行化，但应用层仍需"重读再写"避免覆盖）。更彻底：给 pending 集操作加一把 `threading.Lock`（HNManager 实例属性），`schedule_backfill` / `_save_pending` / `_pending_days` 的复合操作都持锁。推荐"每天完成后重读-删-写 + lock"组合，改动小。
- **测试**：模拟竞态——`_backfill_day` 的 fake 里（回填进行中）调 `mgr.schedule_backfill()` 注入新日期，断言轮结束后 pending 同时包含"新注入的日期"且不含"已完成的日期"。

## B. 订阅端点状态处理

### B1. 重复订阅不恢复 enabled=false 的行

- **位置**：`condenser/routers/hn.py` `add_hn_subscription`（~L24-31）+ `condenser/db.py` `add_hn_subscription`
- **问题**：`get_or_create` 的 `defaults` 只在新建时生效。暂停（PATCH enabled=false）后再 POST 订阅：返回 200、前端 toast "sampling starts now"、回填已调度，但 `enabled` 仍 False → `hn_sampling_active()` False → 永不采样，回填也永不推进（`poll_once` 开头就跳过）。iOS 或第二个 tab 的旧 UI 很容易触发。
- **修复**：POST 语义定为"订阅并启用"：`db.add_hn_subscription` 对已存在的行执行 `enabled=True` 的 update（或返回 `(sub, created)`，router 对 `not created and not sub.enabled` 补一次 update）。与 B3（created 标志）一并处理。
- **测试**：订阅 → PATCH enabled=false → 再 POST → 断言 `get_hn_subscription('front').enabled` 为 True。

### B2. `CONDENSER_HN_ENABLED=false` 时订阅仍报成功

- **位置**：`condenser/routers/hn.py`（POST/PATCH 不检查配置）+ `condenser/hn.py` `startup`
- **问题**：master switch 关闭时 `startup` 直接 return，loop 不存在；但端点照常 200 + "开始采样"，`kick()` 设置的事件无人等待，status 永远 `last_poll_at=null` 而无任何异常指示——用户以为在攒数据，实际零采样，丢的天数不可找回。
- **修复**：两层任选其一或都做：(1) POST 订阅时若 `settings.condenser_hn_enabled` 为 False → 503（detail 说明 HN source 被配置禁用），PATCH enabled=true 同理；(2) `/api/hn/status` 增加 `sampler_running`（或 `source_enabled`）字段，前端 `HackerNewsSection` 显示警示。推荐 (1)+(2)：端点拒绝写入 + status 透出配置态。
- **测试**：`monkeypatch.setenv('CONDENSER_HN_ENABLED','false')` + cache_clear → POST 订阅断言 503；status 断言 `source_enabled` False。注意 TestClient 下 `app.state.hn` 无 loop task 本来就是这个形态。

### B3. `kick()` 跨线程调用 `asyncio.Event.set()`

- **位置**：`condenser/hn.py` `kick`（~L83-85）；调用方 `routers/hn.py`（同步 def，线程池执行）
- **问题**：asyncio 原语非线程安全。跨线程 `Event.set()` 走普通 `call_soon` 不唤醒 selector——"订阅后立即开始首轮采样"最坏拖满 10 分钟轮询间隔；`PYTHONASYNCIODEBUG=1` 下跨线程 `call_soon` 直接 RuntimeError（行已创建但请求 500）。
- **修复**：HNManager 在 `startup`（事件循环线程内）记下 `self._loop_ref = asyncio.get_running_loop()`；`kick()` 改为 `self._loop_ref.call_soon_threadsafe(self._wake.set)`（loop 不存在/未启动时安全降级为 no-op）。或把 router 端点改成 `async def`（跑在事件循环线程，直接 set 合法）——**这是最小改动，推荐**：三个 HN 订阅端点全是纯 DB + 内存操作，改 async 无阻塞风险（SQLite 操作极轻；但注意项目其他 sync 端点先例……router 内 db 调用是阻塞 IO，async def 会在事件循环上执行——SQLite 本地写微秒级，可接受；若保守则用 call_soon_threadsafe 方案）。
- **测试**：机制难以单测断言唤醒时延；至少断言 kick 在无 loop（未 startup）时不抛错。若走 call_soon_threadsafe 方案，用真实事件循环 + 线程池调 kick 验证 `_wake` 被置位。

## C. 迁移 / schema

### C1. 迁移 DDL 的 `source` 列缺 `DEFAULT 'telegram'` → 版本回滚即坏

- **位置**：`condenser/db.py` `_migrate_subscriptions_v3` 的 CREATE TABLE
- **问题**：`source VARCHAR(255) NOT NULL` 无 SQL DEFAULT。迁移跑过一次后若回滚到上一发布版（同一 bind-mount 的 SQLite），旧代码 `INSERT INTO subscriptions (channel_id, enabled, backfill_done, added_at)` 触发 `NOT NULL constraint failed: subscriptions.source` → 新增 TG 订阅全 500。
- **修复**：DDL 改为 `source VARCHAR(255) NOT NULL DEFAULT 'telegram'`。注意**已迁移的库不会重跑迁移**（shape 检测有 source 列即跳过）——对已上线的库需补一次列级修复；但本项目生产尚未部署 v3（`f47e0f2` 未发布），直接改 DDL 即可，无需二段迁移。若担心开发库已迁移：dev 库可删除重来，或加一个"检测 source 列无 default 则重建"的幂等分支（成本高，不推荐，注释说明即可）。
- **测试**：迁移测试里加断言：迁移后 `INSERT INTO subscriptions (channel_id, enabled, backfill_done, added_at) VALUES (...)`（不带 source）成功且 `source='telegram'`——直接模拟旧版代码的写入路径。

### C2. `BareField` 失去 int 强制转换与单列唯一性（PLAUSIBLE，潜伏雷）

- **位置**：`condenser/db.py` `Subscription.channel_id = BareField()`
- **问题**：旧 `IntegerField` 会把 `'123'` adapt 成 int；现在 `('telegram','123')` 与 `('telegram',123)` 可并存（复合 PK 不拦）。timeline JOIN 对无 affinity 列做数值转换后**两行都命中**→ 该频道消息翻倍、未读翻倍；而 `DELETE /api/subscriptions/123`（int 绑定，无转换）只删 int 行，API 层清不掉脏行。verifier 已用 sqlite3 实测复现。当前所有调用方都是 int-typed（FastAPI path/body 校验），属于防御性修复。
- **修复**：在 `db.py` 的 TG 订阅写入口做强制转换：`add_subscription(channel_id: int)` 开头 `channel_id = int(channel_id)`（一行）；或给 Subscription 加 `save`/insert 前的规范化。最小改动：只在 `add_subscription` 转换（唯一的 TG 行创建入口）。同时可在 `_migrate_subscriptions_v3` 后加一次性清理无必要——生产库不会有脏数据。
- **测试**：`db.add_subscription('5')`（故意传 str）→ 断言表里是 int 行、与 `db.add_subscription(5)` 幂等（仍只有一行）。

## D. Cleanup

### D1. 重复订阅无条件重跑 schedule_backfill

- **位置**：`condenser/routers/hn.py` L27-29 + `db.add_hn_subscription`（丢弃 created 标志）
- **问题**：幂等重订阅（重试/双击/重放）把已完成的 8 天重新塞回 pending → 下几轮白抓最多 6 个 hckrnews 日归档 + item 拉取，结果全被 `on_conflict_ignore` 丢弃；status 误显 "backfill pending: 8 days"。
- **修复**：`db.add_hn_subscription` 返回 `(sub, created)`；router 仅 `created` 时调 `schedule_backfill()`（`kick()` 保留——重订阅仍应立即恢复采样，配合 B1 的 re-enable）。与 B1 同一处代码，一起改。
- **测试**：订阅 → 手动清空 pending（模拟回填完成）→ 再 POST → 断言 pending 仍为空。

### D2. `_sample_front` 对 null item 不落占位行，幽灵 id 每轮重拉

- **位置**：`condenser/hn.py` `_sample_front`（~L144-146）
- **问题**：null item 的 id 不入库，只进本轮 `fetched` 集；该 id 停留在 topstories 期间每 10 分钟被当"未见过"重拉一次。
- **修复**：null 时插入最小占位行 `insert_hn_story(id=sid, first_seen_at=now, day=..., is_dead=True)`，让跨轮去重生效（与 A2 的"null 不置 dead"不冲突：A2 针对**已有完整数据**的行被瞬时 null 误杀；这里是从未成功拉到数据的 id，占位 dead 行合理且不进刷新集）。若嫌语义纠结，备选：内存级 `self._null_ids: dict[int, int]`（id→连续 null 次数），连续 ≥3 次才落占位行。推荐直接落占位行，简单。
- **测试**：front=[1]，item 1 返回 null → 第二轮 front 仍 [1] → 断言 item 1 的 fetch 只发生一次（第二轮不再请求）。

---

## 验收

- `uv run pytest` 全绿（含既有 86 个 + 本次新增，注意 A2 会**修改**一个既有测试的语义）。
- 每条 finding 有对应测试锁定（TDD：先红后绿）。
- 完成后更新根 `AGENTS.md` 中 `hn.py` 行（如行为语义有变，例如 null 处理），并写 session 总结（`/kb ss`）链接本计划。

## 相关文档

- [多信源架构 + Hacker News 信源计划](2026-07-19-multi-source-hn.md) — Phase 1 的母计划
- [Phase 1 实施 session](../sessions/2026-07-19-multi-source-phase1-hn-ingest.md) — 产生被 review 代码的 session（commit `f47e0f2`）
