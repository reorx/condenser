# Condenser — 项目规格 (Spec)

> 本文件由 `draft.md` 经逐句审阅 + 决策澄清后产出,目标是让 agent 可直接照此执行开发。
> 草稿原文保留在 `draft.md`,本文是其工程化展开。

---

## 1. 项目概述

Condenser 是一个**自部署、单用户**的 Telegram Channel 信息聚合阅读器——本质是「把信息源从 RSS 换成 Telegram Channel」的类 Google Reader 阅读器。

用户用自己的 Telegram 账号登录,订阅若干 Channel,Condenser 把这些 Channel 的更新聚合成一条**跨频道、按时间倒序**的时间线,提供高信息浓度、清爽优雅的 Power User 级阅读体验。

**核心理念(设计基调,贯穿全程):**
- 优化信息获取流程,信息浓度高但不拥挤。
- 进入主界面先看今日最新,可按日期回溯。
- 向下滚动即阅读,**肉眼扫过即视作已读**。
- 提供有效信息,克制装饰。

**数据架构理念:来源解耦的 records(贯穿设计):**
Condenser 把**用户明确珍视的数据**(如收藏)以**自包含**形式存进 `<source>_records` 表——v1 即 `telegram_records`,每行带 `raw_data` 全量原始数据快照。由此:
- 用户关心的数据与具体数据源(telememo 的频道表)**解耦**:即使 telememo 的 `messages` 被清空、或 condenser 脱离 telememo 独立运行,收藏内容仍可完整浏览。
- 未来接入新数据源(RSS、Mastodon...)各自新增 `xxx_records` 表,共享同一「records」抽象。
- 心智模型:频道原始数据(`channels`/`messages`)是**可重建的缓存**;`telegram_records` 是**不可再生的用户资产**。

---

## 2. 目标 / 非目标

### v1 目标(In Scope)
- 用 Telegram 用户账号(MTProto)登录,分步式 web 登录流程(验证码 + 2FA)。
- 订阅/取消订阅 Channel;每个 Channel 可配置**排除关键词**过滤。
- 跨频道聚合时间线:按天分组、倒序、无限向下滚动回溯。
- 滚过即已读(IntersectionObserver 自动标记)+ 未读计数。
- 单条消息收藏 + 收藏夹视图。
- 消息渲染:文本(含 Telegram entities)、媒体(按需代理缩略图/原图)、相册分组、转发来源。
- App 级单密码门禁。
- Docker 单容器部署。

### 非目标(Out of Scope,v1 不做)
- ❌ 多用户 / App 级账号体系(单用户自部署定位)。
- ❌ 评论/讨论组展示(telememo 有抓取能力,但 v1 不在 UI 呈现;列为 v1.1 候选)。
- ❌ 媒体持久化/离线缓存(只做按需代理,不落盘)。
- ❌ 富链接预览(webpage preview 卡片);v1 只渲染 URL 文本 + entities。
- ❌ 发送消息 / 与 Channel 互动(纯只读阅读器)。
- ❌ 全文搜索的高级形态(telememo 当前只是普通索引,非 FTS5);v1 至多提供基础 LIKE 搜索,列为 v1.1。

---

## 3. 决策记录 (Decision Log)

| # | 决策点 | 结论 | 影响 |
|---|---|---|---|
| D1 | 用户模型 | 单用户自部署 | 无 App 账号体系,单份 TG session |
| D2 | Telegram 接入 | MTProto 用户账号(复用 telememo / Telethon) | 非 Bot;有封号/限流风险,须标注 |
| D3 | telememo 角色 | 作为依赖库,**为其新增 high-level 接口** | 见 Part A |
| D4 | 媒体处理 | 按需代理 + 缩略图,**不持久化** | 需 telememo 暴露媒体取流 |
| D5 | 抓取策略 | **实时增量 + 订阅时回填近 N 天** | 需 telememo 加事件监听 + 按日期回填 |
| D6 | 存储边界 | telememo 提供**单一 DB 模式**(保留原 per-channel 模式);condenser **直接读 telememo 的表**作为频道数据源,叠加自己的 app-state 表 | 见 Part B |
| D7 | 前端 | React SPA (Vite) | 前后端分离,后端吐 JSON API |
| D8 | App 鉴权 | 单密码门禁 + 签名 session cookie | 见 Part C |
| D9 | 关键词过滤 | **仅排除 + 子串匹配(不区分大小写)**;v1 子串,架构预留正则 | **物化**到 telememo `messages.is_filtered` 扩展列(非查询时计算),见 C5 |

