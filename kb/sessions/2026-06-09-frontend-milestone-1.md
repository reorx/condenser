---
created: 2026-06-09
tags:
  - condenser
  - frontend
  - react
  - vite
  - tailwind
  - shadcn
  - tanstack-query
---

# 实现 Condenser 前端 Part D 第一阶段(脚手架 + 鉴权/TG 登录 + 时间线)

## 概要

后端(spec Part A/B/C)已在上个 session 完成,本次按 spec **Part D** 开始前端开发。开工前与用户确认了三项决策:UI 栈用 **Tailwind + shadcn/ui**、Telegram entities v1 只做**纯文本 + URL 自动链接**(后端尚未持久化 entities)、采用**分阶段带检查点**的交付节奏。

第一阶段(M1)交付:项目脚手架(React 19 + Vite 6 + TS strict + Tailwind v4 + shadcn/ui new-york + TanStack Query v5 + React Router v7,pnpm)、App 密码门禁 + 全局 401 回登录、TG 分步登录向导、跨频道时间线(游标无限滚动 + 滚过即已读 + 消息渲染 + 侧边栏未读数 + 加频道)、收藏视图(从 `raw_data` 渲染)、只读订阅列表。

开发后用 dummy TG 凭据起后端(端口 8011,因 8000 被占)+ vite dev,并往 throwaway DB seed 样例消息,用 `agent-browser` 实际渲染验证了 登录 → TG 连接 → 时间线 → 收藏 → 移动端 全流程。过程中定位并修复一个关键 bug:全局 401 handler 无差别 invalidate `tg-status` query,而 `tg-status` 自身 401 会触发无限 refetch,门禁永远卡在 spinner。`pnpm build`(tsc -b + vite build)干净通过,产物 ~114KB gzip。

## 修改的文件

### 新增 — `frontend/`(整个目录)
- **配置**:`package.json`(含 `pnpm.onlyBuiltDependencies: [esbuild]`)、`vite.config.ts`(`@` alias + dev proxy `/api`→`:8000`,可用 `CONDENSER_BACKEND` 覆盖)、`tsconfig*.json`(project references + `@/*` paths;node 配置加 `types:["node"]`)、`components.json`(shadcn new-york / neutral / cssVariables)、`index.html`(`<html class="dark">`)。
- **样式**:`src/index.css` — Tailwind v4 `@import` + `@plugin tailwindcss-animate` + shadcn neutral OKLCH token 全集 + `@theme inline`;自定义 `.msg-link`(蓝色 `text-sky-600 dark:text-sky-400`)。
- **基础设施**:`src/main.tsx`(QueryClientProvider + BrowserRouter)、`src/lib/queryClient.ts`(全局 401 处理,**跳过 tg-status 自身**)、`src/lib/api.ts`(typed fetch 客户端 + `ApiError` + `mediaUrl`)、`src/lib/types.ts`(镜像后端 JSON 契约)、`src/lib/format.ts`(date 解析/相对时间/紧凑数字/频道名)、`src/lib/linkify.tsx`(URL 自动链接)、`src/lib/utils.ts`(cn)。
- **hooks**:`useTgStatus`(鉴权门禁源)、`useSubscriptions` + `useChannelLabels`、`useScrollToRead`(IntersectionObserver 滚过即已读 + 防抖批量 + 乐观更新)、`useSaveToggle`(乐观收藏)。
- **组件**:`components/ui/{button,input,label}.tsx`(shadcn 手写)、`Spinner.tsx`、`Sidebar.tsx`、`components/timeline/{Timeline,MessageCard,MessageMedia}.tsx`。
- **页面**:`pages/{AppLogin,TgLogin,AppShell,TimelineView,RecordsView,SubscriptionsView}.tsx`、`src/App.tsx`(鉴权 gate + 路由)。

### 临时/调试(在 `tmp/`,gitignored)
- `tmp/seed_smoke.py` — 往 smoke DB 注入样例频道/消息/已读/收藏,供前端可视化预览。

## 注意事项

- **全局 401 + 自身 query 的 refetch 死循环**:用「query error 作为登录态来源」时,全局 onError 若无差别 invalidate 该 query,会让它的 401 反复触发 refetch → 永远 `isPending` → spinner 卡死。修法:`queryCache.onError` 里判断 `query.queryKey[0] !== TG_STATUS_KEY[0]` 才 invalidate;`tg-status` 自身的 401 直接由 App 读取渲染登录页。
- **鉴权架构**:cookie 是 HttpOnly,JS 读不到登录态。以「`GET /api/tg/status` 是否 401」作为 App 密码门禁的判据 —— 401→AppLogin,200→看 `status` 决定 TgLogin 或主界面。dev 下 vite proxy 让 cookie 同源生效。
- **时区假设**:后端 date 是 naive ISO 字符串(实为 UTC)。`lib/format.ts:parseDate` 检测无 tz 时补 `Z` 当 UTC 解析再转本地。**待确认 telememo 存的确实是 UTC**,否则显示会偏。
- **媒体渲染**:Telegram 把视频/gif/文件都归为 `media_type='document'`,无法区分;`MessageMedia` 用「先试缩略图 `?thumb=1`、`<img onError>` 回退文件 chip」兼容。`webpage` 类型不当作媒体(它是链接预览)。
- **时间线 channel 名**:`/api/timeline` 条目只有 `channel_id` 无标题,前端用 subscriptions 列表在客户端 join(`useChannelLabels`);`/api/records` 条目自带 `channel`。
- **shadcn + Tailwind v4(Vite)**:`components.json` 的 `tailwind.config` 留空、`cssVariables:true`;`index.css` 用 `@theme inline` 映射 OKLCH CSS 变量(参考 context7 拉的官方 Vite 安装规范)。组件用 React 19 函数式(非 forwardRef)+ `data-slot`。
- **formatter hook**:本仓库 PostToolUse 把 TS/JS 改成单引号 **+ 分号** 风格(与全局「不自动格式化」偏好冲突,但属 harness hook)。Edit 命中被重排区域前需先 Read。
- **环境坑**:pnpm 10 默认 block esbuild 的 build script,需 `pnpm.onlyBuiltDependencies:["esbuild"]` 否则 vite 运行报错;端口 8000 已被既有进程占用,smoke 用 8011 + `CONDENSER_BACKEND` 指向它。
- **未完成(M2)**:订阅完整管理(启停/删除/关键词)、日历组件、新内容轮询提示、媒体灯箱、TG 注销入口;Docker 多阶段前端构建尚未接(后端 `app.py` 已会挂载存在的 `frontend/dist`)。entities 富文本待后端补列。
