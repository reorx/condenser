---
created: 2026-09-16
tags:
  - x
  - article
  - probe
  - backend
  - frontend
  - ios
  - plan
---

# X Article 全文：probe 补抓 + 服务端渲染 HTML + 两端详情加载

> **状态：已实现（2026-09-16）**，未部署。上游 xbird 1.3.0 已就绪并已推送（`8113c60`）。
> 上游接口变更见 `../../../xbird/kb/sessions/2026-09-16-x-article-full-content.md`。
>
> 实现与本文的偏差（均为实现期发现，不改决策）：
> - §4.1 用 **markdown-it-py** 而非 mistune——它已是直接依赖（`purifier.py`），`html=False` 等价于
>   `escape=True`，零新依赖。孤立图片段落用 core rule 隐藏 `<p>`，避免 `<p><figure>` 非法嵌套。
> - §0 样本的「代码块 ×4」是 4 个 ``` 围栏 = 2 个代码块。
> - §4.3 `_COLS_FULL` 不是 `rows_by_id` 的默认：改成 `rows_by_id(ids, with_content=False)` /
>   `get_row(id, with_content=False)`，search 渲染列表时不读正文，只有快照与详情端点传 True。
> - §4.7 `pending` 的 `limit` 可省略（= 服务端 batch），probe 不传——批量由服务端决定。
> - §5.1 web 详情**即使列表说 `has_content: false` 也会请求一次**（正文在列表加载后才到的情况），
>   但只有 `has_content: true` 才显示「正在加载全文…」/「正文加载失败」；无正文的回答不永久缓存
>   （`staleTime` 为函数）。`ARTICLE_PROSE` 补了标题 / 列表 / 引用 / figure 样式（RSS 同样受益）。

## 0. 起因

X 长文（Article）推文在 condenser 里只有**标题 + ~200 字符摘要**。`XCard` 的文章卡
（`XCard.tsx:160-169` / iOS `XCard.swift:171-191`）渲染的就是这两个字段的全部，点开详情
也没有更多——`xBodyText` 在 `text === article.title` 时返回 null，所以详情面板的正文区
对一篇长文**什么都不显示**。

原因不在 condenser：timeline 系列 GraphQL 查询（home / home-latest / user-tweets）不带
`fieldToggles`，X 返回的 article 节点里根本没有正文。只有 TweetDetail 家族
（`client.get_tweet`）带 `withArticleRichContentState` + `withArticlePlainText`。

xbird 1.3.0 补上了这一层：`TweetArticle` 新增 `content`（Markdown 全文）/ `plainText` /
`coverMedia` / `media` / `publishedAt` / `modifiedAt`，且只在 TweetDetail 路径填充
（`article_details=True` 开关，timeline 路径零结构变化）。

**实测样本**（`https://x.com/xiaoerzhan/status/2099707280845332534`，xbird 1.3.0 实抓）：

