---
created: 2026-09-17
tags:
  - purifier
  - x
  - backend
  - ios
  - plan
---

# Purifier 代理 X —— 用 FxEmbed API 把一条推文渲染成讨论页

> **状态：两期代码已实现（2026-09-17），未部署。** 实现中的偏离与新实测见 §8。本计划推翻 `2026-09-07-purifier.md` §4 的一条决定
> （「X 链接不改写，一律深链进 X app」），范围限定在 **status 链接**；
> 其余 x.com 链接的深链行为保持不变。

## 0. 起因与调研

原始设想是「把 fixupx.com 当作 X 的 purifier 处理器」——点一个 X 链接，代理去抓
fixupx 对应页面。**这条路是死的**，实测（2026-09-16）：

```
$ curl -A "<Chrome UA>" -I https://fixupx.com/jack/status/20
HTTP/2 302
location: https://x.com/jack/status/20
```

fixupx 只对 bot UA 吐内容，浏览器 UA 一律 302 回 x.com。而 purifier 的
`preview._fetch_capped` 是 `follow_redirects=True`，所以**照现在的代码抓 fixupx，会静默落到
x.com 的空 SPA 壳上**，readability 抽不出东西 → pure.md 兜底 → 一个废页面。

伪造成 bot UA 也不行，拿到的是完整 body 为空的 OG meta 页：

```html
<head>…<meta property="og:description" content="just setting up my twttr"/>…</head><body></body>
```

FxEmbed 从来不是一个「网页」，它是给 Discord/Telegram 拼卡片用的一堆 meta 标签。

**但它有一套完整的匿名 JSON API**，而且在活跃维护
（`x-powered-by: fixtweet-main-1b15459-2026-09-16T01:26:08`）：

| 事实 | 值 |
|---|---|
| Base | `https://api.fxtwitter.com`，v2 在 `/2/` 前缀（v1 `/:handle/status/:id` 仍兼容） |
| 认证 | 无 |
| 限流 | **1000 req/min per IP**（官方文档原话：generous enough for most legitimate applications） |
| 规格 | `https://api.fxtwitter.com/2/openapi.json`（v2.0.0，机器可读） |
| 自建 | 支持（Cloudflare Worker / Docker，MIT） |
| 文档 | <https://docs.fxembed.com/api/introduction> |

相关端点：`/2/status/{id}`、`/2/thread/{id}`（展开自串）、**`/2/conversation/{id}`（自串 +
回复）**、`/2/status/{id}/quotes`、`/2/profile/{handle}`。

所以方向对、形态要换：**不是代理它的页面，而是调它的 API + 我们自己渲染**。这反而更好——
版面我们控制、图片能走 `/pa`、能把讨论串渲染出来，正对应 HN 走 `proxy` 模式的那条逻辑
（结构本身就是内容）。

### 两个决定性的实测

**① `/2/conversation/{id}` 对一条回复调用时，`thread` 返回的是祖先链**，不只是自串：

```
conversation/1770888775830262034 →
  thread[0] = 20                   jack           'just setting up my twttr'
  thread[1] = 1770888775830262034  derbederdusler '@jack'
  replies   = 15 条（对 target 的回复）
```

天然给出「上文 + 下文」，正是一个阅读页该有的形状。

**② replies 已按热度排好序**（conversation/20 的 34 条，点赞严格递减、时间完全乱序）：

```
8034 → 5182 → 4723 → 4378 → 3336 → 1977 → 951 → 923 → …
```

即「取前 N 条」天然等于「取最热的 N 条」，**我们不需要自己排序**。

## 1. 决策

1. **数据源 = FxEmbed 公开 API**，不抓页面。base URL 做成配置项，将来想自建改一行 env。
2. **每页内容 = `/2/conversation/{id}`**：祖先链全渲染 + 回复前 N 条。一次请求拿全，
   不用 `/2/status` + `/2/thread` 两次。
3. **落地形态 = 新模块 `purifier_x.py` + `render_document` 顶部的 handler 分派**。
   URL 形态不变（`/p/x.com/jack/status/20`），iOS 不需要知道 fxembed 存在。
   照 `vectors.py` / `search.py` 的惯例：**只有一个模块知道 fxembed 存在**。
   *不*做成第四个 `Mode`——前三个是渲染策略，这个是数据源，而且 `MODE_RULES` 只认 host，
   分不开 `x.com/<user>/status/<id>` 与 `x.com/<user>`。
