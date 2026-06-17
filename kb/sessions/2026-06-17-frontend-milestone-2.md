---
created: 2026-06-17
tags:
  - condenser
  - frontend
  - react
  - shadcn
  - tanstack-query
  - telememo
  - milestone-2
---

# 实现 Condenser 前端 Milestone 2（订阅管理 / 日历 / 新内容轮询 / 媒体灯箱 / 设置 / 主题）

## 概要

承接 M1（脚手架 + 鉴权/TG 登录 + 时间线），本次按 `M2.md` 计划完成前端第二阶段。开工前先与用户敲定 `M2.md` §4 的待定决策：**D7** 用后端新增 `head_cursor`（而非前端复刻 cursor 编码）、**D6** 关键词规则只做频道级、**D8** 视频用内联 `<video>` 暂不做 Range、**D10/D11** 加主题切换（默认跟随系统）+ 真实频道头像、**D9** 砍掉键盘快捷键。**D1（时区）经核查确认后端是 UTC、`format.ts` 已正确处理，无需改动**。

为支撑前端，做了三处**小后端改动**（均带 pytest）：① `timeline.query_timeline` 返回 `head_cursor`（最新单元锚点，供 `/timeline/new` 轮询）；② telememo 新增 `TelegramService.get_channel_photo` + condenser 新路由 `GET /api/channels/{id}/avatar`（头像代理，不落盘）；③ `/api/tg/status` 附带 `phone`（供 Settings 显示）。前端则补齐 shadcn 组件（dialog/switch/dropdown-menu/popover/calendar/sonner）、订阅完整管理、批量已读、日历日期过滤、新内容悬浮提示、媒体灯箱、设置弹窗、主题系统（light/dark/system + 无 FOUC）、真实头像 + 字母兜底、单频道隐藏行内频道名、骨架屏，以及修掉 M1 遗留的 Unread/All NavLink 高亮冲突。

验证：后端 `pytest` **16 passed**（3 个新增）、前端 `pnpm build` 干净通过；用 `agent-browser` 起「强制 authorized」的 smoke server（`tmp/smoke_server.py`）对 seeded DB 跑通端到端：登录 → 时间线 → 设置切暗色（验证 `<html class=dark>` + localStorage）→ 日历（仅有消息的日期可选、`?date=` 过滤）→ 订阅管理（行操作菜单、关键词增删 → `is_filtered` 1↔0 往返、启停开关 → DB + 侧边栏）。

## 修改的文件

### 后端（condenser + telememo）
- `condenser/timeline.py` — 新增 `_unit_head()`；`query_timeline` 返回值加 `head_cursor`（page_units[0] 的最大 id 锚点）。
- `condenser/routers/channels.py`（新增）— `GET /api/channels/{id}/avatar`，调 `get_channel_photo` 流式回传、`Cache-Control`，无 service 时 503。
- `condenser/app.py` — 挂载 `channels.router`。
- `condenser/routers/tg.py` — `/status` 附带 `phone`（读 `db.get_tg_session().phone`，仅有值时附加）。
- `../telememo/telememo/service.py` — 新增 `get_channel_photo()`（`download_profile_photo(download_big=False)`，缓冲全量、不落盘）。
- `tests/test_backend.py` — 新增 `test_timeline_head_cursor_polls_only_newer`、`test_channel_avatar_proxy`、`test_tg_status_includes_phone`。

