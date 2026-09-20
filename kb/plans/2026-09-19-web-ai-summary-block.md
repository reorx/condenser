# Web 的 AI 摘要块对齐 iOS（`AiSummaryBlock`）

状态：**已实现**（2026-09-20，见文末 §实现记录）。未部署。

## Context

iOS 上 AI 摘要是一个成型的引用块（`ios/Condenser/UI/AiSummaryBlock.swift`，HN / RSS 的卡片与
详情共用）：浅靛蓝底（indigo 7%）+ 左侧 3pt 深一档同色竖条（55%）+ 8pt 圆角，
**「✨ AI 摘要」标注在块内顶部**（靛蓝 semibold），正文在标注下——「先撞上『这是机器转述』再读内容，
且标注与内容同块，归属不会看岔」。

Web 落后于此：

- `HnCard.tsx` / `RssCard.tsx`：裸段落 + **底部**一个灰色 `bg-muted` chip，无块、无靛蓝、无图标。
  （位置本身已对：标题下、meta 行上。）
- 详情抽屉：RSS 有靛蓝块（`ItemDetailBody.tsx`）但标注仍是底部灰 chip；HN 摘要只是
  `ItemDetailInfo.tsx` 的一行 label/value，而 iOS `HnDetailSheet` 是「meta → 摘要块 → 正文」。
  RSS 在抽屉里还**重复出现两次**（`ItemDetailInfo` 的行 + 正文区的块）。

用户决定：**所有摘要界面**统一换成共享组件；web 卡片**不截断**（iOS 的 8 行 + more 不搬，
web 列宽足够，摘要是这张卡存在的理由）。

## 方案

### 1. 新组件 `frontend/src/components/timeline/AiSummaryBlock.tsx`

iOS 同名组件的 web 版，逐项对照：

| iOS | Web (Tailwind) |
|---|---|
| `tint.opacity(0.07)` 底 | `bg-indigo-500/[0.07] dark:bg-indigo-400/10` |
| 左侧 3pt、55% 竖条，被圆角裁切 | 见 §实现记录 1（计划原写 `border-l-[3px]`，形状不对，改为 `::before`） |
| `cornerRadius: 8` | `rounded-lg` |
| padding v8 / 竖条后 10 / 右 10 | `py-2 pl-[13px] pr-2.5` |
| `Label("AI 摘要", "sparkles")` caption semibold 靛蓝，**在上** | `<Sparkles className="size-3.5" aria-hidden />` + 「AI 摘要」，`text-xs font-semibold text-indigo-600 dark:text-indigo-400` |
| spacing 6 → 正文 | `<p className="mt-1.5 text-sm leading-relaxed break-words text-foreground/90">` |

接口：`{ summary: string | null | undefined; className?: string }`。trim 后为空返回 `null`——
对应 Kit 的 `displaySummary`；`className` 只给外边距。
靛蓝的依据与 iOS 相同：琥珀 = RSS / 收藏、橙 = HN、天蓝 = 未读，靛蓝在 web 上已是「我写的 / 机器写的附注」
色（`AnnotationBadge`、评论按钮）。

### 2. 替换四处

- **`HnCard.tsx`**：摘要段换成 `<AiSummaryBlock summary={hn.summary} className="mt-1.5" />`；
  位置不动（标题 → self-text → 摘要块 → meta → 预览卡）。「有摘要时预览卡丢 description」逻辑不动。
- **`RssCard.tsx`**：summary 分支同样替换；「有摘要不显示摘录」「查看全文」逻辑不动（见文末备注）。
- **`ItemDetailBody.tsx`**：
  - `RssDetailBody` 的内联靛蓝块换成 `<AiSummaryBlock summary={entry.summary} className="mb-3" />`。
  - HN 分支：摘要块放在可标注正文**之上、`AnnotatedText` 之外**（机器的话不可标注，iOS 规则）。
    早退条件让路：外链 story 无 self-text 但有摘要时仍渲染这一节（只有块）。