4. **只认 status**。其余 x.com 链接（主页 / Spaces / 搜索 / 列表）一律保持现状——它们
   **现在是能用的深链**，一刀切吸进代理只会把它们变成错误页，那是退步。
   代价：两端的排除判定要从「按 host」改成「按 host + path」。
5. **别名归一 + 重定向后重分派**：
   - `fixupx.com` / `fxtwitter.com` / `vxtwitter.com` / `twittpr.com` 的 status 路径在分派时
     零成本归一到 X handler（**顺手修掉上面那个废页面 bug**——`fixupx.com` 现在不在排除表里，
     而我们自己的 `forward.py` 就在生产 fixupx 链接）；
   - 其它 URL（t.co、bit.ly…）走正常流程，但在扔进 readability 之前检查 `final_url`：
     落在 x.com status 就转交 X handler。代价是浪费一次对 x.com 壳的抓取（有字节上限）。
6. **iPhone 上阅读开关开着时，代理页优先于 X app 深链**。
   这推翻 `ExternalLink.swift` 现有的顺序（X 深链先于一切）。理由：开关本身的语义就是
   「我要在 condenser 里读」；不动顺序的话 X handler 在手机上几乎永远不会被触发，
   只在页内链接和 Mac 上生效，投入产出不匹配。
   **已知代价**：代理页在 SFSafariViewController 里显示，页内的 `twitter://` 或 x.com
   universal link 通常**不会**跳进 X app，所以「先读、想互动再一键去 app」这条退路在 iPhone 上
   是打折的（等于要手动复制链接）。接受。
7. **只用 FxEmbed，purifier 不碰数据库**。拿不到就是现有的 502 错误页（它本来就带原链接）。
   不查 `x_tweets` 兜底——保持 purifier 与三个既有模式一致的职责边界（拿不到就是拿不到），
   模块也因此能脱离 DB 测试。
8. **图片降级 + 代理，视频只给封面**：`?name=orig` → `?name=medium` 后走 `/pa`；
   视频画 `thumbnail_url` + 一个「▶ 视频 · 在 X 上看」的链接。
9. **配置 = 一个变量**：`CONDENSER_PURIFIER_X_API_BASE`，默认 `https://api.fxtwitter.com`，
   **置空即关闭**（X 链接回到今天的行为）。项目「钥匙即开关」惯例的同构形式——FxEmbed 不要
   钥匙，那就让地址兼任开关，同时是自建入口。
10. **回复规则**：热度序取前 N（`CONDENSER_PURIFIER_X_REPLIES`，默认 20）；**原推作者自己的
    回复无论排名都保留并标出**（作者在回复区的补充/更正是讨论串里最值钱的部分，而它往往没有
    高赞）；`possibly_sensitive` 的回复文字照常显示、**图默认打码点击展开**。
11. **模板复用 `reader_page`** + 一段 X 专用内联 CSS。工具栏 / 深色模式 / 字体 / 字号全部继承；
    `MODE_LABELS` 加一个「推文」；**没有「整页模式」链接**（X 没有那个概念）。
    标题用「姓名 @handle」。
12. **分两期**：先后端上生产（页内链接立即受益，顺便实测 fxembed 在生产可达性），
    iOS 那半跟下一个 build。

## 2. 落点

### 第一期（后端）

- **`condenser/purifier_x.py`**（新）——唯一知道 fxembed 存在的模块：
  - `parse_status_url(host, path) -> str | None`：认 `/{handle}/status/{id}`、`/i/status/{id}`、
    `/i/web/status/{id}`，容忍尾部 `/photo/1` `/video/1` `/analytics`，id 必须纯数字；
    host 认 x.com / twitter.com + 上面四个别名（含 `www.` / `mobile.` / `m.` 前缀）。
  - `fetch_conversation(status_id, settings)`：一个小 httpx 客户端。
    **不能复用 `preview._fetch_capped`**——它的 `accept` 是给 HTML / 资源用的。
    超时复用 `condenser_preview_fetch_timeout`，做成可注入的 seam（照 `fetch_page` 的先例）。
  - `render(conversation, own_origin) -> DocumentResult`：JSON → body_html，
    `purifier_html.reader_page` 套壳。
  - 图片 URL 的 `name=orig` → `name=medium` 改写 + `/pa` 包装。
