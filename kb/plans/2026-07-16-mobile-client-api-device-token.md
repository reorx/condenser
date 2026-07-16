---
created: 2026-07-16
tags:
  - backend
  - auth
  - mobile
  - api
---

# Backend: Device Token 认证 + 移动客户端 API 适配

为 iOS 阅读器（见同日 spec [2026-07-16-ios-reader-app.md](2026-07-16-ios-reader-app.md)）提供
token 认证能力。**现有业务 API 已满足客户端需求，本 spec 不新增任何业务端点**，只做认证层扩展 +
设备管理。

## 背景与结论

现状：所有 `/api/*` router 挂 `require_auth` 依赖（`condenser/auth.py:13`），仅接受签名 cookie
（`condenser_session`，密码登录后由 `routers/auth.py` 下发）。原生 iOS 客户端没有 cookie 语义，
需要 `Authorization: Bearer <token>`。

客户端 API 覆盖 review 结论（无需改动）：

| 客户端需求 | 现有端点 |
|---|---|
| Timeline（游标分页、频道/未读过滤） | `GET /api/timeline` |
| 新消息计数（"始终显示最新更新的消息条数"） | `GET /api/timeline/new?after=<head_cursor>` |
| 频道列表 + 未读数 | `GET /api/subscriptions` |
| 已读上报（批量） | `POST /api/read`、`POST /api/read/bulk` |
| 收藏（列表/添加/取消） | `GET/POST /api/records`、`DELETE /api/records/{cid}/{mid}` |
| 图片/头像/链接预览图 | `GET /api/media/...`、`/api/channels/{id}/avatar`、`/api/preview/image` |

管理类端点（filters、tg 登录、订阅增删）客户端不调用即可，无需独立命名空间。
消息详情无需单独端点：timeline item 携带全文；records 返回自包含快照。

## 设计

### 1. `devices` 表（condenser 侧新表）

peewee model，加入 `condenser/db.py`，绑定 telememo 的 `db` 实例，`init_db()` 中建表
（与现有 condenser 表同一批）：

```
Device:
  id            AutoField
  name          TextField            # 例如 "Reorx's iPhone"，授权时由客户端提供
  token_hash    CharField(unique)    # sha256 hex of raw token
  created_at    DateTimeField        # UTC
  last_seen_at  DateTimeField(null)  # UTC，节流更新
```

- 明文 token 只在签发响应中出现一次：`secrets.token_urlsafe(32)`；库中只存 sha256。
- token 无过期时间（单用户自部署），靠吊销（删行）失效。

### 2. 授权流程（web 跳转换 token）

```
iOS App → ASWebAuthenticationSession 打开
  https://<host>/authorize?device_name=<url-encoded name>
    ├─ 无 cookie session：现有 AppLogin 密码登录（复用现有 auth gate）
    ├─ 授权确认页："授权设备 <name>？" [授权] [取消]
    ├─ 确认 → POST /api/auth/device {name}（仅接受 cookie 认证）
    └─ 成功 → window.location = condenser://auth?token=<raw>&name=<name>
```

- `/authorize` 是**前端路由**（React Router），复用 `App.tsx` 的 auth gate。
- 取消 → 重定向 `condenser://auth?error=denied`，让 App 端能收敛会话。用户直接关闭
  `ASWebAuthenticationSession`（无回调）的处理在 iOS spec 侧（AuthFlow 收到 session
  cancel error 时回登录页）。

**⚠️ 前置工作项：SPA fallback。** `app.py:51` 的 `StaticFiles(html=True)` 只对目录请求返回
`index.html`，**不会**为未知路径 fallback——线上 `GET /authorize`、`/saved` 目前都是 404
（此前不可见，因为用户总是从 `/` 进入后走客户端路由；而本流程依赖冷加载 `/authorize`）。
需把静态挂载改为 catch-all：非 `/api` 且磁盘上无对应文件的路径一律返回 `index.html`。
这同时修复 `/saved`、`/filters` 等深链的既有 404。

### 3. 后端 API 变更

`condenser/routers/auth.py` 新增（全部**仅接受 cookie 认证**，防止被盗 device token 自我增殖）：

| 端点 | 行为 |
|---|---|
| `POST /api/auth/device` `{name}` | 创建 device，返回 `{id, name, token}`（token 仅此一次） |
| `GET /api/auth/devices` | `[{id, name, created_at, last_seen_at}]`（不含 hash） |
| `DELETE /api/auth/devices/{id}` | 吊销；不存在返回 404 |

实现"仅 cookie"约束：这三个端点用独立依赖 `require_cookie_auth`（即现有逻辑改名/拆出），
不走下述扩展后的 `require_auth`。

### 4. `require_auth` 扩展（`condenser/auth.py`）

```
1. Authorization: Bearer <token> 存在 → sha256(token) 按 token_hash 列（unique 索引）查 devices：
     命中 → 通过；last_seen_at 距今 > 1h 时才写库更新（节流，避免每请求写 SQLite）
     未命中 → 401（不再回落 cookie，避免掩盖 token 失效）
2. 无 Bearer header → 走现有 cookie 校验
```

其余所有 router **零改动**（它们只声明 `Depends(require_auth)`）。

图片类端点（media/avatar/preview image）**不加 query-param token**：iOS 端统一用带
header 的 URLSession 加载图片，认证方式保持单一（决策已确认）。

### 5. Web 设置：设备管理

前端设置目前是 `frontend/src/components/SettingsDialog.tsx`（对话框，无 `/settings` 路由）。
在该对话框内新增 "Devices" 区块：列出已授权设备（名称、创建时间、最后活跃），每行一个
Revoke 按钮（`DELETE /api/auth/devices/{id}` + confirm）。乐观更新 `['devices']` query，
错误走 sonner toast（沿用现有 mutation 模式）。若对话框空间局促，实现时可自行决定
折叠/滚动，不升级为独立页面。

新增 `/authorize` 路由页面：读取 `?device_name=`，展示确认卡片，确认后调
`POST /api/auth/device` 并跳转 `condenser://auth?token=...`。

## 测试（BDD：先写行为测试）

加入 `tests/`（沿用现有 TestClient + conftest 模式，注意 peewee 线程本地连接约定）：

1. 密码登录（cookie）→ `POST /api/auth/device` → 返回 token；库中存 hash 而非明文
2. 用该 token `Authorization: Bearer` 访问 `GET /api/subscriptions` → 200
3. 伪造/错误 token → 401；cookie 路径不受影响（原有测试保持绿）
4. `DELETE /api/auth/devices/{id}` 后，原 token → 401
5. 用 Bearer token 调 `POST /api/auth/device` → 401（仅 cookie 可发新 token）
6. `GET /api/auth/devices` 列表包含 name/created_at/last_seen_at，不含 token_hash
7. last_seen_at 节流：同一 token 连续两次请求只写一次（可 freeze 时间或直接断言值不变）

## 非目标

- token 过期/刷新机制（吊销已够用）
- 多用户、权限分级
- query-param token（图片走 header）
- 推送通知

## 实施顺序

1. `app.py`: SPA fallback（catch-all 返回 index.html，见 §2 前置工作项）
2. `db.py`: Device model + CRUD（create/get_by_hash/list/delete/touch_last_seen）
3. `auth.py`: `require_cookie_auth` 拆出 + `require_auth` 支持 Bearer
4. `routers/auth.py`: 三个 device 端点
5. tests（先写，红→绿；含 SPA fallback：未知路径返回 index.html、`/api/*` 不受影响）
6. frontend: `/authorize` 页 + SettingsDialog Devices 区块
