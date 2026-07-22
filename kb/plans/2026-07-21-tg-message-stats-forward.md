# Telegram 交互与转发：消息 stats（已读数 + reactions）+ 转发至本频道

日期：2026-07-21 ｜ 状态：✅ 完成（2026-07-22 验收通过：150 后端 + 42 前端用例全绿，真实会话走查 stats/两种转发模式均落地 @telememo_test，截图 `tmp/2026-07-21-tg-stats-forward/`）
范围：**后端 + web 前端**（iOS 下一批，API 契约按可被 CondenserKit 直接镜像设计）

> **iOS 批次也已完成**（2026-07-22，BDD）：Kit 新增 `ReactionCount`（未知 kind → `.other`
> 前向兼容）/`MessageStats`/`ForwardResult`/`AppMeta` 模型 + `APIClient` 四个方法
> （`messageStats` / `forwardMessage`（trim，空评论 body 不带 comment）/ `appMeta` /
> `setForwardChannel`，协议外方法，与 `mediaURL` 同级）；app 侧 `MessageDetailSheet`
> 加实时 stats 行（纯展示 `MessageStatsRow` + reaction chips，数据在 sheet 的 `.task`
> 拉取——`Group{if}.task` 空分支不触发的坑）、`ForwardDialog` sheet（预检 app_meta →
> 未配置引导/编辑/成功三态 + 错误映射）、设置页「转发」区块；debug 路由新增
> `forward/<cid>/<mid>[/<comment>]`（自动提交，真实网络）。124 Kit 测试全绿；
> 模拟器真实会话走查：stats 行、dialog、两种转发模式均真实落地 @telememo_test
> （t.me/s 页面验证），截图 `tmp/2026-07-22-ios-stats-forward/`。

## 1. 需求与已定决策

在 web 端消息侧边栏（`LinkPreviewPane`）中：

1. **展示消息的已读数（views）和 reactions** —— 打开面板时经 Telethon **实时拉取**
   （用户决策：不入库、无 schema 迁移；顺带返回 forwards 数）。
2. **「转发至本频道」按钮** → dialog：评论输入框 + 提示语
   「写上自己的看法会通过文字 + 链接引用的形式发布新消息」+ 取消/确认转发。
   - 评论**非空** → 发**新消息**：`评论文字\n\n<t.me 原消息链接>`（Telegram 自动生成引用预览卡）。
   - 评论**留空** → **原生 forward**（`client.forward_messages`，保留 "Forwarded from" 头）。
3. **目标频道**在设置页配置一次，存 `app_meta.forward_channel`（复用现有
   `GET/PATCH /api/app/meta`）。未配置时点转发按钮 → toast 引导去设置。

## 2. 架构决策

- **不动 telememo**。`TgManager` 直接调 `service.client.*` 已有先例
  （`_enrich_channel` 的 `get_entity`/`GetFullChannelRequest`、`list_joined_channels` 的
  `iter_dialogs`），`get_messages`/`forward_messages`/`send_message` 属同一层级。
  避免 telememo 发版耦合。
- **reactions 不持久化**：按请求取、按请求丢。类型带判别字段
  `kind: 'emoji' | 'custom' | 'other'` —— `ReactionEmoji` → emoji 字符、
  `ReactionCustomEmoji` → `document_id`（解析 glyph 需额外 RPC，v1 前端降级为
  通用图标 + 数量）、`ReactionPaid`/未来 TL 新类型 → `'other'` 降级不崩；
  另带 `chosen: bool`（`chosen_order is not None`，自己点过的 reaction 高亮）。
- **新 router 文件 `condenser/routers/messages.py`**，URL 前缀 `/api/messages`
  （与 `preview.py` 已有的 `/api/messages/{cid}/{mid}/previews` 同前缀、职责分文件：
  preview.py 无 Telethon 依赖，messages.py 走 TgManager 实时调用）。
  `app.py` + `routers/__init__.py` 各加一行注册。
- **t.me 链接由服务端构建**（不信任客户端传 URL）：channel 有 username →
  `t.me/{username}/{mid}`，否则 `t.me/c/{cid}/{mid}`（与前端 `tgMessageUrl` 同构）。
- **错误处理沿用 TgManager 类级惯例**：前台用户动作 → 只窄捕
  `UnauthorizedError` → `_demote_session()` + 重抛（router 译为 503）；
  消息不存在（`get_messages` 返回 None / forward 时 `MessageIdInvalidError`）→
  自定义 `TelegramMessageNotFound` → 404；`FloodWaitError` → 429 +
  `Retry-After: {seconds}` 头；其余异常原样冒泡为 500。

## 3. API 契约

### `GET /api/messages/{channel_id}/{message_id}/stats`

```jsonc
// 200（FastAPI 返回类型 = pydantic MessageStats，供 iOS 直接镜像）
{
  "views": 1234,          // null = 频道不带此数据
  "forwards": 56,         // null 同上
  "reactions": [
    { "kind": "emoji",  "emoji": "👍", "document_id": null,             "count": 12, "chosen": false },
    { "kind": "custom", "emoji": null, "document_id": 5368221678337263242, "count": 3, "chosen": true }
  ]
}
```
- 404 `{"detail": "message not found"}`（消息已删/坏 id）
- 429 + `Retry-After` 头（FloodWait）
- 503 `{"detail": "telegram not authorized"}`（预检或调用中掉线）