| 字段 | 值 |
|---|---|
| `article.content` | 3265 字符 Markdown：`## 小标题` ×7、`![图注](url)` ×3、``` 代码块 ×4 |
| `article.plainText` | 2558 字符，服务端预渲染的纯文本 |
| `article.previewText` | 88 字符（今天唯一能看到的东西） |
| `article.coverMedia` | 1600×900 |
| `article.media[]` | 3 张，各带 `width`/`height`/`caption` |
| `text`（detail 路径） | 3116 字符 = 标题 + `\n\n` + 全文 |
| `text`（timeline 路径） | 25 字符 = 仅标题 |

## 1. 决策（四项，2026-09-16 与用户确认）

1. **正文格式：服务端把 Markdown 渲染成 HTML 再下发。** DB 存 Markdown 原文，只在 detail
   端点渲染。两端都已有成熟的 HTML 渲染路径（web = `sanitizeHtml` + `ARTICLE_PROSE`，
   iOS = `rssBlocks(fromHTML:)` → 文本块/图片块），**零新客户端依赖、零新渲染管线**。
   服务端渲染还能做两件只有服务端做得了的事：按 URL 把 `media[]` 的 `width`/`height`
   注进 `<img>`（iOS 图片占位不跳动），把 `coverMedia` 拼在正文最前。
2. **抓取时机：轮次末尾问服务端要工作单。** 所有 feed ingest 完成之后，probe 调一次
   `GET /api/sources/x/articles/pending`，服务端回「有 article 标题但没正文」的 tweet id。
   一套机制同时覆盖三件事：本轮新文章（零延迟——问的时候它已入库）、历史积压回填、失败重试。
   *否决的方案*：在 `_run_feed` 里首见即抓。代码更少，但 SeenCache 24 小时内不重推，
   存量文章永远进不了 `fresh`，抓失败也永远不会重试。
3. **回填范围：只回填最近 7 天。** 窗口按 `x_feed_items.first_seen_at` 算，不是
   `created_at`——For You 会翻出十天前的老推，「最近 7 天进到我阅读器里的文章」才是要的集合。
4. **全文进搜索，不进判定。** `search.x_document` 拼上 `plainText`（FTS5 本地、不花钱，
   长文正是事后最想搜到的东西）。`verdict.judge_text` 一个字不改：`embedding.embed_texts`
   没有任何截断，把三千字原样送进 DashScope embedding 和 `attributes.py` 的 LLM 是按量计费的，
   而「这篇值不值得读」用标题 + 摘要判断本来就够。

### 1.1 三个附带决策

- **封面图只进详情，不进卡片。** 时间线保持密度。卡片带封面是另一件事。
- **iOS 把 `RssBlocks.swift` 重命名为 `ArticleBlocks.swift`**（`RssBlock`/`RssImage`/
  `rssBlocks(fromHTML:)` → `ArticleBlock`/`ArticleImage`/`articleBlocks(fromHTML:)`）。
  纯机械改名：让 `XDetailSheet` 里出现 `RssBlock` 太难读，而这条管线本来就是源无关的。
- **`article_attempts` 在「发放」时就 +1**，不等 probe 回报失败。probe 中途崩了也不会让
  一条死推文被无限发放。代价：X 连挂三轮（45 分钟）那篇文章会被永久跳过，7 天窗口内不再捡起。

## 2. 数据流

```
probe run_round():
  probe_config() → feeds
  for feed: fetch → ingest                    ← 新文章此刻已入库
  ──────────────── 轮次末尾 ────────────────
  GET  /api/sources/x/articles/pending?limit=5
       → {"tweet_ids": ["2099707280845332534", ...]}
       （服务端在发放时 article_attempts += 1）
  for id in ids:                               ← 条间 sleep 1.0s
      client.get_tweet(id) → to_json(tweet)["article"]
  POST /api/sources/x/articles
       {"articles": [{"tweet_id": "...", "article": {...}}]}
       → 存 x_tweets.article_detail + search.index_x_tweets([id])
```

**只有 `article` 这一块上行，不是整条 detail 推文。** 这条是硬约束：`upsert_x_tweet` 的
update set 是从 `fields` 全量生成的整行覆盖，而 detail 路径的 `tweet.text` 是「标题 +
`\n\n` + 全文」(3116 字符)，timeline 路径只有 25 字符的标题。整条推上去会把 `text` 换成全文，
前端 `xBodyText` 的 `text === title` 判等失效，**卡片当场变成三千字**。

## 3. Schema v21

两列，照 v13 `x_tweets.urls` 的迁移模板（shape-based `ADD COLUMN`，放在 `create_tables()` 之前）。

| 列 | 内容 |
|---|---|
| `x_tweets.article_detail` TEXT | JSON：xbird 那 6 个增量键（`content` / `plainText` / `coverMedia` / `media` / `publishedAt` / `modifiedAt`），**不含** `title` / `previewText` |
| `x_tweets.article_attempts` INTEGER DEFAULT 0 | 发放计数，≥ `CONDENSER_X_ARTICLE_MAX_ATTEMPTS` 就不再进工作单 |

**`article` 列保持原样不动**（仍是 `{title, previewText}`）。这是向后兼容的关键：
`verdict.judge_text`、`search.x_document`、前端 `xBodyText` 三处都把 `article` 读作
「只有标题和摘要」，新列不碰它们，升级时逐个显式接入。

```python
def _migrate_x_article_v21() -> None:
    cols = [r[1] for r in tdb.db.execute_sql('PRAGMA table_info(x_tweets)').fetchall()]
    if not cols or 'article_detail' in cols:
        return
    tdb.db.execute_sql('ALTER TABLE x_tweets ADD COLUMN article_detail TEXT')
    tdb.db.execute_sql('ALTER TABLE x_tweets ADD COLUMN article_attempts INTEGER NOT NULL DEFAULT 0')