- **`condenser/purifier.py`**：
  - `resolve_handler(target)` —— `render_document` 的第一步，命中就走 handler、不到
    `resolve_mode`；cache key 带上 handler。
  - `rewrite_url`：`EXCLUDED_REWRITE_HOSTS` 的判定从「按 host」改成「按 host + path」——
    x.com / twitter.com 的 **status 路径进代理**，其余路径仍保持绝对链接；t.me 不变。
  - `_render_readable`：抓完之后、扔进 readability 之前，`final_url` 命中 X status 则转交
    （决策 5 的第二层）。
- **`condenser/purifier_html.py`**：X 专用 CSS 常量 + `MODE_LABELS['x'] = '推文'`。
- **`condenser/config.py`**：`condenser_purifier_x_api_base`、`condenser_purifier_x_replies`。
- **`.env.example`**：两个新变量 + 一句话说明。

### 第二期（iOS）

- `CondenserKit/PurifierLink.swift`：`isPurifierExcludedHost(_:)` → 改成带 path 的判定
  （名字也该跟着改，比如 `isPurifierExcluded(host:path:)`），x.com status 不再排除。
- `Condenser/UI/ExternalLink.swift`：分支顺序——`Purifier.rewrittenURL` 返回非 nil 时
  **不再走 `xAppURL` 深链**。
- `CondenserKit/Tests/…/PurifierLinkTests.swift`：钉住「两端排除表一致」的那组用例要同步改，
  并补 status / 非 status / 别名三类。

## 3. 数据形状（FxEmbed v2，实测 + openapi 核对）

`GET /2/conversation/{id}` → `{code, status, thread[], replies[], author, cursor}`

`APITwitterStatus` 用得上的字段：

| 字段 | 说明 |
|---|---|
| `id` / `url` / `created_at` / `created_timestamp` | 基本信息 |
| `text` | 正文（t.co 已展开） |
| `raw_text.display_text_range` | **X 自己标出的「去掉开头 @ 提及后的显示范围」**，照它切就干净了，不用写正则 |
| `raw_text.facets` | 实体，链接改写用 |
| `author` | `screen_name` / `name` / `avatar_url` / `verification` |
| `likes` / `reposts` / `replies` / `quotes` / `views` | 统计 |
| `media.photos[]` | `url`（`?name=orig`）/ `width` / `height` / `altText` |
| `media.videos[]` | `url` / `thumbnail_url` / `duration` / `formats[]` |
| `media.external` | 外部视频 |
| `quote` | **嵌套的 status，或 `APIStatusTombstone`**（被删的引用推）——两种都要处理 |
| `poll` / `community_note` / `card` | 投票 / 社区注释 / 卡片，渲染与否见 §6 |
| `possibly_sensitive` | 敏感标记 |
| `replying_to` | `{screen_name, status, url, profile_url}` |
| `article` | **只有 `title` / `preview_text` / `cover_media`，没有正文**（见 §6 已知损失） |

`replies[]` 是 `APISubstatus`（字段少一些，但 text / author / media / possibly_sensitive 都在）。

失败形态：推文删了 / 账号封了 → `code 404`；受保护、年龄限制 → `code 401`；
fxembed 挂了或限流 → 5xx / 超时。**注意 `code` 在 body 里，HTTP 状态可能是 200**，
判定要读 body 的 `code`。

## 4. 测试（BDD，先写后实现）

- fixture 用真实 JSON 存盘（已在 scratchpad 抓到 `conversation/20` 与一条回复的 conversation），
  **不打网络、不花钱**。
