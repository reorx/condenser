---
created: 2026-06-18
tags:
  - frontend
  - timeline
  - ui-redesign
  - page-header
  - tanstack-query
  - tailwind
---

# Timeline 阅读视图重构：统一顶栏 + 日期分隔线 + 列边界

## 概要

用户给了一张新界面设计图，要求按图重构消息阅读视图，共 6 点变化：① 消息区左右加边界；② 顶栏统一为「Icon + 标题 + 未读数」左对齐 + 全图标按钮右对齐（去文字）；③ 取消会浮动的 sticky 日期条，日期改为只在跨天时出现的静态分隔标签；④ 按图调间距/宽度；⑤ 收藏图标永远显示；⑥ 转发消息改为圆角边框 + 柔和背景 + 左缩进的卡片。

走 feature-dev 流程：先用 code-explorer 摸清 `TimelineView`/`Timeline`/`MessageCard`/`AppShell` 现状，再向用户确认了几处关键决策（总消息数后端取不到 → 只显示未读数；Unread-only 改为右侧 Sparkles 图标按钮；列边界只在桌面端加；频道筛选下拉从 sticky 日期条搬到顶栏右侧图标区）。

最大的架构动作：频道筛选器原本和 sticky 日期条绑在一起、状态在 `Timeline` 内部，而新设计要把它放到顶栏（在 `TimelineView` 里）。为此把 timeline 无限查询抽成 `useTimeline` hook 由 `TimelineView` 持有、`useChannelFilter` 一并上提，`Timeline` 退化为展示型组件（接收 `query`/`items`/`visible`/`onClearFilter`/`emptyLabel`）。

3 个 code-reviewer 并行 review，修了两个高置信问题：无限滚动 IntersectionObserver 的依赖数组里混入了整个 `query` 对象（每次 render 新引用 → observer 反复重建，快速滚动可能漏触发 `fetchNextPage`）；以及 `TimelineView` 与 `Timeline` 各自重复 `flatMap` 派生 `items`。`tsc -b` + 14 个 vitest 全绿。提交为 `b472f14`，**只提交了本次重构的 8 个文件**，刻意没有捎带工作区里已存在的独立 Filters 特性改动。

## 修改的文件

### 新建

- `frontend/src/components/PageHeader.tsx` — 统一顶栏组件。导出 `PageHeader`（`icon + title + meta` 左对齐，`actions` 用 `ml-auto` 右对齐）和 `IconBadge`（把 lucide 图标包进 `size-9` 灰圆，对齐 `ChannelAvatar` 的尺寸占位）
- `frontend/src/hooks/useTimeline.ts` — 从 `Timeline` 抽出的 `useInfiniteQuery`，导出 `useTimeline(params)` + `TimelineQuery` 类型。抽出的唯一目的：让 `TimelineView` 能观察已加载消息，从而在顶栏构建频道筛选器

### 修改

- `frontend/src/pages/TimelineView.tsx` — 改用 `PageHeader`；自己持有 `useTimeline` 查询 + `useChannelFilter`；算未读数（单频道 `sub.unread`，All/Unread 求和 enabled 频道）；图标按钮顺序 日历→刷新→全部已读→[频道筛选(多频道才显示)]→Unread 切换(Sparkles)；图标逻辑 频道→`ChannelAvatar size-9`，Unread→`Sparkles`，All→`Inbox`（包 `IconBadge`）
- `frontend/src/components/timeline/Timeline.tsx` — 退化为展示型。删掉内部 `useInfiniteQuery`/`useChannelFilter`/`filterControl`；删掉 `sticky top-12` 浮动日期条，改为 group 间静态左对齐日期标签（`px-4 pt-6 pb-2 text-xs text-muted-foreground sm:px-5`，无水平线）；新增 props `query`/`items`/`visible`/`onClearFilter`/`emptyLabel`
- `frontend/src/components/timeline/MessageCard.tsx` — 收藏按钮去掉 `opacity-0 group-hover:...` 改为常显；转发盒子 `border p-3` → `rounded-lg border bg-muted/30 p-3 ml-8`（圆角+柔和背景+2rem 左缩进，"↪ Forwarded" 标签留在缩进外）；`<article>` 补 `px-4 sm:px-5` 内边距（之前裸贴列边）
- `frontend/src/components/CalendarPopover.tsx` — 触发按钮改纯图标（`size="icon"`），选中日期时 `variant="default"` 高亮填充，日期文字移到 `title` 提示
- `frontend/src/pages/RecordsView.tsx` — Saved 页头改用 `PageHeader`（`IconBadge` + Bookmark，无 meta，actions 为多频道时的 `ChannelFilter`）
- `frontend/src/pages/AppShell.tsx` — `max-w-2xl` 内容列加 `md:border-x md:border-border`（桌面端起，移动端不加）+ `min-h-dvh`（让边线满高）

## 注意事项

### 把 query 上提以解耦顶栏控件

