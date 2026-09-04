---
created: 2026-09-02
tags:
  - frontend
  - backend
  - hn
  - summary
  - vibe-reader
  - feature-plan
---

# Vibe Reader 联动模式 + HN 条目服务端摘要

两件事，一个动机：**在 condenser 时间线上决定要不要点开一条，点开之后立刻有深读材料。**

- **HN 服务端摘要**（本仓库独立完成）：HN 卡片像 RSS 卡片一样带 2-3 句中文摘要，
  外加一句讨论在说什么。用途是**点开之前的判断**。
- **Vibe Reader 联动**（与 `../vibe-reader-hn` 配对，对方 plan：
  `vibe-reader-hn/kb/plans/2026-09-02-condenser-link-mode-multi-session.md`）：
  扩展 sidepanel 打开时，从 condenser 点开的链接由扩展自动提取正文、生成摘要 +
  HN discussion insight，并随 tab 切换自动展示。用途是**点开之后的深读**。

本 plan 由一轮讨论敲定，决策记录见 §0。condenser 侧改动全部在前端 + 后端摘要管线，
**联动本身不需要任何后端改动**。

## 0. 已定决策（用户拍板，不再重议）

1. **只处理带 intent 的 tab。** 扩展不做「opener 是 condenser 就自动处理」的兜底。
   从 condenser 开出去的 tab，只有 condenser 明确发过 `condenser:open` 的才被扩展
   自动处理和计费。
2. **联动开关的唯一真源在扩展侧。** condenser 只镜像状态、可请求切换；本地只存
   「不再提示」一个标记。
3. **发现机制用 content script 桥 + `window.postMessage`，不用 `externally_connectable`。**
   后者要求 condenser 知道扩展 id（开发态还会变），耦合到部署配置里去了。
4. **桥的存在即「扩展已打开」。** 桥由 sidepanel 注入，sidepanel 关闭时 port 断开，
   桥立刻通知页面。没有心跳。
5. **不做 hover 预取。** 没点开的条目不付费。
6. **HN 摘要在服务端做**，与 RSS 摘要同一套 fence（开关、独立 key、每轮 batch 上限、
   status 计数）。它和联动不冲突：一个管点开前，一个管点开后。
7. **HN 摘要的原料 = 文章正文 + HN 讨论。** 这是与 RSS plan §0.1「不抓全文」的
   **有意分叉**：RSS 条目有 feed 自带的正文，HN 条目什么都没有，而 `hn.py` 的
   preview 预取**已经在抓这些 URL 的 HTML**（`preview._fetch_capped`），反爬 /
   付费墙失败面早已存在。抓不到正文时降级为「讨论 + preview description」，
   不因此计入重试。

## 1. 联动协议（两个仓库共用一份契约）

### 1.1 传输

- 页面 ↔ 桥：`window.postMessage(msg, location.origin)`。页面只认
  `event.source === window && event.data?.ns === 'vibe-reader'`；桥只认
  `ns === 'condenser'`。
- 桥 ↔ sidepanel：`runtime.connect` port（扩展内部，本仓库不关心）。
- 版本字段 `v: 1`。两边各自用测试钉住消息形状；任何一方改契约先 bump `v`。

### 1.2 页面如何被识别

`frontend/index.html` 加：

```html
<meta name="application-name" content="condenser">
```

扩展 sidepanel 看到激活 tab 的页面带这个 meta，就注入桥。

### 1.3 消息集

| 方向 | `type` | 载荷 | 说明 |
|---|---|---|---|
| 桥 → 页 | `vibe-reader:hello` | `{v, linked}` | 桥注入完成、或收到页面的 hello 时发 |
| 页 → 桥 | `condenser:hello` | `{v}` | 页面 mount 时发。解决「桥先于 React 挂载」的顺序问题：两边各自 ready 时都打一次招呼 |
| 页 → 桥 | `condenser:set-link` | `{linked: boolean}` | 请求切换 |
| 桥 → 页 | `vibe-reader:link` | `{linked}` | 开关最终状态（扩展是真源） |
| 桥 → 页 | `vibe-reader:bye` | `{}` | port 断开（sidepanel 关闭 / 扩展重载） |
| 页 → 桥 | `condenser:open` | `{url, title?, hn?}` | 用户点了一个外链，见 §1.4 |
| 桥 → 页 | `vibe-reader:status` | `{url, state, modes?}` | Phase D，卡片角标用；`state ∈ queued / extracting / generating / done / error` |

`hn` 字段：`{id, title, score, comments_count, submitted_at}`。有它扩展就跳过
Algolia 搜索，直接锁定 discussion（vibe-reader 记录过 Algolia 滞后 18 小时的问题，
这是联动带来的实打实收益）。

