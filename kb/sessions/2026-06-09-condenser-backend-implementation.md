---
created: 2026-06-09
tags:
  - condenser
  - telememo
  - backend
  - fastapi
  - telegram
  - bdd
---

# 按 spec.md 实现 Condenser 后端（Part A telememo 改造 + Part B/C condenser 后端）

## 概要

本次 session 按 `spec.md` 的构建顺序（§6 步骤 1–7 + 打包）从零实现了 Condenser 的**后端部分**。Condenser 是自部署、单用户的 Telegram Channel 聚合阅读器，复用 `../telememo`（可编辑路径依赖）作为频道数据源，与其**共用同一个 SQLite 文件**。

实现分两层：

1. **Part A — 改造 telememo**（`../telememo` 仓库）：遵循其「只增不毁、低抽象、low-level 不吞异常」原则，新增单一 DB 模式 + 扩展列机制、转发字段落库、`TelegramService` 高层门面（程序化分步登录 / backfill / subscribe / get_media）。A3（DisplayMessage 组装）发现已提前迁到 `utils.py`，仅需让其支持从 DB 列读取转发信息。
2. **Part B/C — condenser 后端**（本仓库）：uv 包结构 + FastAPI，实现 App 密码门禁、TG 分步登录、订阅 + 回填、实时入库、关键词过滤**物化**到 `is_filtered`、跨频道时间线（游标分页 + 相册合并 + 日期/未读过滤 + 已读/收藏标记）、收藏（来源解耦快照）、媒体按需代理。

遵循用户 BDD 方法论：用 mock Telegram 写行为测试。**telememo Part A 12 个测试全过，condenser 后端 13 个测试全过**，覆盖 spec §7 所有关键场景。最后 `git init` + 初始提交。

调试中定位到一个关键坑：pytest + Starlette TestClient 下，peewee 连接是**线程本地**的，lifespan 在 portal 线程跑而 seed 在主线程跑，导致 `close_db()` 关不掉主线程的陈旧连接，跨测试串到上一个测试的 DB 文件 → `UNIQUE constraint failed`。解决：fixture teardown 显式关主线程连接。

## 修改的文件

### telememo（`../telememo`，尚未提交，独立仓库）
- `telememo/types.py` — `MessageData` 增加 `fwd_*` 字段；新增 `SignInResult` 模型。
- `telememo/db.py` — `Message` 模型加转发列；`init_db(db_path, optional_fields=...)` 支持扩展列（幂等 ALTER）+ 缺失原生列的轻量迁移；create 路径持久化转发字段。
- `telememo/telegram.py` — 把 `convert_channel_to_info` / `convert_message_to_data` 提升为模块级函数（供 service 复用 raw client）；转换时填充转发字段。
- `telememo/utils.py` — `group_messages_to_display(raw_messages_map=None)` 可从 DB 列构建 `ForwardInfo`（新增 `forward_info_from_row`）。
- `telememo/service.py`（新）— `TelegramService` 门面：connect/disconnect/is_authorized、send_code/sign_in_code/sign_in_2fa/export_session、resolve_channel、backfill（FloodWait 退避）、subscribe/update_subscription/unsubscribe/is_listening、get_media。
- `tests/test_part_a.py`（新）— 12 个 mock-Telegram 测试（A5 验收）。
- `pyproject.toml` — `asyncio_mode = "auto"`。

### condenser（本仓库）
- `condenser/config.py` — pydantic-settings 读环境变量。
- `condenser/crypto.py` — Fernet 加密 session + itsdangerous 签名 cookie，均从 `CONDENSER_SECRET_KEY` 派生。
- `condenser/db.py` — condenser 表（peewee 模型绑定到 telememo 的 `db` 实例）+ CRUD + `init_db`（先 telememo 表/`is_filtered`，再 condenser 表）。
- `condenser/filters.py` — 关键词过滤物化（入库后 + 规则变更重算）。
- `condenser/timeline.py` — 时间线查询：游标分页、相册合并、日期/频道/未读过滤、已读/收藏标记、days/new/unread_counts。
- `condenser/records.py` — 收藏快照（self-contained `raw_data`）+ 从快照渲染（不依赖 telememo 表）。
- `condenser/tg.py` — `TgManager`：生命周期、分步登录→加密存储、实时入库→重算 is_filtered、回填调度、订阅编排。
- `condenser/auth.py` + `condenser/routers/*` — App 密码门禁依赖 + 全部 C2 端点。
- `condenser/app.py` + `condenser/__main__.py` — FastAPI 工厂 + lifespan + uvicorn 入口；存在前端构建目录则挂静态资源。
- `tests/conftest.py` + `tests/test_backend.py` — 13 个后端行为测试。
- `Dockerfile` / `docker-compose.yml` / `.env.example` / `README.md`（含 D2 风险标注） / `.gitignore` / `pyproject.toml`。

## 注意事项

- **peewee 线程本地连接坑**：测试中 TestClient 在 portal 线程跑 lifespan，sync route handler 在 threadpool 跑，seed 在主线程跑——每个线程各有连接。换 DB 文件时必须关闭主线程的陈旧连接，否则 autoconnect 复用旧连接串到上个测试的库。生产环境无此问题（单库长连接，SQLite 锁可应付单用户）。
- **扩展列不被覆盖的契约**：telememo 的 smart-save 只写原生列（`Message.create`/`Message.update` 列举字段，`is_filtered` 不在模型里），所以增量更新天然不清空 condenser 的 `is_filtered`。关键是 telememo 不能用整行 `INSERT OR REPLACE`。
- **过滤是物化而非查询时计算**：匹配逻辑放写入侧（`filters.py`），查询只读布尔列 `is_filtered`，性能好且为正则预留（未来只改计算函数 + 加 `is_regex`）。
- **收藏来源解耦**：`telegram_records.raw_data` 存 album 全部消息行的自包含快照；即使 telememo `messages` 被清，收藏仍能渲染（测试 `test_record_is_source_decoupled` 删行后仍渲染验证）。
- **游标分页 + 相册**：相册行同 date、相邻 id；取 `limit + buffer` 行后按 grouped_id 合并为 display unit，cursor 锚定 unit 内最小 id；边界用保守 `has_more`（buffer 填满即认为有更多）避免漏数据。
- **环境有 formatter hook**：保存时自动把代码改成单引号风格（与全局「不要自动格式化」偏好冲突，但那是 harness 的 PostToolUse hook，非本人执行）；已顺其风格保持一致。
- **Docker 构建上下文**：condenser 依赖 `../telememo` 路径，构建上下文须同时包含 `telememo/` 与 `condenser/`（compose 用 `context: ..`）。
- **未完成**：Part D（React SPA，构建步骤 8）未做，它也是多阶段 Docker 镜像的前端阶段。telememo Part A 改动在独立仓库**尚未提交**。