- **`ItemDetailInfo.tsx`**：删掉 RSS 与 HN 两行 `AI 摘要` DetailRow——正文区的块已承担，
  留着就是同一段话在抽屉里出现两次（iOS 详情 sheet 也没有这一行）。

### 3. 测试（BDD，先写后实现）

- 新 `AiSummaryBlock.test.tsx`：标注在 DOM 顺序上**先于**摘要文本；纯空白 / null 渲染为空。
- `HnCard.test.tsx` / `RssCard.test.tsx`：补「标注先于摘要文本」。
- `ItemDetailBody.test.tsx`：RSS 用例补标注顺序；新增 HN——外链 story 有摘要时渲染块；
  有 self-text 时块在正文之前且在 `AnnotatedText` 之外。
- `ItemDetailPane.test.tsx`：语义不变（由正文区的块满足；`getByText` 同时保证抽屉里只出现一次）。

### 4. 预览 harness

`src/preview/mocks.ts` 补 `makeRssItem` + 两条 RSS mock（一条带 `summary` 与内联 `content`，
一条走摘录回退），`TimelineDayGroup` 本就按源分发，所以 `PreviewApp` 不用动。

### 5. 文档

`frontend/AGENTS.md` 组件清单（新增行 + 四行更新）、`kb/docs/status-and-gaps.md`、本文件。

## 备注（不在本次范围，供判断）

iOS `RssCard` 在有摘要时**还会先画 3 行正文开头**再接摘要块（2026-08-23 定型：「只看转述没法快速判断文章本身」），
web `RssCard` 仍是「有摘要就不给摘录」。这是内容取舍的差异而非摘要块样式的差异，本次不动；
想对齐的话是 RssCard 里十来行的后续改动。

## 实现记录（2026-09-20）

1. **竖条不能用 `border-l`**。计划表里写的 `border-l-[3px]` + `rounded-lg`，放大截图后发现边框会
   沿圆角弯曲并在两端收尖——一个括号，不是一根条。iOS 是直的矩形 overlay 被 `clipShape` 裁切。
   改为块 `relative overflow-hidden` + `before:` 3px 绝对定位竖条，左内边距相应变成 13px（3 + 10，
   与 iOS `.padding(.leading, 13)` 同数）。对比图：`tmp/2026-09-19-web-ai-summary-block/02-*`。
2. **`displaySummary` 一并导出**。计划说「调用方不再各写一遍判断」，但有两处调用方是在摘要上**分支**
   而不只是渲染：RssCard 的摘录回退 / 「查看全文」、HnCard 的预览 description 丢弃。它们若继续用
   `rss.summary ?` 真值判断，纯空白摘要会得到「无块、也无摘录」。三处都走 `displaySummary`，
   并各有一条空白摘要的用例钉住。`ItemDetailBody` 的 HN 早退同理。
3. **真实数据走查用的是库副本**。本地 dev 库 0 条摘要（`.env` 没有 `CONDENSER_SUMMARY_API_KEY`），
   于是 `tmp/seed_walkthrough_db.py` 把库 backup 到 scratchpad、删掉副本里的 `tg_session`
   （第二个进程不能拿同一 auth key 连 Telegram）、给 6 条 HN + 3 条 RSS 写上标明「走查用假摘要」的文本，
   后端以 `CONDENSER_DB_PATH=<副本>` 起在 :8793，Vite 以 `CONDENSER_BACKEND` 指过去。dev 库未被改动，
   副本走查后已删。
4. 顺带：`pnpm dev` 包了 portless，无 TTY 时起不来（要 sudo 起代理）；harness / 走查直接
   `pnpm exec vite --host 127.0.0.1 --port 5792` 即可。

测试：web 319（+10），`pnpm build`（`tsc -b`）通过。截图 11 张在 `tmp/2026-09-19-web-ai-summary-block/`。