### 1.4 什么时候发 `condenser:open`

一个**事件委托监听器**挂在 `AppShell`，捕获 `click` 与 `auxclick`（覆盖 Cmd 点击 /
中键），条件：

- 目标是 `<a target="_blank">`，`href` 为 http(s)；
- 联动已开启（`linked === true`）；
- 域名不在「无正文」列表：`x.com` / `twitter.com` / `t.me` / `news.ycombinator.com/user`
  等（列表放 `lib/vibeReader.ts`，测试钉住）。**HN item 页（`/item?id=`）要发**，
  扩展那边走 `hnThread`。

不 `preventDefault`，浏览器照常开 tab。`title` 取 `data-vr-title` 否则 `textContent`；
`hn` 取 `data-vr-hn-id` 等 data 属性（见 §2.3）。

## 2. Phase A —— 联动客户端（前端）

> **状态：✅ 前端 + 单测已完成 2026-09-04**（`frontend/src/lib/vibeReader.ts` + `hooks/useVibeReader.ts`
> + `components/VibeReaderPrompt.tsx` / `VibeReaderDot.tsx`、`SettingsDialog` 行、`AppShell` 装配、
> `index.html` meta、§2.3 的 data 属性；`vibeReader.test.ts` 29 条 + `VibeReaderPrompt.test.tsx` 6 条
> + Settings / HnCard 各加用例）。**未联调**：扩展侧 Phase 1 未就绪，§6.2 的走查与截图归档待其完成。
> 与本节的几处出入 / 补充：(1) 委托挂在 `document` 而不是 `AppShell` 的根元素，**bubble 阶段**并跳过
> `defaultPrevented` 的点击（已被取消的点击不会开 tab）；`auxclick` 只认中键（右键也触发 auxclick）。
> (2) `shouldAnnounce` 额外排除**同源链接**（media / avatar / preview 代理不是文章）。(3) 协议版本
> 不匹配的 hello：记下 `version`、`available` 保持 false，Settings 行显示「协议版本不匹配 (vN)」，
> 开关禁用。(4) `bye` 同时把 `linked` 置回 false——联动是这条连接的属性，下一次 hello 会重述开关。
> (5) 提示每次页面加载只弹一次；扩展侧已开启联动时不弹。(6) `vibe-reader:status` 已进类型联合，
> 不处理（Phase D）。

### 2.1 测试先行（BDD）

`frontend/src/lib/vibeReader.test.ts`：
- 收到 `vibe-reader:hello` → `available=true`、`linked` 镜像载荷；`bye` → `available=false`。
- mount 时发出 `condenser:hello`。
- `setLink(true)` 发 `condenser:set-link`，状态**不**乐观翻转，等 `vibe-reader:link`。
- 委托点击：`<a target=_blank href=https://example.com data-vr-hn-id=1 data-vr-title=T>`
  → 发出 `condenser:open` 且 `hn.id === 1`；`auxclick` 同样；`x.com` 不发；未 linked 不发；
  非 `_blank` 不发。
- 来源校验：`event.source !== window` 或 `ns` 不对的消息被忽略。

`frontend/src/components/VibeReaderPrompt.test.tsx`：首次 hello 弹提示；点「开启」发
set-link；点「不再提示」写 localStorage 后不再弹。

### 2.2 实现

- `lib/vibeReader.ts`：一个模块级 store（`useSyncExternalStore`），字段
  `available` / `linked` / `version`；`setLink()`；`announceOpen(intent)`；
  `installLinkDelegate(root)` 返回卸载函数。消息类型定义在同文件顶部，作为契约副本。
- `hooks/useVibeReader.ts`：订阅 store。
- `pages/AppShell.tsx`：mount 时 `installLinkDelegate(document)` + 发 `condenser:hello`。
- `components/VibeReaderPrompt.tsx`：sonner toast，「检测到 Vibe Reader，开启联动？」
  两个 action：开启 / 不再提示（`localStorage['condenser-vibe-reader-prompt'] = 'dismissed'`，
  沿用 `useCollapsedSources` 的读写模式）。
- `SettingsDialog`：新增一行「Vibe Reader 联动」：状态文字（未检测到 / 已连接·关闭 /
  已连接·开启）+ Switch（`available` 为 false 时禁用）。
- `Sidebar` 底部一个 6px 指示点：绿 = linked，灰 = available 未开，隐藏 = 不可用。
  `title` 说明状态。

### 2.3 卡片的 data 属性