### `POST /api/messages/{channel_id}/{message_id}/forward`

```jsonc
// 请求：{ "comment": "值得一读" } 或 {} / {"comment": null}（原生 forward）
// 200：{ "status": "ok", "mode": "quote",   "link": "https://t.me/mych/123" }  // 有评论
//      { "status": "ok", "mode": "forward", "link": "https://t.me/mych/124" }  // 空评论
// link = 目标频道里新落地消息的 t.me 链接（前端 toast 带「打开」动作）
```
- 404 / 429 / 503 同上
- 422 `{"detail": "forward target channel not configured"}`

### `GET/PATCH /api/app/meta`（增量扩展）

```jsonc
// GET 新增字段："forward_channel": "@my_channel" | null
// PATCH：{ "forward_channel": "@my_channel" }；传 "" 清除（读回 null）
```

## 4. 改动清单

### 后端

| 文件 | 改动 |
|---|---|
| `condenser/tg.py` | pydantic 模型 `ReactionCount`（kind/emoji/document_id/count/chosen）+ `MessageStats`；异常 `TelegramMessageNotFound`；模块级 helper：`_normalize_target(str) -> str\|int`（纯数字转 int，@handle/t.me 链接原样给 Telethon）、`channel_message_url(cid, mid)`（查 `tdb.get_channel` 的 username，`/c/` 兜底）、`_convert_reactions(reactions)`（三分支 + 降级）。`TgManager` 新方法：`get_message_stats(cid, mid) -> MessageStats`（`client.get_messages(handle, ids=mid)`，None → `TelegramMessageNotFound`）、`forward_message(cid, mid, comment) -> dict`（读 `app_meta.forward_channel`，未配置 → `LookupError`；分支见 §1.2；返回含新消息 `link`，`send_message`/`forward_messages` 的返回值取 `sent.id` 拼链接） |
| `condenser/routers/messages.py` | **新文件**：`/api/messages` prefix + `require_auth`，两个端点（预检 503 惯例 + `TelegramMessageNotFound`→404 / `LookupError`→422 / `FloodWaitError`→429+Retry-After / `UnauthorizedError`→503）；`app.py` + `routers/__init__.py` 注册 |
| `condenser/types.py` | `ForwardMessageBody(comment: Optional[str])`；`AppMetaPatch` 加 `forward_channel: Optional[str]` |
| `condenser/routers/settings.py` | GET 返回 `forward_channel`（`get_meta` or None）；PATCH 写入（strip 后存，'' 即清除） |
| `tests/test_message_actions.py` | 新文件，见 §5 |

### 前端

| 文件 | 改动 |
|---|---|
| `components/ui/textarea.tsx` | **新增** shadcn new-york Textarea 原语（对照 `input.tsx` 风格） |
| `lib/types.ts` | `ReactionCount` / `MessageStats` / `AppMeta` |
| `lib/api.ts` | `messageStats` / `forwardMessage` / `getAppMeta` / `patchAppMeta` |
| `hooks/useMessageStats.ts` | **新增**：镜像 `useLinkPreviews`，`staleTime: 0` + `refetchOnWindowFocus: false`（每次开面板取最新） |
| `hooks/useAppMeta.ts` | **新增**：`useAppMeta()`（staleTime 60s）+ `useSetForwardChannel()` mutation（成功 invalidate，失败 toast） |
| `components/timeline/ReactionChip.tsx` | **新增**：一个 reaction 圆片（`kind='emoji'` → emoji 字符，`'custom'`/`'other'` → 通用图标；`chosen` → 高亮 ring/bg）+ count ——按「循环体必须引用组件」规则单独抽出 |
| `components/timeline/MessageStatsRow.tsx` | **新增**：views（Eye + `compactNumber`）/ forwards（Repeat2）/ reaction chips；pending 或全空时渲染 null |
| `components/timeline/ForwardDialog.tsx` | **新增**：仿 `AddByHandleDialog` —— 标题「转发到我的频道」、`DialogDescription` 提示语（用户指定中文文案，见 §1.2；app 其余 UI 为英文，此处特意保留中文）、Textarea（placeholder「留空则原样转发…」）、取消/确认转发（pending → Spinner）、成功 toast 带「打开」动作（`window.open(result.link)`）+ 关闭重置 |
| `components/timeline/LinkPreviewPane.tsx` | `SheetHeader` 下加一行：`MessageStatsRow` + Forward 按钮（`useAppMeta` 无 `forward_channel` → `toast.info` 引导设置）；挂 `ForwardDialog`（仅 TG target） |
| `components/SettingsDialog.tsx` | 新 Forward 区块：Input（@channel / t.me 链接）+ Save，接 `useAppMeta`/`useSetForwardChannel` |
| `frontend/CLAUDE.md` | 组件清单加 3 行（MessageStatsRow / ReactionChip / ForwardDialog）+ hooks 列表加 2 个（**同一提交内**，清单维护规则） |
| `MessageStatsRow.test.tsx` / `ForwardDialog.test.tsx` | 新组件测试，见 §5 |