```

**重推不会清空新列**：`upsert_x_tweet` 的 `update={... for k, v in fields.items() ...}`
只覆盖 `ParsedTweet.row()` 里出现的列，新列不在其中——和 `messages.is_filtered` 的
扩展列契约同构。

### 3.1 待办查询

```sql
SELECT t.id FROM x_tweets t
  JOIN (SELECT tweet_id, MIN(first_seen_at) AS seen FROM x_feed_items GROUP BY tweet_id) f
    ON f.tweet_id = t.id
 WHERE f.seen >= ?                          -- now - CONDENSER_X_ARTICLE_BACKFILL_DAYS
   AND t.article IS NOT NULL
   AND json_extract(t.article, '$.title') IS NOT NULL
   AND t.article_detail IS NULL
   AND t.article_attempts < ?
 ORDER BY f.seen DESC
 LIMIT ?
```

要求有 feed 行，所以嵌入式引用推文（`insert_x_tweet_if_absent` 那条路径，永不覆盖已有行）
不会进工作单——它们在时间线上没有卡片，也就没有详情可点。

## 4. 后端改动

### 4.1 新模块 `condenser/xarticle.py`

Markdown → HTML。**无包内 import**（`text.py` 的先例：`items.py` 要用它，而它不能反向依赖）。

- `render_html(detail: dict) -> str | None`
  - mistune，**`escape=True`** 关掉裸 HTML 透传（X 的 MARKDOWN entity 可以携带任意
    Markdown——样本里的代码块和表格就是这么来的，所以必须用真解析器而不是手写子集）；
  - 自定义 image renderer：`![caption](url)` → `<figure><img src w h alt><figcaption>caption</figcaption></figure>`，
    `width`/`height` 按 URL 从 `detail['media']` 查表注入。图注走 figcaption 而不是只留 alt，
    是为了让 iOS 那条管线把它落成图片后面的文本块（RSS 的 `<figcaption>` 就是这个行为）；
  - `coverMedia` 渲成同样形状拼在最前（xbird 的 `content` 不含封面）。
- 图片 URL **保持 `pbs.twimg.com` 原样**。服务端先代理会让 iOS 变成代理套代理——
  `articleBlocks` 本来就会把每张图过 `proxiedImageURL`。Web 那边自己重写（§5.1）。

### 4.2 `condenser/x.py`

- `article_pending(limit, settings) -> list[int]`：§3.1 的查询 + 原子地 `article_attempts += 1`。
- `store_article_details(items) -> dict`：逐条写 `article_detail`（只保留 6 个已知键，
  `content` 和 `plainText` 全空则不写、计数已在发放时烧掉），然后 `search.index_x_tweets(ids)`
  重建这些条目的 FTS 文档。

### 4.3 `condenser/sources/x.py`

分两套 SELECT，照 `sources/rss.py` 的 `_LIST_COLS` / `_SELECT_FULL`：

- `_COLS`（列表用）：现状 + `(t.article_detail IS NOT NULL) AS has_article_content`，
  **不选 `article_detail` 本身**；
- `_COLS_FULL`（`get_row` / `rows_by_id` 用）：加选 `t.article_detail`。

⚠️ `rows_by_id` 同时被 `records.build_item_snapshot` 和 search 索引复用——快照要全文（§4.5），
search 走自己的 `_x_rows`（§4.6），互不打架。

### 4.4 `condenser/items.py`

`x_payload(row, with_content: bool = False)`，照 `rss_payload` 的形状：

```python
article = _json_field(row.get('article'))
if article:
    article = {**article, 'has_content': bool(row.get('has_article_content'))}
    if with_content:
        article['content_html'] = xarticle.render_html(_json_field(row.get('article_detail')))