- **触发原因**：某个 UI 控件（这里是频道筛选器）需要放在父级（顶栏），但它的状态和数据源都在子组件（`Timeline`）里。解法是把数据源（无限查询）抽成 hook 上提到父级，状态（`useChannelFilter`）也跟着上提，子组件退化为接收 props 的展示型组件。这是 React「状态上提」的标准套路，单 caller 时 blast radius 可控。
- **`TimelineQuery` 类型导出**：`export type TimelineQuery = ReturnType<typeof useTimeline>`，避免在每个 callsite 重复写 `UseInfiniteQueryResult<...>` 的长泛型，把整个 query 对象作为 prop 下传时类型也干净。
- **展示型 `Timeline` 的 props 设计**：传 `items`（未过滤的全部已加载单元，用于「真的没消息」vs「全被筛掉」的区分）+ `visible`（过滤后，用于渲染）两个数组；`showFilter` 为 false（单频道）时 `visible === items` 是同一引用。`emptyLabel` 让父级注入 Unread 视图专属的「全部已读」空状态文案，而不是把 `unreadOnly` 这个语义又塞回展示组件。

### useEffect 依赖数组不要混入 TanStack Query 的整个对象

- **坑**：`useInfiniteQuery` 每次 render 都返回**新的对象引用**。把整个 `query` 放进 `useEffect` 依赖数组（哪怕同时也列了 `query.hasNextPage` 等具体字段），会导致 effect 每次 render 都重跑——这里就是 IntersectionObserver 被反复 disconnect/observe，快速滚动时新 observer 可能还没就绪就错过了 sentinel 进入视口，漏触发 `fetchNextPage`。
- **正解**：只列真正用到的具体字段 `[query.hasNextPage, query.isFetchingNextPage, query.fetchNextPage]`，不要列 `query` 本身。`fetchNextPage` 是稳定引用，可安全入数组。

### 顶栏图标按钮的实现选择

- **用原生 `title` 而非 shadcn `Tooltip`**：日历和频道筛选的触发器本身已经是 `PopoverTrigger asChild`，再套一层 `TooltipTrigger asChild` 会让 Radix 的两个 `asChild` 叠在同一元素上，行为脆弱。直接用原生 `title` 属性做 hover 提示（代码库里 Refresh 按钮原本就这么做），最省事且零依赖。
- **图标按钮统一 `size="icon" className="size-8"`**；激活态（Unread 开启、日期已选）用 `variant="default"` 填充，未激活用 `variant="ghost" + text-muted-foreground`。
- **`ChannelFilter` 混入图标按钮行**：给它传 `className="h-8 px-2"` 覆盖其内置的 `h-6 px-1.5`（靠 tailwind-merge 后者覆盖前者）。能 work 但略脆，是已知的小技术债（见遗留问题）。

### 间距 / 边界细节

- **列边界只在桌面端**：移动端 `max-w-2xl` 列被窄屏撑满、左右无留白，加边线会贴屏幕边缘很丑，所以用 `md:border-x`。配 `min-h-dvh` 让短内容时边线也能满屏高。
- **卡片补水平内边距**：`MessageCard` 的 `<article>` 之前完全没有 `px`，文字裸贴列边（设计图里消息明显内缩）。统一加 `px-4 sm:px-5`，与顶栏、日期标签的 inset 一致；`border-b` 仍满列宽（padding 在边框内侧）。
- **日期分隔线 = 纯文字标签**：按用户选择，只是左对齐的小号灰字（Today / Yesterday / EEE, MMM d，复用 `lib/format.ts:dayLabel`），靠 `pt-6 pb-2` 的上下间距分隔，不画水平线。

## 遗留问题

- **未做浏览器视觉验证**：完成了代码 + 类型检查 + 14 个 vitest，但 dev server 后端返回 401（app-password 门），无法用已登录会话截图。建议下次启动 dev 时人眼检查：移动端窄屏顶栏 5 个图标会不会挤（标题会 truncate，预计 OK）、转发卡 2rem 缩进观感、日期标签上下间距、列边线在长短内容下的表现。
- **`ChannelFilter` 尺寸覆盖略脆**：它内部硬编码 `h-6 gap-1 px-1.5 text-xs`，两个 caller 都传 `h-8 px-2` 覆盖，依赖 tailwind-merge 的「后者胜」。reviewer 建议把高度做成 `size` prop 或从基类去掉 `h-6`，本次未改（避免 scope 蔓延）。
- **顶栏只显示未读数、不显示总消息数**：后端 `/api/subscriptions` 的 `Subscription` 只有 `unread` 没有 `total`，timeline 接口也没暴露总数。设计图里的「· 5,310 total」本次未实现。若要补，需要后端加一个 counts 接口或在 Subscription 上加 `total_messages` 字段。
- **移动端顶栏单行 5 图标**：旧版按钮是独立换行的一排，新版全部内联在右侧。窄屏（~360px）下靠标题 truncate 让位，单用户 reader 场景可接受，但若将来要适配更多按钮需重新考虑折叠策略。
- **工作区有独立的 Filters 特性未提交**：本次只提交了重构相关的 8 个文件（`b472f14`）。`condenser/db.py`、`routers/subscriptions.py`、`types.py`、`FiltersView.tsx`、`useAllFilters.ts`、`components/filters/`、`SubscriptionsView.tsx`、`Sidebar.tsx`、`tests/test_backend.py` 等是另一条独立特性线，留给用户单独提交（后续已由 `83358ed`/`1759be2` 提交）。

## 相关文档

- [媒体 Skeleton + 持久化宽高](2026-06-18-media-skeleton-and-dimensions.md) — 同日上一个 session，本次重构沿用了其 `MessageMedia` 媒体渲染（卡片补 `px` 后媒体仍满卡片宽度）
- [内容更新机制](../docs/content-update-mechanism.md) — 参考 `useNewContent` 新内容轮询如何依赖 page-1 的 `head_cursor`（重构后这部分逻辑保留在展示型 `Timeline` 中）