### 前端（`frontend/src/`）
- **UI 原语**：`components/ui/{dialog,switch,popover,dropdown-menu,calendar,sonner}.tsx`（取 shadcn new-york 源，改 `radix-ui` 统一包 → 各 `@radix-ui/react-*`、button 路径 → `@/components/ui/button`、去 `"use client"`）。装 `sonner`。
- **主题**：`lib/theme.tsx`（ThemeProvider + `useTheme`，localStorage `condenser-theme`，system 用 matchMedia 跟随）；`index.html` 去掉硬编码 `class="dark"`、加无 FOUC 内联脚本；`main.tsx` 包 ThemeProvider + 挂 `<Toaster />`。
- **订阅管理**：`pages/SubscriptionsView.tsx` 重写（开关 + 行 dropdown + 关键词/删除弹窗）；`hooks/useSubscriptionMutations.ts`（启停/删除，乐观）；`hooks/useFilters.ts`（关键词 CRUD，改后 invalidate timeline/subscriptions）；`components/subscriptions/KeywordFilterDialog.tsx`；`components/ConfirmDialog.tsx`（可复用确认弹窗）。
- **批量已读**：`hooks/useBulkRead.ts`（乐观 sweep + 计数归零）；`pages/TimelineView.tsx` 头部「Mark read」。
- **日历**：`hooks/useTimelineDays.ts`；`components/CalendarPopover.tsx`（仅有消息的日期可选，选中写 `?date=`）；`lib/format.ts` 加 `toDayKey`/`fromDayKey`/`dayKeyLabel`。
- **新内容轮询**：`hooks/useNewContent.ts`（30s 轮询、隐藏标签页暂停）；`components/timeline/Timeline.tsx` 加悬浮「N new messages」条 → refetch + 滚顶；`lib/types.ts` `TimelinePage` 加 `head_cursor`。
- **媒体灯箱**：`components/timeline/Lightbox.tsx`（全屏 overlay、相册 ←/→、Esc、img→video 自适应、锁滚动）；`MessageMedia.tsx` 缩略图改 button 触发灯箱、文件 chip 仍走链接。
- **设置 / 头像 / 打磨**：`components/SettingsDialog.tsx`（手机号 + 断开 TG + 锁定 + 主题三选）；`components/ChannelAvatar.tsx`（头像代理 + 字母/颜色兜底）；`Sidebar.tsx`（频道用头像、Settings 按钮、Manage channels 改 Radio 图标、修 Unread/All 高亮）；`MessageCard.tsx` `showChannel` prop；`components/timeline/TimelineSkeleton.tsx`；`lib/api.ts` 加 `errorMessage()` + `channelAvatarUrl()`、`tgStatus` 返回类型加 `phone`。

### 临时/调试（`tmp/`，gitignored）
- `tmp/smoke_server.py` — monkeypatch `TgManager.status='authorized'` 起服务、serve `frontend/dist`，对 `tmp/smoke.db` 做可视化 smoke。截图 `tmp/m2-*.png`。

## 注意事项

- **决策先行**：跨仓库/触发后端改动的决策（D6/D7/D8/D11）务必先与用户敲定再动手；纯前端默认项（D2/D3/D5/D12）取默认值并告知即可。
- **shadcn 源适配**：MCP 拉到的 registry 组件用 `radix-ui` 统一包 + `@/registry/...` 路径，本仓库装的是**各独立** `@radix-ui/react-*` 包、button 在 `@/components/ui/button`，需逐个改 import；删掉只在被裁剪组件里用到的 lucide 图标导入（否则 `noUnusedLocals` 报错）。`calendar` 依赖 `react-day-picker` v9 API（`getDefaultClassNames`/`DayButton`）。
- **head_cursor 设计**：取「页内最新单元的最大 id」作锚点（`_unit_head` 用 `max(id)`，区别于分页用的 `_unit_boundary` 取 `min(id)`），保证 `/timeline/new?after=` 用 `id > cid` 能整体排除该相册单元、不重复返回。前端只用第一页的 `head_cursor` 轮询。
- **主题无 FOUC**：`index.html` 内联脚本在 React 挂载前依据 localStorage/系统偏好打 `dark` class；ThemeProvider 在 system 模式下用 matchMedia 监听 OS 变化实时切换；sonner `<Toaster theme={resolvedTheme}>` 跟随。
- **日历日键对齐**：后端 `days`/`?date=` 用 UTC `substr(date,1,10)`；前端用本地日历单元，故 `toDayKey`/`fromDayKey` 都按**本地** Y-M-D 构造，使高亮单元与日键一致（避免时区错位）。
- **乐观更新沿用 M1 pattern**：timeline 用 `setQueriesData({queryKey:['timeline']})` 广播扫描，subscriptions 用 `setQueryData(['subscriptions'])`；关键词改动后端会重算 `is_filtered`，须 invalidate `['timeline']` + `['subscriptions']`。
- **smoke 局限**：无真实 TG session 时媒体/头像 503 → 走兜底（chip/字母），故灯箱、真实头像、新内容悬浮条、TG 注销无法可视化验证（逻辑靠 types/build + pytest + curl 覆盖）。
- **发现一个非 M2 的既有 bug（相册已读计数）**：标记相册已读只写主 id（如 5004），但 `timeline.unread_counts` 按 `COALESCE(grouped_id,id)` 计数、相册另一行（5005）仍 unread → 相册永远清不掉未读角标。属后端/读取逻辑，M1/后端遗留，M2 仅使其更显眼。建议后续按 TDD 修（标记时写全 `raw_message_ids`，或计数按 display unit）。

## 相关文档

- [前端 M1 session 总结](./2026-06-09-frontend-milestone-1.md) — 本次 session 承接的上一阶段
- [后端剩余工作清单](./2026-06-09-backend-remaining-work.md) — 参考：其中的「全局关键词规则 API」对应本次决策 D6（暂只做频道级）