## 5. 测试（BDD——先写测试后实现）

### 后端 `tests/test_message_actions.py`

沿用 per-file `_client()`/`_login()`/fake service 惯例（模板：`test_backend.py` 的
raw-client mock，`tg.service = MagicMock()` + `AsyncMock` per-call）：

1. `test_message_stats_returns_views_forwards_and_reactions` —— mock `get_messages` 返回带
   views/forwards/普通 emoji + 自定义 emoji（含 `chosen_order`）reactions 的对象 → 精确 JSON 断言
   （kind/emoji/document_id/count/chosen 全字段）
2. `test_message_stats_unknown_reaction_kind_degrades_to_other` —— `ReactionPaid` 形状 → `kind='other'` 不崩
3. `test_message_stats_404_when_message_missing` —— `get_messages` 返回 None
4. `test_message_stats_503_when_unauthorized` —— `tg.service = None`
5. `test_message_stats_429_on_flood_wait` —— `get_messages` 抛 `FloodWaitError` → 429 + `Retry-After` 头
6. `test_forward_empty_comment_uses_native_forward` —— 设 `forward_channel='@mychannel'`，
   POST `{}` → `mode='forward'` + `link` 指向目标频道新消息 id，断言 `forward_messages('@mychannel', mid, …)`
7. `test_forward_with_comment_sends_quote_message_with_link` —— channel 带 username，
   POST 评论 → `mode='quote'`，断言 `send_message` 文本 == `'评论\n\nhttps://t.me/{username}/{mid}'`
8. `test_forward_uses_private_link_when_channel_has_no_username` —— 文本含 `t.me/c/{cid}/{mid}`
9. `test_forward_whitespace_comment_treated_as_empty` —— `'  '` → 原生 forward
10. `test_forward_422_when_target_not_configured`
11. `test_forward_503_when_unauthorized`
12. `test_app_meta_forward_channel_roundtrip` —— PATCH 设值 → GET 读回；PATCH `''` → 读回 null

### 前端（vitest）

- `MessageStatsRow.test.tsx`：渲染 views/forwards 数字 + emoji chip + 自定义 emoji 降级图标；
  全空数据渲染 null。mock `@/lib/api`（`vi.mock`）+ `QueryClientProvider` 包裹。
- `ForwardDialog.test.tsx`：提示语 + 两按钮呈现；输入评论 + 确认 →
  `api.forwardMessage(cid, mid, '评论')`；留空确认 → comment 为 `undefined`；成功后关闭 + toast。

## 6. 实施顺序（teammate 执行）

1. **后端 BDD**：写 `test_message_actions.py`（全红）→ 实现 `tg.py` helpers + 方法 →
   router 端点 → types + settings.py → `uv run pytest` 全绿（现有 138 后端用例不回归）
2. **前端 BDD**：`textarea.tsx` → types/api → 写两个组件测试（红）→ 实现
   hooks + ReactionChip + MessageStatsRow + ForwardDialog（绿）
3. **接线**：LinkPreviewPane + SettingsDialog + `frontend/CLAUDE.md` 清单 →
   `pnpm test` 全绿 + `pnpm build` 通过
4. **验收**：本地起 dev（后端 :8792 + 前端 :5792），真实登录会话下走查：
   开面板看 stats、配置目标频道、空评论 forward、带评论 quote 转发，截图归档
   `tmp/2026-07-21-tg-stats-forward/`（含面板 stats 行、dialog、设置区块、目标频道收到消息的证据）

## 7. 边界与已知限制

- **Album**：stats/forward 只作用于点击的那条 `message_id`（面板 target 只有单 id）；
  原生 forward 单条相册成员只转那一张。**记为 v1 限制**，不为此扩 `PaneTarget`。
- **自定义 emoji**：不做 `GetCustomEmojiDocuments` 解析，UI 通用图标 + 数量。
- **FloodWait**：429 + `Retry-After`，前端 toast 提示稍后再试。
- **目标频道无效**（handle 打错、无发言权）：不特判，冒泡 500 →
  前端 fallback toast。后续可收紧为 422。
- **调用中掉线**：窄捕 `UnauthorizedError` → `_demote_session()` → 503；
  与现有 tg-status 门机制自然衔接，无需改 `useTgStatus`。
- **空/纯空白评论**：前后端双重 strip（后端为准）。
- **转发成功后无缓存失效需求**：新消息只有目标频道恰好也被订阅时才会出现在 timeline，
  由正常 realtime ingest 兜住，不特判。

## 8. 不做（明确出圈）

- iOS 端 UI（下一批；API 契约已按 Kit 镜像友好设计）
- reactions 入库 / 列表页展示 stats（如需，后续在卡片上用已入库的 `views` 另起小任务）
- 转发历史记录、每次转发时选目标频道
