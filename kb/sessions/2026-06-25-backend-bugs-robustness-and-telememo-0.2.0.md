---
created: 2026-06-25
tags:
  - backend
  - robustness
  - telememo
  - sqlite-wal
  - app-meta
  - telegram
  - session-invalidation
  - release
---

# 后端 bug 修复 + 健壮性补强 + telememo 0.2.0 发布

## 概要

本次从「检查所有 *.md 给出下一步建议」开始,通读 `spec.md` / `README.md` / `M2.md` /
`AGENTS.md` / `kb/sessions/*` 并与仓库实际状态交叉核对,发现两处文档与现实不符:Docker
文件已存在但 Dockerfile 仍是纯 Python 单阶段(前端构建未接),README 严重过时(还说前端没
做)。用户随后选择推进一批后端任务,逐个 TDD/BDD 实现并独立 commit。

完成的 7 项:**3a** SQLite WAL、**4b** app_meta(schema 版本 + 运行时 backfill_days 覆盖)、
**2a** 相册未读(发现早已修好,仅更正过时文档)、**2b** 启动时实体缓存预热(私有频道重启后
头像/媒体不再挂)、**3c** 运行时 session 失效 demote、**4a** 频道完整信息(member_count /
description)、**3b** 实时消息编辑(`MessageEdited`)。

关键设计取舍:**4a 放 condenser 侧**(用 telememo 公开的 `get_or_create_channel` 写,既守
原生列契约又零发布耦合);**3b 放 telememo 侧**(实时订阅生命周期本就在
`service.subscribe`,拆开会重复一套 add/remove 逻辑)。3b 因此需要发布 telememo 才能在
condenser 生效。期间发现本地 `../telememo` checkout 落后 origin 8 个 commit、缺 `service.py`,
`git pull` 后才与已发布的 0.1.0 源对齐——这是能在 telememo 侧开发的前提。

收尾阶段起了一个 subagent 完成发布:**telememo 0.2.0 已发布到 PyPI**,两个仓库的 feature
分支都已合并回各自 `master`,condenser 的 `uv.lock` 升级到 telememo 0.2.0,全套测试绿
(condenser 51 passed,telememo 28 passed)。git 改动均**只在本地**(都领先 origin、未 push)。

## 修改的文件

### condenser(分支已并入 `master`,7 commits)

- `condenser/db.py` — `_enable_wal`(init 后 `PRAGMA journal_mode=WAL`,`:memory:` 跳过);
  `SCHEMA_VERSION=1` + init 时写 `app_meta.schema_version`;`effective_backfill_days(env_default)`
  让 app_meta 运行时覆盖优先于环境变量(非法/缺失回退)。
- `condenser/tg.py` — `_warm_entity_cache`(startup 后台经 `list_joined_channels`/`iter_dialogs`
  重注册私有频道 access_hash);`_is_auth_error` + `_demote_session`(`UnauthorizedError` 时丢
  service、清 session blob、置 `authorized=0`、断开旧 client),接在 `_backfill_channel` /
  `fetch_older` / `list_joined_channels` 失败路径;`_enrich_channel`(订阅后台
  `GetFullChannelRequest` 取 `about`/`participants_count`,经 `tdb.get_or_create_channel` 落库);
  `_backfill_channel` 改用 `db.effective_backfill_days(...)`。
- `condenser/routers/settings.py`(新建) — `GET/PATCH /api/app/meta`(schema_version 只读 +
  backfill_days 覆盖,正整数校验)。`condenser/app.py` 注册该 router。
- `condenser/routers/subscriptions.py` — `GET /api/subscriptions` 增 `member_count` / `description`。
- `condenser/types.py` — `AppMetaPatch`。
- `tests/test_backend.py` — 新增 WAL、app_meta(含 backfill 覆盖)、startup 预热、session demote、
  channel enrich 共 6 个测试。