**风险标注(D2):** 自动化 Telegram 用户账号属 ToS 灰色地带,个人自用风险低;须在 README 标注,并在抓取层做 FloodWait 退避。Session string 等同账号钥匙,**必须加密存储**。

**存储边界补充(D6):** condenser 对 telememo 的表遵循「**默认列只读 + 扩展列读写**」契约:telememo 原生列由 TelegramService 写、condenser 只读;condenser 经 `init_db(optional_fields=...)` 在 telememo 表上增设的列(如 `messages.is_filtered`)由 condenser 读写,**telememo 增量更新时不得覆盖**(见 A1)。

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│  单个 Python 进程 (condenser backend)                          │
│                                                               │
│  ┌────────────────┐   ┌──────────────────────────────────┐  │
│  │ FastAPI (async)│   │ telememo.TelegramService (新增)   │  │
│  │  - JSON API    │◀─▶│  - 程序化分步登录                  │  │
│  │  - /media 代理 │   │  - resolve / backfill(offset_date)│  │
│  │  - app 鉴权    │   │  - subscribe(实时 NewMessage)      │  │
│  └───────┬────────┘   │  - get_media(按需取流)            │  │
│          │            └───────────────┬──────────────────┘  │
│          │ 读                          │ 写(单一 DB 模式)    │
│          ▼                             ▼                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  SQLite (单一文件)                                      │   │
│  │  telememo 表: channels / messages(+is_filtered 扩展列) │   │
│  │              / comments                                │   │
│  │  condenser 表: subscriptions / keyword_filters /       │   │
│  │     read_messages / telegram_records / tg_session /    │   │
│  │     app_meta                                           │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────────────▲───────────────────────────────┘
                                │ HTTP (JSON + 静态资源)
                        ┌───────┴────────┐
                        │ React SPA (Vite)│
                        └─────────────────┘