只加属性，不改事件：
- `HnCard`：标题链接与 comments 链接加 `data-vr-hn-id={hn.id}`、`data-vr-title={hn.title}`、
  `data-vr-hn-score` / `data-vr-hn-comments` / `data-vr-hn-submitted`。
- `ItemDetailInfo` 里 HN 的两个链接同样。
- RSS / TG / 预览卡里的链接不用改，委托层自然覆盖（无 `hn`，扩展走 Algolia）。

`iOS` 不参与联动（没有扩展），不改。

## 3. Phase B —— HN 服务端摘要（后端）

> **状态：✅ 已完成 2026-09-02**（`condenser/hn_summary.py`、schema v19、
> `tests/test_hn_summary.py` 30 条；真实冒烟 `tmp/2026-09-02-hn-summary/`）。
> 实现与本节的两处出入：(1) `summary.py` 抽出的共用传输函数叫 `complete(system, user)`；
> (2) 多了一个 `skip:empty` 决定——无正文、无 preview description、无评论时不调模型且
> 不再重进 batch（否则年龄门槛永不关闭）。status 块的 `given_up` 按 `summary.counts()`
> 的既有形状叫 `failed`。

### 3.1 数据（schema v19）

`hn_stories` 加三列，**照抄** `rss_entries` 的三件套，语义一字不改：

```
summary TEXT NULL
summary_model TEXT NULL      -- provenance，不是 re-do 契约（summary.model_tag 的说明）
summary_attempts INTEGER DEFAULT 0
```

`kb/docs/database.md` 加 v19 changelog；`init_db` 按 shape-based `ADD COLUMN` 惯例，
放在 `create_tables` 之前（database.md 的排序陷阱）。

### 3.2 原料

一条 story 的输入是两段文本，缺哪段都能跑：

1. **文章正文**：`preview._fetch_capped`（同 UA、同超时，cap 用新设置
   `condenser_hn_summary_max_bytes`，默认 1 MiB）→ `readability-lxml` 抽主体 →
   `text.plain_text` → 截到 `condenser_hn_summary_max_article_chars`（默认 6000）。
   自提帖（`url IS NULL`）用 `text` 列。抓取 / 抽取失败 → `article = None`，
   用 `preview.description` 顶上，**不计 attempts**（失败不是模型的错，见 §0.7）。
   ⚠️ `text._drop_noise` 是手写扫描不是正则，保持先 readability 再 plain_text 的顺序，
   不要把整页 HTML 直接喂给 `plain_text` 之外的任何正则。
2. **讨论**：Algolia `GET https://hn.algolia.com/api/v1/items/{id}`（一次请求拿整棵树，
   免鉴权）。按返回顺序取顶层评论，每条带最多两层回复，`plain_text` 后拼接，
   截到 `condenser_hn_summary_max_discussion_chars`（默认 6000）。0 评论 → `None`。

依赖：`readability-lxml`（`uv add`）。`trafilatura` 质量更高但拖 lxml 之外一整串
依赖，v1 不用；抽取质量不够再换，接口就是 `html -> str | None` 一个函数。

### 3.3 触发时机

挂在 `HNManager.poll_once` 的尾巴、`_qualify()` **之后**（`_qualify` 「必须是最后一步」的
理由是分数要新鲜 + 带着 preview 入场；摘要不影响 admission，排在它后面不破坏那条理由，
但要把 `_qualify` 的 docstring 改成「admission 的最后一步」）。

候选 SQL（`db.hn_stories_needing_summary`，形状同 `_RSS_SUMMARY_WHERE`）：

```
qualified_at IS NOT NULL
AND summary_model IS NULL AND summary_attempts < ?
AND 未读（LEFT JOIN read_items ... IS NULL）
AND is_dead = 0 AND type = 'story'
AND (comments_count >= ? OR first_seen_at <= ?)   -- 讨论成形了再总结
ORDER BY first_seen_at DESC LIMIT ?
```

门槛默认：`condenser_hn_summary_min_comments = 10` **或** `condenser_hn_summary_min_age_hours = 3`。
一条 story **只总结一次**（v1 不做「评论翻倍后刷新」，需要时再加 `summary_comments_count` 列）。

### 3.4 模块与 fence

新模块 `condenser/hn_summary.py`，不往 `summary.py` 里塞分支：两者共用
`summary.summarize_entry` 的传输层（`_post`、`SummaryError` / `ProviderUnavailable`、
`clean_answer`、thinking 关闭），各自有 prompt、候选 SQL 和 round。共用的传输函数
如需改签名，先在 `summary.py` 抽成「给定 system + user prompt 发一次」的函数。