- `AGENTS.md`(`CLAUDE.md` 是其 symlink)、`kb/sessions/2026-06-09-backend-remaining-work.md` —
  更正/勾掉已完成项,记录「3b 需 telememo 0.2.0 发布 + bump lock」。
- `uv.lock` — telememo 0.1.0 → **0.2.0**(commit `53ac283`)。

### telememo(分支 `feat/realtime-message-edits` 已并入 `master`,1 commit,已发 PyPI)

- `telememo/service.py` — `subscribe` 用**同一 handler** 注册 `NewMessage` + `MessageEdited`;
  `update_subscription` 两个事件都重注册;`unsubscribe` 无需改(`remove_event_handler(cb)` 不
  传 event 会移除该回调的所有注册)。
- `telememo/__init__.py` — 版本 0.1.0 → **0.2.0**。
- `tests/test_part_a.py` — `test_subscribe_handles_new_and_edited`(编辑同一 id 原地更新 text)。

## 注意事项

- **相册未读 bug 早已修好**:`db.mark_read` 的 `_expand_album_siblings` + `mark_read_bulk` 已覆盖,
  且有 `test_read_album_clears_unread_count` 等回归测试。AGENTS.md 的 known-bug note 是过时的——
  动手前先核对现状,别照旧文档重复造轮子。
- **跨仓库前先对齐 telememo checkout**:本地 `../telememo` 曾落后 origin 8 个 commit、缺
  `service.py`,一度误判为「published wheel 的源没进 git」。`git pull` 后才与 0.1.0 对齐。要改
  telememo 前务必先 `git fetch && git pull`。
- **3b 优雅地放 telememo,4a 务实地放 condenser**:判断标准是「生命周期归属」与「发布耦合成本」。
  3b 的订阅生命周期在 telememo,拆开 condenser 会复制 add/remove;4a 只是一次性取数 + 经 telememo
  自己的 writer 落库,放 condenser 零耦合且不破契约。
- **edit 复用 NewMessage 路径**:`save_message_smart` 按 `should_update_record(edit_date)` 原地
  UPDATE 原生列(保住 `is_filtered`);同一 handler 服务两个事件,condenser 的 `_on_new_message`
  对 dispatch 出来的 edit 重算 `is_filtered`,**condenser 无需任何代码改动**即可受益。
- **WAL 是文件头持久属性**:`PRAGMA journal_mode=WAL` 执行一次即写入 db 头,后续每线程新连接自动
  继承;`:memory:` 不支持需跳过。
- **session demote 要断开旧 client**:`UnauthorizedError`(AuthKeyUnregistered / SessionRevoked /
  UserDeactivated 都是其子类)永不自愈;只置 service=None 不够,旧 Telethon client 会后台一直
  重连刷错误日志,必须 `await old.disconnect()`。
- **测试 spawned 后台任务别走 TestClient**:portal 线程的 event loop 让 spawn 的 backfill/enrich
  竞态;直接 `asyncio.run(tg._backfill_channel(...))` / `tg._enrich_channel(...)` 才确定性。构造
  `UnauthorizedError` 用无参 `__init__` 子类绕过 telethon 的 RPCError 构造签名。
- **发布耦合的交付顺序**:telememo 改动 → 合 master → `uv build` + `uv publish`(用
  `/tmp/uv.env` 凭据)→ 等 PyPI 可用 → condenser `uv lock --upgrade-package telememo` → `uv sync`
  → 测试 → 提交 lock。本地用 editable overlay(`uv pip install -e ../telememo` + `UV_NO_SYNC=1`)
  先验证,再 `uv sync` 还原回 PyPI 以保持提交态与 lock 一致。
- **当前 git 状态**:condenser 与 telememo 都在 `master`、都领先 origin **未 push**;本轮唯一对外
  操作是被授权的 telememo PyPI 发布。剩余 v1 收尾仅 Docker 多阶段前端构建 + README(spec 步骤 9)、
  以及 Q4「取消订阅连同消息删除」、backfill 批间隔 sleep。