```

**关键数据流:**
1. **入库(写原生列):** TelegramService 在「单一 DB 模式」下,把订阅频道的**回填**(近 N 天)和**实时**新消息,经 telememo 既有存储逻辑**全量**写入 `channels`/`messages`。
2. **过滤物化(condenser 写扩展列):** 新消息入库后(及关键词规则变更时),condenser 按规则计算并写 `messages.is_filtered`(见 C5)——过滤是**预计算的布尔列**,不在查询时算。
3. **读:** condenser 查 `messages`(`WHERE is_filtered IS NOT 1` + `subscriptions(enabled=1)`)LEFT JOIN `read_messages`/`telegram_records`,`ORDER BY date DESC` 分页 → 时间线 API。
4. **收藏(写用户资产):** 收藏某消息时,condenser 从 telememo 表取该消息全量数据,连同 `raw_data` 快照写入 `telegram_records`,与数据源解耦(§1 records 理念)。
5. **媒体:** 前端 `<img src="/api/media/{channel_id}/{message_id}?thumb=1">` → 后端调 `TelegramService.get_media` 流式回传,不落盘。

**进程模型:** 单进程、单 event loop。FastAPI 与 Telethon client 共享 asyncio loop;实时监听与回填作为后台 `asyncio.Task` 运行。单用户并发低,无需独立 worker 进程。

**telememo 依赖形态:** 本地可编辑路径依赖(co-development)。condenser `pyproject.toml`:
```toml
[tool.uv.sources]
telememo = { path = "../telememo", editable = true }
```

---

## Part A — telememo 改造规格

> 原则:**只增不毁**。telememo 现有 CLI / per-channel 行为保持可用,新增能力以新模块 / 新参数形式提供。遵循 telememo 自身 CLAUDE.md 的轻量、低抽象、low-level 不吞异常原则。

### A1. 单一 DB 模式(对应 D6)
- 现状:`messages` 表已是 `(channel, id)` 联合唯一索引、`date` 带索引——**schema 天然支持多频道共存**;per-channel 只是 `init_db()` 传了不同路径。
- 改造:让 `init_db(db_path)` 既能用于单一统一库,也能用于 per-channel 库。新增一个明确的入口/参数表达「单一 DB 模式」,供 condenser 传入统一 `db_path`。保留 `config.get_db_path(channel_id)` 的 per-channel 行为给 telememo CLI。
- **扩展列机制(`optional_fields`,对应 condenser 的过滤需求):** `init_db(db_path, optional_fields=None)` 新增参数,允许调用方声明在 telememo 表上**额外的 nullable 列**;建表后用 `PRAGMA table_info` 检测,缺失则 `ALTER TABLE ... ADD COLUMN`(幂等)。形如:
  ```python
  init_db(db_path, optional_fields={
      "messages": [{"name": "is_filtered", "type": "BOOLEAN", "default": 0}],
  })
  ```
  - 这些列**不属于** telememo 的 Peewee 模型,由调用方(condenser)读写,用于在 telememo 数据上叠加 condenser 语义(此处:过滤标记)。condenser 用它实现过滤,是因为查询时实时过滤性能差、且难支持正则。
  - **关键约束:** telememo 的增量同步/更新(`save_messages_batch_smart` 等)**只写自己的原生列**,不得覆盖扩展列——即编辑同步必须用「按列 UPDATE」,而非整行 `INSERT OR REPLACE`。
- 验收:多个频道写入同一 `db_path` 后,`SELECT ... FROM messages ORDER BY date DESC` 跨频道返回正确;声明 `is_filtered` 后该列存在、telememo 增量更新一条消息不清空其 `is_filtered`。

### A2. 转发字段落库(消除现有缺口)
- 现状:`Message` 表无转发列;`_convert_message_to_data` 不提取 `fwd_from`(telememo CLAUDE.md 已列为 TODO)。
- 改造:
  - `Message` 表新增列:`is_forwarded`、`fwd_from_channel_id`、`fwd_from_channel_name`、`fwd_from_user_name`、`fwd_from_message_id`、`fwd_original_date`、`fwd_post_author`(对齐 `ForwardInfo`)。
  - `MessageData` 增加对应字段;`_convert_message_to_data` 调用 `extract_forward_info()` 填充。
  - 提供轻量迁移(新增列,`ALTER TABLE`/重建均可,单用户可接受)。

### A3. DisplayMessage 组装提升为库内函数
- 现状:`group_messages_to_display()` / `extract_forward_info()` 埋在 `scripts/debug_messages.py`。
- 改造:迁移到库内稳定模块(如 `telememo/display.py` 或 `telememo/utils.py`),供 condenser 直接调用,把同一 `grouped_id` 的相册合并为单个 `DisplayMessage`、附 `ForwardInfo` 与聚合统计。

### A4. 高层门面 `TelegramService`(新增,Part A 的核心)

新增模块 `telememo/service.py`,提供**storage-agnostic、可程序化认证、长生命周期**的门面。底层尽量复用现有 `telegram.py`。

```python
class TelegramService:
    # ---- 构造 / 生命周期 ----
    def __init__(self, api_id: int, api_hash: str, session: str | None = None): ...
        # session: Telethon StringSession 字符串;None 表示尚未登录
    async def connect(self) -> None: ...        # 建立连接(不触发交互)
    async def disconnect(self) -> None: ...
    @property
    def is_authorized(self) -> bool: ...

    # ---- 分步登录(替代交互式 client.start)----
    async def send_code(self, phone: str) -> str: ...
        # 返回 phone_code_hash;底层 client.send_code_request
    async def sign_in_code(self, phone: str, code: str, phone_code_hash: str) -> SignInResult: ...
        # 成功 -> SignInResult(status="ok", session=<StringSession>)
        # 需要 2FA -> SignInResult(status="2fa_required")
    async def sign_in_2fa(self, password: str) -> SignInResult: ...
        # 成功 -> SignInResult(status="ok", session=<StringSession>)
    def export_session(self) -> str: ...        # 导出当前 StringSession 供 condenser 加密存储

    # ---- 频道 ----
    async def resolve_channel(self, handle: str) -> ChannelInfo: ...
        # 解析 @username / t.me 链接 / id -> ChannelInfo(复用 get_channel_info)

    # ---- 回填(对应 D5,新增 offset_date 支持)----
    async def backfill(self, channel, since_days: int | None = None,
                       since_date: datetime | None = None,
                       persist: bool = True) -> AsyncIterator[DisplayMessage]: ...
        # 复用 iter_messages 的 offset_date 拉取近 N 天;persist=True 时经 telememo 存储层入库

    # ---- 实时(对应 D5,telememo 当前完全没有)----
    async def subscribe(self, channels: list[int],
                        on_message: Callable[[DisplayMessage], Awaitable[None]] | None = None,
                        persist: bool = True) -> None: ...
        # 注册 events.NewMessage(chats=channels);新消息入库(persist) + 回调 condenser
    async def update_subscription(self, channels: list[int]) -> None: ...
        # 订阅集合变化时动态调整监听的 chats

    # ---- 媒体代理(对应 D4)----
    async def get_media(self, channel: int, message_id: int,
                        thumb: bool = False) -> tuple[AsyncIterator[bytes], str]: ...
        # 返回 (字节流, mime_type);thumb=True 取缩略图。底层 download_media / iter_download。不落盘。