- `parse_status_url`：四种 host × 三种 path 形态 × 尾巴 × query 垃圾 × 非 status 必须返回 None。
- `rewrite_url`：x.com status → `/p/…`；x.com 主页 / Spaces / 搜索 → 保持绝对；t.me 不变。
- 渲染：祖先链顺序、回复截断到 N、作者回复必显、`display_text_range` 切掉开头提及、
  引用推 tombstone 不炸、敏感图打码、`name=orig` → `name=medium` + `/pa`。
- 失败：`code 404` / `code 401` / 超时 → 502 错误页且带原链接。
- 开关：base URL 置空 → X 链接不进代理（`rewrite_url` 保持绝对）。

验收：本地起后端，浏览器打开几条真实推文（含带图、带引用、带视频、长串）截图，
归档到 `tmp/2026-09-17-purifier-x/`。

## 5. 风险

1. **生产可达性未验**：`api.fxtwitter.com` 我在本机验过，生产服务器上没有。第一期上线即实测。
2. **FxEmbed 依赖 X 的 guest 通道**，历史上被封过多次。坏了就是 502 错误页 + 原链接，
   不影响其它源；真长期坏了就把 base URL 置空。
3. **代理页禁 JS**（purifier 的铁律，`/p` 页跑在 condenser 自己的 origin 上）。
   所以决策 10 的「敏感图点击展开」**不能用 JS**，得用 `<details>` 或 checkbox + CSS。
4. **`?name=medium` 仍可能超 `/pa` 的字节上限**，而 `_fetch_capped` 超限是**截断**不是报错
   （`body[:cap]`）——会得到一张下半截烂掉的图。上线后看一眼实际尺寸，必要时降到 `small`。

## 6. 已知损失（明确接受）

- **X 长文（v21，`005be8e`）在代理页里会降级**：FxEmbed 的 `article` 只给
  `title` / `preview_text` / `cover_media`，**没有正文**。归档里有全文，但决策 7 定了
  purifier 不查库，所以一条长文推的代理页只有标题 + 预览段 + 封面。
- **投票 / 社区注释 / 卡片**第一期先不渲染（数据在，加是增量的事）。
- **翻页不做**：`cursor.bottom` 能翻更多回复，但代理页是「读一眼讨论」，不是 X 客户端。
- **Web 前端不接**：purifier 至今是 iOS-only（web 只有一条 service-worker denylist 防止
  `/p` 被 SPA 壳接管），这次不改变这一点。

## 7. 与既有文档的一处表面矛盾（写进注释，免得以后看着像自相矛盾）

`xarticle.py`（2026-09-16）明确写了「**图片 URL 留在 pbs.twimg.com**，因为 iOS 已经把正文图过
`/api/preview/image` 了，这里再代理就是 proxy 套 proxy」。本计划决策 8 却要代理图片——
两者不冲突：`xarticle` 的产物是交给**客户端**渲染的 HTML 片段，客户端自带代理层；
代理页是**浏览器直接看**的完整页面，没有那一层，`/pa` 是唯一可用的通道，而
「读一条推文，浏览器永远不直连 X」是项目既有原则。

## 8. 实现记录（2026-09-17）

落地：`condenser/purifier_x.py`（新）、`purifier.py` 分派 / `rewrite_url` / 重定向转交、
`purifier_html.py`（`X_CSS`、`reader_page(heading=, extra_css=)`）、`routers/purifier.py`
（`_fetch_x` 注入点、关闭时 302）、两个配置项；iOS Kit `isPurifierExcluded(host:path:)`、
`ExternalLink.swift` 分支顺序、`XDetailSheet` 两个按钮。测试：后端 959（`tests/test_purifier_x.py`
35 例，fixture 为 5 份真实 conversation 响应，`tests/fixtures/x_fxembed/`），Kit 337，iOS `make build`
通过。走查截图 `tmp/2026-09-17-purifier-x/`（隔离实例：临时库、临时密码、计费 key 全置空，
`serve.sh`）：长 note + 视频、引用 + 图、长文卡片、自串续篇、祖先链、深色、删除推文的 502 页，
另外实测了真实 t.co 链接 301 → twitter.com → x.com 后被转交给 X handler。

### 8.1 实测推翻 / 修正的前提