```

`has_content` **永远都在**（列表和详情都给），`content_html` 只有 `with_content=True` 才有。
camelCase 的 `title`/`previewText` 是上游原样，snake_case 的 `has_content`/`content_html`
是我们算的——和 `media[]` 里 camelCase 透传的约定一致。

### 4.5 `condenser/records.py`

- `build_item_snapshot` 的 X 分支用 `with_content=True`，快照自带渲染好的 HTML；
  两端的 `hasInline` 分支直接命中，收藏条目不发请求。
- 新增 `x_article(tweet_id)`：活表查不到时从 `saved_items.raw_data` 回放。**不是装饰**——
  X 有 retention 扫除（`cleanup.sweep_x_retention`），旧推文会被删掉，而收藏的记录不该跟着瞎。

### 4.6 `condenser/search.py`

- `_x_rows` 的 SELECT 加 `t.article_detail AS article_detail`；
- `x_document` 拼上 `json_extract` 出来的 `plainText`（xbird 已经给了纯文本，不用从 Markdown 剥）；
- `TOKENIZER_VERSION` +1 → 全量重建（既有先例：新源接入时就这么做）。

### 4.7 `condenser/routers/x.py`

| 端点 | 说明 |
|---|---|
| `GET /api/sources/x/articles/pending?limit=N` | probe 工作单。`_require_source_enabled` |
| `POST /api/sources/x/articles` | probe 推正文。`_require_source_enabled` |
| `GET /api/x/tweets/{tweet_id}` | 客户端详情，返回整个 TimelineItem 信封（和 `rssEntry` 同形，客户端复用现成渲染）。活表 → `records.x_article` 回落 → 404 |

### 4.8 `condenser/config.py`

| 配置 | 默认 |
|---|---|
| `CONDENSER_X_ARTICLE_ENABLED` | `true` |
| `CONDENSER_X_ARTICLE_BACKFILL_DAYS` | `7` |
| `CONDENSER_X_ARTICLE_BATCH` | `5`（每轮上限） |
| `CONDENSER_X_ARTICLE_MAX_ATTEMPTS` | `3` |

## 5. 客户端

### 5.1 Web

| 文件 | 改动 |
|---|---|
| `lib/types.ts` | `XArticle` 加 `has_content?: boolean` / `content_html?: string \| null` |
| `lib/api.ts` | `xTweet(id: string) => request<TimelineItem>('/api/x/tweets/' + id)` |
| `hooks/useXArticle.ts` | 新增，`useRssArticle` 的翻版：`queryKey: ['x-article', id]`、`enabled: id !== null`、`staleTime: Infinity`（一条推文发出去就不变了） |
| `lib/sanitize.ts` | 新增 `proxyImages(html)`：`<img src>` → `previewImageUrl(src)`。「读一条推文不会让 X 看到读者 IP」这条承诺，长文配图也得算进去 |
| `ItemDetailBody.tsx` | 新增 `XArticleDetailBody`：标题 + `proxyImages(sanitizeHtml(content_html))`，套 `AnnotatedText` + `ARTICLE_PROSE`；未到手停在 `previewText` + spinner「正在加载全文…」，失败停在 `previewText` +「正文加载失败」。**失败不弹 toast**——降级到已经在屏幕上的东西，这是 RSS 定下的规矩 |
| `XCard.tsx` | 文章卡在 `has_content` 时加「查看全文」按钮 → `openPane(item)`。卡片仍**不**原地展开：正文只在详情里出现一次，因为高亮标注只能有一份底本 |
| `frontend/CLAUDE.md` | 更新 `XCard` / `ItemDetailBody` 两行 |

### 5.2 iOS

| 文件 | 改动 |
|---|---|
| `CondenserKit/…/RssBlocks.swift` → `ArticleBlocks.swift` | 重命名：`RssBlock`→`ArticleBlock`、`RssImage`→`ArticleImage`、`rssBlocks(fromHTML:baseURL:)`→`articleBlocks(fromHTML:baseURL:)`。X 传 `baseURL: nil`（URL 全是绝对的） |
| `CondenserKit/…/Models.swift` | `XArticle` 加 `hasContent: Bool?` / `contentHTML: String?` |
| `CondenserKit/…/APIClient.swift` | `xTweet(id:) async throws -> TimelineItem`，**不进 `CondenserAPI` 协议**（`rssEntry` 的先例） |
| `Condenser/UI/XDetailSheet.swift` | 抄 `RssDetailSheet.loadArticle()` 的三态机：`articleBlocks` / `articleLoaded` / `articleFailed`，`.task(id: tweet.id)` 触发，快照的 `contentHTML` 优先。**解析结果一次性存 `@State`**——2026-08-23 RSS 卡顿就是把整篇正则放进 `body` 踩的 |
| `Condenser/UI/RssDetailSheet.swift` | 跟着改名；`RssArticleImageView` → `ArticleImageView`，X 直接复用（含 `/api/preview/image` 代理与全屏查看器） |
| `Condenser/UI/XCard.swift` | `XArticleCard` 在 `hasContent` 时加「查看全文」提示 |

⚠️ Mac Catalyst 右侧栏：新 `@State` 必须靠外层 `.id(item.id)` 复位，否则切条目时上一条的
全文会串到下一条。`MessageListView` 已经保证了这一点，`XDetailSheet` 自己不用再加。

## 6. probe

| 文件 | 改动 |
|---|---|
| `pyproject.toml` / `uv.lock` | xbird 锁到 `8113c60`（1.3.0）。当前锁的是 `dfc5040`，venv 里装的还是 1.2.0 |
| `xsource.py` | `fetch_tweet_article(tweet_id, timeout_ms) -> dict \| None`：`client.get_tweet(id)`，失败照既有约定抛 `XSourceError`（xbird 把远端失败当**返回值**，吞掉会让死会话永远看不出来）。`ARTICLE_FETCH_DELAY = 1.0`，和 `FOLLOWING_PAGE_DELAY` 同一个理由 |
| `client.py` | `pending_articles(limit)` / `push_articles(items)` |
| `runner.py` | `run_round` 末尾加 `_run_articles(...)`：单条失败只记日志不沉整轮（`_run_feed` 的隔离约定）。**不进 SeenCache**——工作单本身就是服务端的去重 |

两条 scheduler lane（For You :05、feeds :00/:15/:30/:45）都会跑这一步，重复无害：
工作单是服务端算的，拿到正文的条目下一轮自然不在里面了。

## 7. 测试（BDD：先写行为用例）

**后端** `tests/test_x_article.py`
- 工作单：7 天窗口边界、`attempts >= 3` 不再发放、发放即计数、按 `first_seen_at` 倒序、`limit` 生效、无 feed 行的引用推文不进
- 推送：存 `article_detail`、`article` 列不被改写、`text` 不被改写、重建 FTS
- 列表 payload **不含** `content_html`、**含** `has_content`
- 详情端点：活表命中 / 快照回落 / 404
- `judge_text` 对有全文的推文输出不变（回归钉子）

`tests/test_xarticle_render.py`
- 标题/列表/引用/代码块/图片；`width`/`height` 按 URL 注入；图注进 `<figcaption>`；封面在最前；裸 HTML 被转义

**probe** `tests/test_probe.py` 追加：轮次末尾取工作单并推回；单条失败不沉整轮；工作单为空时不发请求

**Web**：`XCard` 有全文时出「查看全文」、卡片不渲染正文；`ItemDetailBody` 的加载/失败/快照三态

**iOS**：`ArticleBlocks` 改名后原用例全绿 + X 的绝对 URL 用例；`APIClient.xTweet` 的 `MockURLProtocol` 用例

## 8. 文档

- `kb/docs/database.md` — v21 changelog + 两列说明
- `CLAUDE.md` — `x.py` / `search.py` / `records.py` 行，新增 `xarticle.py` 行
- `kb/docs/probe.md` — 轮次末尾这一步
- `frontend/CLAUDE.md` — 组件清单两行
- `kb/docs/status-and-gaps.md` — 落地记录

## 9. 已知遗留

1. **表格渲染是残的。** xbird 的 draftjs 渲染器把每个 MARKDOWN entity 当独立 block，
   块间用 `\n\n` 连接，所以样本里那个表格变成了被空行隔开的几行 `| a | b |`，GFM 解析不出来。
   这是 xbird 侧的问题（合并相邻 MARKDOWN block 即可），本次不动。
2. **推文自己写的那句话取不到。** xbird 的 `extract_tweet_text` 是短路链
   `article → note → legacy.full_text`，有 article 时推文自身文本在输出里根本不存在。上游行为。
3. **`inlineStyleRanges` 被忽略** —— 粗体/斜体/行内代码在 `content` 里丢失（draftjs 渲染器
   从 TS 1:1 移植的已知局限）。
4. **引用一篇长文时 quote 卡片看不出是长文。** `sources/x.py` 的联表投影里没有 `q_article`，
   `_x_quote` 拼出来的精简 payload 连标题都没有。既有缺口，不在本次范围。
5. **超过 7 天的存量文章永远只有摘要**，且没有按需触发的手段（服务端不能直连 X）。这是
   决策 3 的明码代价。

## 相关文档

- [xbird：TweetArticle 携带 X Article 完整详情](../../../xbird/kb/sessions/2026-09-16-x-article-full-content.md) — 上游接口变更，本计划的前提
- [RSS 列表摘要 + 详情端点拆分](2026-08-23-rss-list-excerpt-detail-endpoint.md) — §4.3/§4.4 照抄的范式
- [X 源与本地 probe](2026-07-24-x-source-local-probe.md) — 推模型的由来，其中 bird 实测第 9 条正是「长文全文拿不到」
- `kb/docs/probe.md` — probe 轮次结构与 xbird 不变量
- `kb/docs/database.md` — 迁移约定与 `init_db` 顺序陷阱