```

**`SignInResult` / 配置解耦:**
- `TelegramService` 纯参数构造,**不依赖** `~/.config/telememo/config.py`(那是 telememo CLI 的事)。
- Session 以 **StringSession 字符串**进出,持久化由 condenser 负责(加密)。

**限流:** `backfill` / `subscribe` 内部对 `FloodWaitError` 做退避重试(尊重 `e.seconds`),回填分批 + 间隔。

### A5. telememo 改造验收(BDD,集成测试为主)
- 单一 DB 模式下两个频道入库,跨频道按日期查询有序。
- `send_code → sign_in_code`(mock Telegram)产出可用 StringSession;`export_session` 往返可重连。
- `backfill(since_days=7)` 只回填近 7 天;`subscribe` 收到新消息触发 `on_message` 且入库。
- `get_media` 对图片消息返回非空字节流 + 正确 mime。
- 转发消息入库后 `DisplayMessage.forward_info` 完整。

---

## Part B — condenser 数据模型

condenser 与 telememo 共用**同一个 SQLite 文件**。对 telememo 的表,condenser 遵循「**默认列只读 + 扩展列读写**」契约(见 A1 `optional_fields`);此外 condenser 新增自己的 app-state 表与用户资产表。

### B1. 复用 telememo 的表(默认列只读 + 扩展列可写)
- `channels`(只读):`id, title, username, description, member_count, last_sync_message_id, last_sync_at, added_at`
- `messages`(原生列只读):`channel, id, text, date, sender_id, sender_name, views, forwards, replies, is_edited, edit_date, media_type, has_media, grouped_id` + (A2 新增的转发列)
  - **扩展列(condenser 经 `optional_fields` 增设,读写):** `is_filtered`(BOOLEAN,关键词过滤的物化结果;condenser 计算并写入,telememo 不碰)。
- `comments`:v1 不用。

### B2. condenser 新增表

```sql
-- 订阅(channel_id 引用 telememo channels.id)
CREATE TABLE subscriptions (
  channel_id     INTEGER PRIMARY KEY,
  enabled        BOOLEAN NOT NULL DEFAULT 1,
  backfill_done  BOOLEAN NOT NULL DEFAULT 0,   -- 回填是否完成
  added_at       DATETIME NOT NULL
);

-- 排除关键词【规则】(D9:仅排除、子串、不区分大小写;v1 子串,预留正则)
-- 这是过滤的"规则源";计算结果【物化】到 telememo 的 messages.is_filtered(见 C5)
CREATE TABLE keyword_filters (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id  INTEGER,                 -- NULL = 全局规则
  pattern     TEXT NOT NULL,           -- 存原文;匹配时两侧 lower() 做 substring
  created_at  DATETIME NOT NULL
);

-- 已读(显式记录,支持回溯;滚过即写)
CREATE TABLE read_messages (
  channel_id  INTEGER NOT NULL,
  message_id  INTEGER NOT NULL,        -- DisplayMessage 主 id
  read_at     DATETIME NOT NULL,
  PRIMARY KEY (channel_id, message_id)
);

-- 用户资产:收藏的 telegram 记录(来源解耦、自包含)
-- 未来其他数据源 → 新增 <source>_records 表(见 §1 records 理念)
CREATE TABLE telegram_records (
  channel_id  INTEGER NOT NULL,
  message_id  INTEGER NOT NULL,        -- DisplayMessage 主 id
  raw_data    TEXT NOT NULL,           -- 收藏时从 telememo 表取的全量原始数据(JSON 快照),自包含
  created_at  DATETIME NOT NULL,
  PRIMARY KEY (channel_id, message_id)
);