1. **Cloudflare 按 UA 拦截**：`python-httpx/*` UA 拿到 403 + challenge 页（`cf-mitigated: challenge`，
   与 HTTP/1.1 还是 HTTP/2 无关），项目 UA `CondenserBot` 放行。`fetch_conversation` 必须带
   `condenser_preview_user_agent`，有测试钉住。
2. **§0 ②「replies 按点赞严格递减」只对 `conversation/20` 这种无嵌套的成立。** `replies` 是 X 的
   conversation module 排版：一条顶层回复后面跟着它下面的回复（常是作者在答），而且不保证树序
   （长文样本里一条回复排在列表最后，它的父节点在中间）。所以按 `replying_to` 重建树，**N 数的是
   顶层线程**，决策 10 的「作者回复必显」落成「作者说过话的线程整条保留」（只留作者那条会丢掉
   它在回谁）。
3. **自串续篇不在 `thread` 里**（`thread` = 祖先链，以目标推本身结尾），而是出现在 `replies` 里。
   实现把「作者回复自己」的链从回复里提出来，接在主推下面。
4. **facet 下标是 code point**（openapi 文案写 UTF-16，对 X 不成立），note tweet 的 media facet
   下标会指向旧的截断文本。每个 facet 用前先核对原文，url / media 核对不上按 t.co 串搜，mention
   核对不上就当普通文本。`display_text_range` 也会越界（note tweet 598 字给 `[0, 599]`），夹住。
5. **§6「长文没有正文」已不成立**：FxEmbed 的 `article` 现在带 `content`（Draft.js `blocks` +
   `entityMap`，含 MEDIA / MARKDOWN 实体）和 `media_entities`。本期仍只渲染卡片（标题 + 导语 +
   封面 + 「在 X 上读全文」），正文渲染是可以单独做的增量——fixture `conversation_article.json`
   里有完整样本。
6. **风险 4 基本消除**：`name=medium` 实测约 100KB（原图 190KB、视频封面 115KB），离 `/pa` 5MB 上限很远。

### 8.2 与决策的偏离

1. **关闭开关的形态**（§4「置空 → rewrite_url 保持绝对」）：`rewrite_url` 不看开关——它是 URL 形状
   的事实，给它穿 settings 要改五层签名。关闭时由 `/p` 把推文请求 302 回原链接
   （`purifier.passthrough_url`）。页内链接的结果与「保持绝对」一样（多绕一跳），而且同一条规则
   也兜住了 iOS 已改写发来的请求——服务端关了，app 不需要知道。
2. **`render` 的签名**：`purifier_x.render(conversation, link=, asset=, replies_limit=) -> XPage`，
   由 `purifier.py` 套 `reader_page` 和 `DocumentResult`。`purifier_x` 反过来 import `purifier`
   会循环；注入两个改写函数后它也不需要知道 `/p` `/pa` 长什么样。标记全部在生成时转义，**不过
   sanitizer**——sanitizer 会把两条必须保持绝对的链接（mp4、「在 X 上看全部」）也改写掉，后者
   经代理就是本页自己。
3. **视频**（决策 8「封面 + 在 X 上看」）：封面仍走 `/pa`，点击打开码率 ≤ 2.5 Mbps 的 mp4（通常
   720p）。手机浏览器能直接播，不用面对 X 的登录墙；只在读者点击时直连 video.twimg.com，和
   「在 X 上看」一样是显式动作。没有 mp4 时才回落「▶ 视频 · 在 X 上看」。
4. **敏感图的范围**：决策 10 说的是回复；实现为「主推以外」的 `possibly_sensitive` 媒体都收进
   `<details>`（祖先、续篇、回复、引用推）——读者点开的那条照常显示。
5. **标题行**：`<title>` 按决策 11 是「姓名 @handle」，但页面里不再画 `h1`（`reader_page(heading=False)`）：
   祖先链在主推上方，页头放主推作者名反而错位。
6. **iOS 的「在 X 上打开」「作者主页」不经代理**（`openExternalURL(purify: false)`）：决策 6 针对的是
   正文里的链接；详情页这两个按钮的意图就是进 X app，读者此刻正在读这条推文。
7. **时间统一显示 UTC**（`2026-09-15 03:50 UTC`）：页面有缓存、不跑 JS，没有可靠的本地时区。
