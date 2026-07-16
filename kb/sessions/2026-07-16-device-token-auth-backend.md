---
created: 2026-07-16
tags:
  - backend
  - auth
  - mobile
  - frontend
  - spec
---

# 手机版阅读器需求讨论、两份 spec 定稿，并实施后端 device token 认证

## 概要

本次 session 从零开始讨论 condenser 手机版阅读器的需求：确定了原生 iOS (SwiftUI) 形态、
web 跳转授权换 device token 的认证方案、滚动即已读、详情用底部 sheet、轻量缓存等关键决策，
产出两份经 reviewer subagent 审阅通过的 spec（后端 + iOS，均在 `kb/plans/`）。审阅过程中
发现一个关键问题：`StaticFiles(html=True)` 不为未知路径回退 index.html，线上 `/authorize`、
`/saved` 冷加载 404，而授权流程依赖冷加载——已纳入 spec 并实施修复。随后按 BDD 流程完成
后端 spec 全部实施：先写 8 个行为测试（红），再实现 `devices` 表、Bearer 认证、三个设备管理
端点、SPA fallback、前端 `/authorize` 授权页和 SettingsDialog Devices 区块（绿），最后在
隔离环境用真实浏览器端到端走通了 冷加载 → 密码门 → 授权 → `condenser://` 回调 全流程。
66 个后端测试全部通过，前端 build 无错。

## 修改的文件

**Spec（新建）**
- `kb/plans/2026-07-16-mobile-client-api-device-token.md` — 后端 device token 认证 spec
- `kb/plans/2026-07-16-ios-reader-app.md` — iOS 阅读器 App spec（monorepo `ios/` 目录）

**后端**
- `condenser/db.py` — 新增 `Device` model（`token_hash` unique，只存 sha256）+ CRUD +
  `touch_device_last_seen`（1h 节流）；`SCHEMA_VERSION` 1 → 2
- `condenser/crypto.py` — 新增 `hash_device_token()`
- `condenser/auth.py` — 拆出 `require_cookie_auth`；`require_auth` 支持 `Authorization: Bearer`
  （Bearer 存在时单独裁决，不回落 cookie）
- `condenser/routers/auth.py` — `POST /api/auth/device`、`GET /api/auth/devices`、
  `DELETE /api/auth/devices/{id}`（均仅 cookie 认证）
- `condenser/app.py` — `SPAStaticFiles`：404 时非 `/api` 路径回退 index.html
- `condenser/types.py` — `DeviceCreateBody`
- `tests/test_device_auth.py` — 新增 8 个行为测试

**前端**
- `frontend/src/pages/AuthorizeView.tsx` — 设备授权页（新建）
- `frontend/src/App.tsx` — `/authorize` 在 TG 门之前渲染（只需 cookie session）
- `frontend/src/components/DeviceList.tsx` — 设备列表 + 吊销（新建）
- `frontend/src/components/SettingsDialog.tsx` — 挂入 Devices 区块
- `frontend/src/lib/api.ts` / `types.ts` — device 接口与 `Device` 类型
- `frontend/AGENTS.md` / 根 `AGENTS.md` — 组件清单与 auth/app 描述同步

## 注意事项

- **spec 审阅 subagent 抓到了真 bug**：Starlette `StaticFiles(html=True)` 只对目录请求返回
  index.html，SPA 深链需要自己做 catch-all fallback。审阅 agent 实测了线上 URL 验证该问题，
  说明 spec review 环节让 reviewer 对照真实代码/环境验证声明是值得的。
- **Bearer 不回落 cookie**：`require_auth` 里 Bearer header 存在时单独裁决，避免浏览器里
  失效 token 被 cookie 掩盖，客户端能第一时间收到 401。
- **设备管理端点仅 cookie**（`require_cookie_auth`）：被盗 device token 无法自我增殖或吊销
  其他设备。
- **明文 token 只出现一次**（签发响应），库中只有 sha256；`last_seen_at` 写库按 1h 节流，
  避免热路径每请求写 SQLite。
- **图片认证只走 header**：iOS 端统一用带 `Authorization` header 的 URLSession 加载图片，
  不做 query-param token，认证面保持单一。
- agent-browser 的 `find text "Authorize" click` 会命中标题 "Authorize device" 而不是按钮；
  用 `snapshot` 拿 ref 再 `click e4` 更可靠。

## 遗留问题

- SettingsDialog 的 Devices 区块未在浏览器中实际点开验证（隔离环境无 TG 登录进不了主界面）；
  本地 dev 环境打开设置即可确认。
- iOS App spec（阶段 2-4：认证、核心阅读、补全）尚未实施；`ios/` 骨架（阶段 1）已由
  另一 session 完成。
- 设备吊销只在 web 端提供；iOS 登出仅清本地 Keychain，不调吊销接口（spec 既定决策，非缺陷）。

## 相关文档

- [后端 device token 认证 spec](../plans/2026-07-16-mobile-client-api-device-token.md) — 本次 session 新建并完整实施
- [iOS 阅读器 App spec](../plans/2026-07-16-ios-reader-app.md) — 本次 session 新建，待后续实施
