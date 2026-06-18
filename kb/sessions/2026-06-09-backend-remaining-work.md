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
- [ ] **频道完整信息落库**（B1）：`resolve_channel` 用 `get_entity`，拿不到 `member_count` / `description`。需要 `GetFullChannelRequest` 才能填 `channels.member_count`（订阅列表目前无成员数）。
- [ ] **接上 `app_meta`**（B2）：表与 get/set helper 已就绪，但未用于「schema 版本」与「`backfill_days` 运行时覆盖」。当前 backfill 天数只读环境变量。

### 二、健壮性 / 正确性缺口

- [ ] **开启 SQLite WAL**（性价比最高）：sync 路由跑在 threadpool（多线程多连接），实时入库写 + 用户写并发时可能偶发 `database is locked`。建议 `init_db` 后执行 `PRAGMA journal_mode=WAL`。
- [ ] **实时监听消息编辑**：当前只订阅 `events.NewMessage`，未订阅 `MessageEdited`，频道消息被编辑后 realtime 不会更新 `text` / 重算 `is_filtered`。
- [ ] **backfill 批间隔**（A4「回填分批 + 间隔」）：已做分批 + FloodWait 退避，但未在批之间主动 sleep，回填大频道更易撞限流。
- [ ] **运行时 session 失效处理**：启动 connect 失败有兜底；运行中 session 被 revoke / AuthKeyError 未专门处理（Telethon 会自动重连，但鉴权失效不会自愈）。

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