Fence 与 RSS 一致：
- 开关 `CONDENSER_HN_SUMMARY_ENABLED`（默认 true）；**key 仍是 `CONDENSER_SUMMARY_API_KEY`**，
  没 key 整个不动。共用 key 是有意的：同一用途、同一 provider，两把 key 只会多一处配置。
- `CONDENSER_HN_SUMMARY_BATCH`（默认 10）。每条 story 是 1 次 Algolia + 1 次文章抓取 +
  1 次 LLM，串行，provider 不应答即停轮（RSS 的规则）。
- `/api/hn/status` 加 `summary` 块：`enabled / model / pending / done / given_up`，
  `hn_summary.counts()`，形状同 `summary.counts()`。

Prompt（`hn_summary.system_prompt`）：中文；先 2-3 句说文章讲了什么、结论是什么；
再 1-2 句说 HN 讨论的主流反应或争议点。只有讨论没正文时，第一段改为「根据标题与讨论
推断文章内容」并如实说明。无 Markdown、无前缀（`_PREFIX_RE` 沿用）。`PROMPT_VERSION`
独立于 RSS 的。

失败计费：`SummaryError`（模型拒绝这条输入）→ `bump_hn_summary_attempts`，三次后放弃；
`ProviderUnavailable` → 停轮不计；抓取 / Algolia 失败 → 降级或跳过本轮，不计。

### 3.5 下发与索引

- `items.hn_payload` 加 `summary`（`null` 表示没有）。`records.py` 快照自然带上。
- `search`：HN 文档加 summary 字段；round 末尾 `search.index_hn_stories(ids)`（RSS 的
  `index_rss_entries` 对应物，没有就加）。不 bump `TOKENIZER_VERSION`。

### 3.6 测试先行

`tests/test_hn_summary.py`（`fetch_json` / `fetch_article` / `summarize` 全部注入，零网络）：
- 候选：未 qualified 不进；已读不进；评论 < 10 且不满 3 小时不进；满一个条件进。
- 降级：文章抓取失败 → 仍生成，prompt 里带 preview description，attempts 不变。
- 计费：`SummaryError` 三次后放弃；`ProviderUnavailable` 第一条就停轮且后面的不碰。
- 自提帖用 `text` 列，不发抓取。
- 索引：生成后 `search` 能搜到摘要里的词。
- status 计数。
- ⚠️ 固定时钟的 fixture 记得关 cleanup 规则（CLAUDE.md 的陷阱）。

## 4. Phase C —— HN 摘要的展示

> **状态：✅ 已完成 2026-09-02**（Web `HnCard` / `ItemDetailInfo`、preview 画廊；iOS Kit
> `HnStory.summary` + `displaySummary`、`HnCard` / `HnDetailSheet` / 分享图；验收图
> `tmp/2026-09-02-hn-summary-display/`）。与本节的一处出入：`ItemDetailBody` 不加摘要块，
> 抽屉里只有 Info 行——HN 的 body 只有自提帖正文，再画一遍就是三处同文。iOS 随下一个 build。

- `HnCard`：标题下、meta 行上，`rss.summary` 的同款段落（`text-foreground/90`，机器
  转述的视觉标识与 RssCard 保持一致）。有 summary 时 `LinkPreviewCard` 的 description
  省略（信息重复）。
- `ItemDetailInfo`：HN 详情里同样显示。
- iOS Kit：`HnStory` 加 `let summary: String?`（Codable 缺字段解为 nil，旧 build 不受影响），
  `HnCard` 在标题下渲染；随下一个 build 走。

## 5. Phase D —— 状态回传（可选，等 vibe-reader Phase 3）

- `lib/vibeReader.ts` 处理 `vibe-reader:status`，按 URL 存 `Map<url, state>`。
- 卡片时间行加一个小角标（`ForwardedBadge` 的位置和尺寸）：转圈 = 生成中，
  闪电 = 就绪。点击不做事，只是提示。
- 不落库、不进 React Query 缓存，刷新页面即丢。

## 6. 顺序与验收

1. Phase B 可以独立先做（不依赖扩展），上线后立刻有用。
2. Phase A 与 vibe-reader Phase 1 一起联调：本机 `pnpm dev` + 扩展 dev 模式，
   走查：打开 condenser → 提示 → 开启 → 点一条 HN → 新 tab 里 sidepanel 自动开跑。
   截图归档 `tmp/2026-09-xx-vibe-reader-link/`。
3. Phase C 随 B 发布；iOS 部分随下一个 build。
4. Phase D 等对方 Phase 3。

**发布注意**：push master 即部署。Phase B 上线前生产 `.env` 无需新 key（复用
`CONDENSER_SUMMARY_API_KEY`），但要确认 `readability-lxml` 进了镜像。
