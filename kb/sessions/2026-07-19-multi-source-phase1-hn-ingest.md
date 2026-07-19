---
created: 2026-07-19
tags:
  - session
  - multi-source
  - hackernews
  - backend
  - migration
---

# 多信源 Phase 1：Hacker News 采样存档落地（后端 + 最小订阅入口）

## 概要

按多信源计划的 Phase 1 实施：condenser 从 Telegram 专用升级为多信源架构的第一步。核心矛盾是 HN 官方 API 只有当前快照没有历史，"每日上过首页的 story" 只能靠持续采样积累，因此本阶段独立于 breaking 的 API 改造，先行上线开始攒数据。本次完成：`subscriptions` 表泛化迁移（SCHEMA_VERSION 3，复合主键 `(source, channel_id)`），新增 `hn_stories` 存档表，`HNManager` 订阅驱动的采样循环（topstories 差集入库、48h 快照刷新、dead 标记）、hckrnews 历史回填（串行限速 + 待回填日期集），`/api/sources/hn/subscriptions*` + `/api/hn/status` 端点，以及 `/subscriptions` 页的 Hacker News 最小管理区块。全程 BDD：先写 17 个行为测试再实现，一次通过；全量 86 个后端测试绿，前端 build 通过。无任何 breaking change，可立即部署。

## 修改的文件

- `tests/test_hn.py` — 新增。17 个行为测试：v3 迁移（存量 TG 行无损、幂等）、订阅驱动采样开关、first_seen_at 去重 + peak_rank、刷新窗口过期、UTC day 键、dead/deleted 标记、单条失败容错、整轮失败记录不 crash、回填（-7~-2 立即 / 昨天今天待回填 / 失败重试 / 限速 / DAYS=0 关闭 / first_seen 夹取）、端点生命周期与 status 计数。HTTP 用可注入 `fetch_json` mock，零新依赖。
- `condenser/db.py` — `SCHEMA_VERSION=3`；`Subscription` 加 `source`/`name`/`config`，`channel_id` 改 `BareField`，复合 PK；`_migrate_subscriptions_v3()` 按表结构（无 `source` 列）检测并重建表；TG CRUD 全部加 `source='telegram'` 约束；新增 HN 订阅 CRUD（`get/add/update/delete_hn_subscription`、`hn_sampling_active`）与 `HNStory` 模型 + CRUD（sticky insert、快照更新、peak_rank 取最优、dead 标记、刷新窗口查询、计数）。
- `condenser/timeline.py` — 三处 subscriptions JOIN 加 `s.source='telegram'`。
- `condenser/config.py` — 新增 `CONDENSER_HN_ENABLED/POLL_INTERVAL/FRONT_SIZE/REFRESH_HOURS/BACKFILL_DAYS`。
- `condenser/hn.py` — 新增。`HNManager`：poll loop（wait_for + `kick()` 事件即时唤醒）、`poll_once`（无 enabled 订阅零请求跳过；采样 → 快照刷新（排除本轮已拉 id）→ 回填推进；状态写 `app_meta`）、hckrnews 逐日串行回填（`hn_backfill_pending` 日期集，满 2 天才可回填，失败留集重试）。
- `condenser/types.py` — `HNSubscribeBody` / `HNSubscriptionPatch`。
- `condenser/routers/hn.py` — 新增。POST/PATCH/DELETE `/api/sources/hn/subscriptions*`（v1 仅 `front`，非法 feed 422，订阅时 schedule_backfill + kick）、GET `/api/hn/status`。
- `condenser/app.py` — lifespan 创建 `app.state.hn` 并 startup/shutdown，挂 hn 路由。
- `frontend/src/lib/types.ts` / `api.ts` — `HnStatus` 类型 + `hnStatus/hnSubscribe/hnSetEnabled/hnUnsubscribe`。
- `frontend/src/components/subscriptions/HackerNewsSection.tsx` — 新增。Front Page 订阅/退订（ConfirmDialog）、采样暂停 Switch、状态行（存档数/今日/上次采样/待回填天数/错误），60s 轮询刷新。
- `frontend/src/pages/SubscriptionsView.tsx` — 挂载 `HackerNewsSection`。
- `AGENTS.md`（根 + frontend）— 架构/模块表/状态段更新，组件清单加 `HackerNewsSection`。

## 注意事项

- **迁移检测按表结构而非版本号**：`PRAGMA table_info(subscriptions)` 缺 `source` 列才重建，天然幂等，也覆盖版本号缺失的旧库。SQLite 改主键必须建新表→复制→改名，全程包在事务里，且要在 `create_tables`（IF NOT EXISTS 会跳过旧表）之前跑。
- **`BareField` 实现 channel_id 的 per-source 类型**：SQLite 无 affinity 列，TG 行存 int、HN 行存 str；TEXT 与 INTEGER 存储类在 SQLite 比较永不相等，所以 timeline 的整数 JOIN 天然不会撞到 `'front'` 行——但仍显式加了 `s.source='telegram'` 以明确语义。
- **可测性三件套**：可注入 `fetch_json`（替代 respx/网络 mock）、`_now()` 实例级覆盖（时间旅行测刷新窗口/回填资格）、限速间隔做成实例属性（测试置零）。HNManager 因此 17 个测试首跑全绿。
- **采样与刷新去重**：`poll_once` 里刷新阶段要排除本轮采样刚拉过的 id，否则每轮对新 story 重复请求一次。
- **first_seen_at 是 sticky 的**：入库用 `on_conflict_ignore`，同 id 再上首页不重置——这是 timeline append-only 排序语义的根基。
- **回填行的 first_seen_at** 用提交时间夹到归档日 `[00:00, 23:59:59]` 区间，天然落在历史位置不冲顶。
- 端点测试里要 `_quiet_hn()`（替换 fetch + 停掉 kick），否则 lifespan 里的后台 loop 会与断言竞态、甚至打真实网络。

## 遗留问题

- **Post-merge code review 发现 10 个已验证缺陷**（采样循环无兜底、null 误标 dead、pending 竞态、订阅端点状态处理、迁移缺 DEFAULT 等），修复 handoff：[HN Phase 1 review 修复清单](../plans/2026-07-19-hn-phase1-review-fixes.md)。
- Phase 2（envelope API + 统一 read/saved 表 + 联邦 timeline 归并）、Phase 3（web UI）、Phase 4（iOS）未开始；2-4 是 breaking，需按计划一起部署。
- `hn_stories` 尚无任何读取端（timeline 不展示 HN），本阶段只积累数据——属计划内。
- 回填的 `peak_rank` 为 NULL（hckrnews 不含名次信息），仅实时采样行有值。
- 部署前需确认生产 SQLite 备份机制就位（v3 迁移会重建 subscriptions 表）。

## 相关文档

- [多信源架构 + Hacker News 信源计划](../plans/2026-07-19-multi-source-hn.md) — 本次 session 依据此计划实施 Phase 1