-- 单份 TG session(加密)+ 登录态;单行
CREATE TABLE tg_session (
  id              INTEGER PRIMARY KEY CHECK (id = 1),
  phone           TEXT,
  session_enc     BLOB,                -- 加密后的 StringSession
  authorized      BOOLEAN NOT NULL DEFAULT 0,
  updated_at      DATETIME
);

-- 杂项(schema 版本、backfill_days 覆盖等)
CREATE TABLE app_meta (
  key    TEXT PRIMARY KEY,
  value  TEXT
);
```

**说明:**
- 关键词过滤**物化**到 `messages.is_filtered`(telememo 扩展列):入库后 + 规则变更时由 condenser 计算写入;查询只读布尔列(性能好、易支持正则,见 C5)。改规则后须**重算**受影响范围,即对历史生效。
- `telegram_records.raw_data` 自包含快照 → 即使 `messages` 被清空或脱离 telememo,收藏的**文本/结构**仍可浏览(§1 records 理念)。**注意边界:** 媒体按 D4 不落盘、按需代理,故脱离源时媒体无法加载;若要收藏内容完全离线,需 v1.1 给 records 增加媒体持久化(列为开放项 Q11)。
- `read_messages` 显式记录支持「向下滚回溯到很久以前的未读仍标未读」。单用户体量,SQLite 足够。
- `session_enc` 用 `CONDENSER_SECRET_KEY` 派生密钥加密(如 Fernet)。

---

## Part C — condenser 后端

### C1. 运行时生命周期
启动时:
1. 连接 SQLite,建表/迁移。
2. 读 `tg_session`;若 `authorized` 且有 session → 用 `TelegramService(api_id, api_hash, session)` `connect()`。
3. 若已授权:读 `subscriptions(enabled=1)` → `subscribe(channels)` 启动实时监听;对 `backfill_done=0` 的频道排后台回填任务。
4. 起 FastAPI;挂载 React 构建产物为静态资源。

### C2. API 端点(JSON,除特别说明外均需 app 鉴权)

**鉴权 / TG 登录**
| Method | Path | 说明 |
|---|---|---|
| POST | `/api/auth/login` | App 密码 → 校验 → 下发签名 session cookie |
| POST | `/api/auth/logout` | 清除 cookie |
| GET | `/api/tg/status` | TG 登录态(unauthorized / awaiting_code / awaiting_2fa / authorized) |
| POST | `/api/tg/send-code` | body `{phone}` → 调 `send_code`,暂存 `phone_code_hash` |
| POST | `/api/tg/sign-in` | body `{code}` → `sign_in_code`;成功则加密存 session、`authorized=1`、启动监听 |
| POST | `/api/tg/sign-in-2fa` | body `{password}` → `sign_in_2fa` |
| POST | `/api/tg/logout` | 注销 TG 会话,清 `tg_session` |

**订阅管理**
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/subscriptions` | 列出订阅(含频道信息、未读数) |
| POST | `/api/subscriptions` | body `{handle}` → `resolve_channel` → 入 `subscriptions` → 触发回填近 N 天 + 加入实时监听 |
| PATCH | `/api/subscriptions/{channel_id}` | 启用/停用 |
| DELETE | `/api/subscriptions/{channel_id}` | 取消订阅(移出监听;消息保留与否见开放问题 Q4) |
| GET | `/api/subscriptions/{channel_id}/filters` | 列关键词 |
| POST | `/api/subscriptions/{channel_id}/filters` | 加排除关键词 |
| DELETE | `/api/filters/{id}` | 删关键词 |

