---
created: 2026-06-09
tags:
  - condenser
  - backend
  - todo
  - gap-analysis
---

# 后端剩余工作梳理（对照 spec.md 的缺口分析）

## 概要

接续同日的后端实现 session，本次对照 `spec.md` 系统性盘点了**后端已实现 vs 仍欠缺**的部分。结论：spec C2 的所有端点都已存在、§7 关键场景都有测试覆盖；但仍有少量 v1 该做的功能未做、若干健壮性缺口、以及部分端点缺直接测试。前端（Part D）已在另一个 session 进行中。

下面按优先级分组记录，供后续后端 session 直接 pick up。spec 明确推迟到 v1.1 的项不计入欠债。

## 待办

### 一、v1 spec 有、但未实现（优先补齐）

- [ ] **取消订阅的「连同消息删除」选项**（Q4 / C2 DELETE）：当前 `DELETE /api/subscriptions/{id}` 只做默认「保留消息」。需额外提供删除该频道消息的选项（如 `?purge=1`），删除 `messages`（收藏 `telegram_records` 自包含，不受影响）。
- [x] ~~**全局关键词规则的 API**（D9 / C5）~~：2026-06-18 完成。新增 `GET /api/filters` / `POST /api/filters` / `POST /api/filters/preview`（preview 复用 `filters.text_is_filtered`，对最近 1000 条消息做 dry-run）；旧的 `GET/POST /api/subscriptions/{cid}/filters` 同步删除，所有调用迁到新端点。前端新增 `/filters` 独立页 + `CreateFilterDialog`。
- [x] ~~**频道完整信息落库**（B1）~~：2026-06-24 完成（condenser 侧）。`TgManager._enrich_channel` 在订阅注册后台用 `GetFullChannelRequest` 取 `about` / `participants_count`，经 telememo 自己的 `get_or_create_channel`（写原生列，遵守契约）落库，`GET /api/subscriptions` 暴露 `member_count` / `description`。
- [x] ~~**接上 `app_meta`**（B2）~~：2026-06-24 完成。`init_db` 写 `schema_version`；`db.effective_backfill_days` 让 `app_meta` 的运行时覆盖优先于环境变量，`_backfill_channel` 经它解析；新增 `GET/PATCH /api/app/meta` 读写。

### 二、健壮性 / 正确性缺口

- [x] ~~**开启 SQLite WAL**~~：2026-06-24 完成。`db._enable_wal` 在 `init_db` 后执行 `PRAGMA journal_mode=WAL`（`:memory:` 跳过）。测试 `test_init_db_enables_wal`。
- [x] ~~**实时监听消息编辑**~~：2026-06-24 完成（telememo 0.2.0）。`service.subscribe` 同一 handler 注册 `NewMessage` + `MessageEdited`，`save_message_smart` 按 `edit_date` 变化原地更新 `text`，再 dispatch → condenser `_on_new_message` 重算 `is_filtered`。**需发布 telememo 0.2.0 + bump lock 才在 condenser 生效**。
- [ ] **backfill 批间隔**（A4「回填分批 + 间隔」）：已做分批 + FloodWait 退避，但未在批之间主动 sleep，回填大频道更易撞限流。
- [x] ~~**运行时 session 失效处理**~~：2026-06-24 完成。`TgManager._demote_session` 在 `UnauthorizedError`（AuthKeyUnregistered / SessionRevoked / UserDeactivated）时落地：丢弃 service、清空 session blob、置 `authorized=0`、断开旧 client；接在 `_backfill_channel` / `fetch_older` / `list_joined_channels` 的失败路径上。测试 `test_auth_error_demotes_session_to_unauthorized`。

### 三、测试覆盖缺口

- [ ] 补端点级测试：app/TG `logout`、`PATCH`/`DELETE` 订阅、`/api/read/bulk`、`/api/timeline/days`（channel 维度）、filters 列表端点、全局规则。
- [ ] （可选）有真实凭证后跑一次真实 Telegram 的端到端 smoke。

### 四、打包

- [ ] Dockerfile 多阶段**前端构建阶段**（待前端产物就绪后前置 node 阶段，COPY dist 并指向 `CONDENSER_STATIC_DIR`）。
- [ ] 实际跑通 `docker build` / `docker compose up --build` 验证。
- [ ] 构建上下文根目录加 `.dockerignore`（context = 父目录，避免把 `.venv`/`.git` 等打进去）。

## 注意事项（明确不算欠债，spec 已推迟 v1.1 / 非目标）

- 正则过滤（Q9）、基础搜索（Q5）、评论/讨论组展示（Q6）、媒体持久化离线（Q7/Q11）、SSE/WebSocket 推送（Q2，v1 即轮询 `/api/timeline/new`）、前端虚拟列表（Q3）。
- 物化机制已为正则预留：未来加 `keyword_filters.is_regex` + 改 `filters.text_is_filtered` 即可，**无需动查询**。