**时间线 / 阅读**
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/timeline` | 跨频道时间线;query:`cursor`(分页游标,基于 date+id)、`limit`、`channel_id`(可选单频道)、`date`(可选,`YYYY-MM-DD`,只取该日 → 支持**日历组件**查看「某频道某天」)、`unread_only`(可选)。返回 `DisplayMessage` + `is_read` + `is_saved`,`WHERE is_filtered IS NOT 1` + 订阅过滤,`ORDER BY date DESC` |
| GET | `/api/timeline/days` | 可选:返回「有消息的日期」列表(+每日计数),供日历组件标记可选日期/跳转;query `channel_id`(可选) |
| GET | `/api/timeline/new` | 轮询新消息:query `after=<cursor>`,返回比游标更新的条目(给前端「有新内容」提示) |
| POST | `/api/read` | body `{items:[{channel_id,message_id}]}` 批量标已读(滚过即上报) |
| POST | `/api/read/bulk` | body `{channel_id?, before_date}` 标某频道/某日期前全部已读 |
| GET | `/api/records` | 收藏(records)列表;从 `raw_data` 渲染,不依赖 telememo 表 |
| POST | `/api/records` | body `{channel_id, message_id}`;收藏 → 从 telememo 取全量数据写入 `telegram_records.raw_data` |
| DELETE | `/api/records/{channel_id}/{message_id}` | 取消收藏 |

**媒体代理(对应 D4)**
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/media/{channel_id}/{message_id}` | 调 `get_media` 流式回传原图/视频;`?thumb=1` 取缩略图。设置合理 `Cache-Control`(浏览器缓存,服务端不落盘) |

### C3. 时间线查询(关键)
- 基础:`messages` JOIN `subscriptions(enabled=1)` ON channel,**`WHERE messages.is_filtered IS NOT 1`**,LEFT JOIN `read_messages` / `telegram_records`。
- 关键词过滤:**不在查询时算**,直接读物化列 `is_filtered`(物化逻辑见 C5)→ 查询是简单布尔谓词,性能好。
- 日期过滤(可选 `date`):`WHERE date(messages.date) = :date`,配合 `channel_id` → 日历查看某频道某天。
- 相册:同 `grouped_id` 用 A3 的 `group_messages_to_display` 合并为单条 `DisplayMessage`(查询需多取同组行)。
- 游标分页:`(date, id)` 复合游标,稳定倒序。
- 标记:`is_read = read_messages 命中`,`is_saved = telegram_records 命中`。

### C4. App 鉴权(D8)
- 环境变量 `CONDENSER_APP_PASSWORD` 设单密码。
- `/api/auth/login` 校验后下发**签名 cookie**(HttpOnly、SameSite=Lax;用 `CONDENSER_SECRET_KEY` 签名)。
- 其余 API 依赖中间件校验 cookie。静态资源可放行,数据 API 必须鉴权。

### C5. 关键词过滤语义(D9,精确定义 + 物化机制)
- **规则:** 仅**排除**;**子串**匹配;**不区分大小写**(v1)。规则存 `keyword_filters`,作用对象为消息 `text`(含 caption)。
- **作用域:** 全局规则(`channel_id IS NULL`)对所有频道生效 + 频道专属规则。
- **物化(而非查询时计算,对应反馈 #1):** 过滤结果写入 telememo 扩展列 `messages.is_filtered`。理由:① 查询只需布尔列,性能远好于每条跑匹配;② 复杂匹配(正则)放在 Python 写入侧算,易实现且不拖慢查询。
- **计算时机:**
  1. **入库后:** 新消息(回填/实时)入库后,condenser 对其计算 `is_filtered`(经 `subscribe` 的 `on_message` 回调 / 回填后处理)。
  2. **规则变更:** 增删某频道(或全局)关键词时,**重算**受影响范围内消息的 `is_filtered`(一次批量 UPDATE)。
- **正则预留:** v1 仅子串;因计算在 Python 写入侧,未来加正则规则**无需改查询**,只改计算函数 + `keyword_filters` 增一个 `is_regex` 标志位即可。

---

## Part D — condenser 前端 (React SPA / Vite)

### D1. 视图
1. **登录页:** App 密码门禁 → 若 TG 未登录,引导 TG 分步登录(输手机号 → 验证码 →(需要时)2FA)。
2. **主界面(时间线):** Google Reader 式,跨频道聚合。
   - 顶部为**今日**,按天分组(day header),倒序;向下无限滚动 = 回溯更早。
   - 左侧/抽屉:频道列表 + 各自未读数;可切「全部 / 单频道 / 仅未读 / 收藏(records)」。
   - **日历组件:** 选频道 + 选日期 → 看「某频道某天」(`/api/timeline?channel_id=&date=`);有消息的日期可由 `/api/timeline/days` 标记。
   - 高信息浓度:紧凑行,频道名 + 时间 + 文本摘要/全文 + 媒体缩略图 + 转发来源徽标 + views。
3. **订阅管理:** 添加(输入 @handle / t.me 链接)、启停、删除、配置排除关键词。
4. **收藏(records)视图:** 列出 `telegram_records`,**从 `raw_data` 渲染**——不依赖 telememo 表,即使原始消息已清理仍可完整浏览(§1 records 理念)。

### D2. 关键交互
- **滚过即已读:** `IntersectionObserver` 监听每条消息;当其**底部滚出视口顶部**(完全划过)→ 加入待上报队列,**防抖批量** `POST /api/read`。前端乐观更新 `is_read`。
- **无限滚动:** 触底用游标拉下一页;考虑长列表性能(虚拟列表可选,见开放问题)。
- **收藏:** 每条消息一个收藏按钮,乐观更新;收藏即把该消息全量数据**快照**存入 `telegram_records.raw_data`(源解耦)。
- **新内容提示:** 前端聚焦/定时轮询 `/api/timeline/new`,有新内容显示「N 条新消息」提示条,点击插入顶部。

### D3. 消息渲染规则
- **文本:** 渲染 Telegram message entities(粗体/斜体/`code`/链接/spoiler 等);URL 渲染为可点链接,**不**抓富预览卡片(v1)。
- **媒体:** `media_type=photo` → 缩略图 `?thumb=1`,点击放大取原图;`video` → 缩略图 + 点击流式播放(`/api/media/...`);其它(文档/音频)→ 图标 + 文件名(可下载链接走代理)。
- **相册:** `is_album` → 媒体网格,整体作为一条。
- **转发:** `is_forwarded` → 显示「转自 {from_channel_name}」徽标。
- **已读态:** 已读条目视觉弱化(降低对比/灰化),但仍在流中可回溯。

---

## 5. 配置与部署

### 环境变量
| 变量 | 说明 |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | my.telegram.org 申请 |
| `CONDENSER_APP_PASSWORD` | App 门禁密码 |
| `CONDENSER_SECRET_KEY` | cookie 签名 + session 加密派生 |
| `CONDENSER_DB_PATH` | SQLite 路径(默认数据卷内) |
| `CONDENSER_BACKFILL_DAYS` | 订阅时回填天数,默认 **7** |

### 部署
- **单容器**:Python 后端同时服务 JSON API 与 React 构建产物(`/` 静态、`/api/*` 接口)。
- SQLite 文件挂数据卷持久化。
- 提供 `docker-compose.yml`(一个 service + 一个 volume)与 `Dockerfile`(多阶段:构建前端 → 拷进 Python 镜像)。

---

## 6. 构建顺序(BDD 优先)

> 遵循用户方法论:新功能先写**行为测试用例**,再实现。下列每步先落 BDD 场景(见 §7),再编码。

1. **telememo 改造**(Part A):单一 DB 模式 → 转发字段 → DisplayMessage 提升 → `TelegramService`(分步登录 / backfill offset_date / subscribe / get_media)。集成测试(mock Telegram)。
2. **condenser 骨架**:项目脚手架(uv 包结构)、依赖 telememo、SQLite 建表/迁移、配置加载。
3. **鉴权**:App 密码门禁 + cookie 中间件;TG 分步登录端点 + session 加密存储。
4. **订阅 + 回填**:`resolve_channel`、`subscriptions` CRUD、订阅触发回填近 N 天。
5. **实时入库**:`subscribe` 后台任务,新消息入库。
6. **过滤物化 + 时间线 API**:`is_filtered` 计算(入库后 + 规则变更重算)→ 跨频道查询(读 `is_filtered`)+ 相册合并 + 游标分页 + `date` 过滤 + 已读/收藏标记。
7. **媒体代理**:`/api/media`。
8. **前端**:登录 → 时间线(无限滚动 + 滚过即已读 + 日历)→ 订阅管理 → 收藏(records,从 `raw_data` 渲染)→ 消息渲染。
9. **打包**:Dockerfile + compose;README(含 D2 风险标注)。

---

## 7. BDD 关键行为场景(示例,实现前补全)

```gherkin
Feature: 订阅频道并回填
  Scenario: 新增订阅触发近 N 天回填
    Given 已登录 Telegram 且 App 已鉴权
    When 我用 "@technews" 新增订阅
    Then 该频道写入 subscriptions
    And 近 CONDENSER_BACKFILL_DAYS 天的消息入库到 messages
    And 时间线能看到这些消息

Feature: 滚过即已读
  Scenario: 消息划出视口后标记已读
    Given 时间线有未读消息 M
    When M 完全滚出视口顶部
    Then 前端批量上报 M 为已读
    And 重新加载后 M 显示为已读、对应频道未读数减一

Feature: 关键词排除(物化到 is_filtered)
  Scenario: 排除含关键词的消息(不区分大小写)
    Given 频道 C 设了排除关键词 "AD"
    And C 有消息文本包含 "广告ad促销"
    Then 该消息 messages.is_filtered 被置为 1
    And 时间线不返回该消息
    When 我删除该关键词
    Then 该频道消息的 is_filtered 被重算为 0
    And 该消息重新出现在时间线

Feature: 日历查看某频道某天
  Scenario: 按日期 + 频道过滤
    Given 频道 C 在 2026-06-01 有 3 条消息
    When 我请求 /api/timeline?channel_id=C&date=2026-06-01
    Then 只返回该频道该天的 3 条消息(倒序)

Feature: 实时增量
  Scenario: 订阅频道发新帖即时入库
    Given 已订阅频道 C 且实时监听运行中
    When C 发布一条新消息
    Then 该消息经 subscribe 入库
    And 前端轮询 /api/timeline/new 能发现它

Feature: 收藏(来源解耦)
  Scenario: 收藏写入自包含 raw_data
    Given 时间线有消息 M
    When 我收藏 M
    Then telegram_records 出现一行,raw_data 含 M 的全量数据
    And 即使 messages 中的 M 被删除,收藏视图仍能完整渲染 M
    When 我取消收藏 M
    Then telegram_records 不再有 M

Feature: 媒体按需代理
  Scenario: 图片走代理且不落盘
    Given 消息 M 含图片
    When 前端请求 /api/media/{c}/{M}?thumb=1
    Then 后端经 TelegramService.get_media 流式回传缩略图
    And 服务端磁盘无持久化媒体文件
```

---

## 8. 待确认的开放问题(我提议的默认值,审阅时可红线)

| Q | 问题 | 提议默认 |
|---|---|---|
| Q1 | 回填天数 N | **7 天**,`CONDENSER_BACKFILL_DAYS` 可配 |
| Q2 | 实时→前端推送 | v1 **前端轮询** `/api/timeline/new`;SSE/WebSocket 列为可选增强 |
| Q3 | 长列表性能 | v1 先普通渲染 + 分页;若卡顿再上**虚拟列表**(react-virtuoso 之类) |
| Q4 | 取消订阅后旧消息 | 默认**保留**已入库消息(仅停止抓取、移出订阅过滤);提供「连同消息删除」选项。注:收藏(`telegram_records`)自包含 `raw_data`,**任何情况都不受影响** |
| Q5 | 搜索 | v1 不做;telememo `text` 仅普通索引,v1.1 提供基础 LIKE 搜索 |
| Q6 | 评论/讨论组 | v1 不展示;v1.1 作为消息详情可选展开 |
| Q7 | 媒体缓存策略 | 不落盘;仅靠浏览器 `Cache-Control` 缓存代理响应 |
| Q8 | 多账号 | 明确不支持(单用户单 session 定位) |
| Q9 | 关键词正则 | v1 仅子串;物化机制已为正则预留(`keyword_filters.is_regex` + Python 侧计算),作为 v1.1 |
| Q10 | is_filtered 重算成本 | 规则变更时对受影响频道批量 UPDATE;单用户量级可接受,无需异步队列 |
| Q11 | 收藏媒体离线 | v1 records 只自包含文本/结构,媒体仍按需代理(脱离源不可见);v1.1 可选给 records 持久化媒体 |

---

## 附:与 draft.md 的对应关系
- draft「订阅定制 + 关键词过滤」→ Part B/C(D9 仅排除子串)+ §7。
- draft「Google Reader 式、按日期、滚过即已读」→ Part D(D1/D2)。
- draft「收藏」→ Part C/D + `telegram_records` 表(来源解耦,见 §1 records 理念)。
- draft「类 RSS、信息浓度高且清爽」→ §1 理念 + Part D 渲染规则。
- draft「自部署、登录自己的 TG 账号」→ D1/D2 + Part A(TelegramService 分步登录)+ §5 部署。
