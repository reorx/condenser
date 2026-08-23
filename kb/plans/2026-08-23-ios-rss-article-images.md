# iOS：RSS 详情按需取全文，正文里带图

状态：已完成（2026-08-23。§1/§3/§5 与 §4 的文字部分已先行于 commit 3bdc361 落地；
本轮补 §2 块解析器、详情图片渲染、SnapshotCache v3；验收截图
`tmp/2026-08-23-ios-rss-images/`）
前情：`2026-08-23-rss-list-excerpt-detail-endpoint.md`（载荷瘦身，后端 + web 已实施）
起因：读者反馈 `rss:677` 在 iOS 上看不到图片

## 背景与已确认的事实（不必重新调查）

### 后端与 web 已经完成，iOS 是唯一没跟上的一端

- 列表 payload 不再带正文：`rss` payload 是 `content_excerpt`（≤500 字符纯文本，
  `condenser/text.py:excerpt`，ingest 时算好存列）+ `content_truncated`
  （末尾省略号的**回读**——客户端不要自己嗅探那个字符）。`content` 字段在列表里
  **不存在**。
- 全文在 `GET /api/rss/entries/{id}`（`condenser/routers/rss.py:118`）：返回的是**完整
  envelope**（不是 `{content: ...}`），所以客户端能用已有的卡片/详情代码渲染它。
  不按订阅作用域——暂停的 feed、搜索到的条目照样能取；归档行被 retention 清掉时回落
  收藏快照（`records.rss_article`），真的没有才 404。
- web 端已接完：`frontend/src/hooks/useRssArticle.ts`（`staleTime: Infinity`，已发布的
  文档不会在我们脚下变）+ `RssCard` 的 more 懒加载 + 失败保留 excerpt。
- ⚠️ 后端那批改动**还在工作树里没提交**。push master 即生产部署，所以上线顺序是：
  后端 + web 先落地，iOS 再发 build。

### iOS 现在是坏的，不只是没图

`Models.swift:661` 的 `RssEntry` 只有 `content`，而列表里已经没有这个字段了 →
`contentText` 恒为 nil → **卡片正文和详情正文现在都是空白**（`RssCard.swift:46/57`
两个分支、`RssDetailSheet.swift:29` 都依赖它）。接 `content_excerpt` 不是本任务的
可选项，是必须一起做的前提。

`MainView.swift:205` 的 debug 路由用 `$0.rss?.contentText != nil` 挑「第一条有正文的」，
同样失效。

### 要用的东西全都现成（X 推文媒体在用的那套，别新造）

| 已有 | 位置 | 作用 |
|---|---|---|
| `APIClient.proxiedImageURL(_:)` | `APIClient.swift:168` | 任意外站图片 → `/api/preview/image?url=`，客户端从不直连第三方 |
| `APIClient.authedRequest(_:)` | `APIClient.swift:173` | 非 JSON 资源带 Bearer |
| `ImageLoader.shared` | `Services/ImageLoader.swift` | 带 header 的图片加载 + 手动 URLCache 读写（代理不一定带缓存头） |
| `AuthedAsyncImage` | `UI/AuthedAsyncImage.swift` | 骨架 → 淡入 → 失败占位图标 |
| `ImageViewerScreen` / `ImageViewerItem(urls:startIndex:)` | `UI/ImageViewerScreen.swift` | 全屏浏览：`ViewerPhoto.proxied` 就是给任意代理 URL 准备的，多图可左右翻 |
| `SelectableTextView` | `UI/SelectableTextView.swift` | UITextView 包装：长按选取 + 链接走统一出口 + 跟随 `readingFontScale` |

详情 sheet 的三个 present 点都在 `ReaderSession` 环境内（`reader.api` 可达）：
`MessageListView.swift:191`、`SavedScreen.swift:93`、`MainView.swift:74`（debug 深链）。

### 验收样本（生产实测）

`rss:677` = kawabangga《生活来在一个包里》，`content` 2442 字符，两张绝对 URL 的
`<img>`（wp-content 的 png / jpeg，都带 `width`/`height` 属性），`summary` 为 NULL
——正好覆盖「无摘要 + 有图」这条主路径。

## 目标设计（方案已定，细节自行落实并写清理由）

### 1. Kit 模型跟上契约（`Models.swift` 的 `RssEntry`）

- 加 `contentExcerpt: String?`（`content_excerpt`）与 `contentTruncated: Bool`
  （`content_truncated`，用 `decodeIfPresent ?? false`——老快照里没有这个键）。
- `content` **保留 optional**：详情接口的响应带它，收藏的旧快照也带它。
- 卡片改吃 `contentExcerpt`（后端已经剥净标签，客户端不再解析 HTML）；`contentText`
  退化成「拿到全文之后才有值」的降级路径。`RssCard.swift` 两个分支同步改。
- `SnapshotCache` 的契约版本号 bump（`condenser-snapshots-v2` → `v3`，机制见
  `ios/CLAUDE.md`）：旧快照按 miss，代价是冷启动多一次网络请求，一次性。

### 2. Kit 新增块解析器（新文件 `RssBlocks.swift`）

```swift
public enum RssBlock: Equatable, Sendable {
    case text(String)
    case image(RssImage)
}
public struct RssImage: Equatable, Sendable {
    public let src: String        // 已解析成绝对 URL
    public let width: Int?        // <img> 属性，用来预留纵横比
    public let height: Int?
}
public func rssBlocks(fromHTML html: String, baseURL: URL?) -> [RssBlock]
```

**实现路径（重要）**：不要另写一套 HTML 处理。`rssPlainText` 里那些决定
（`<script>`/`<style>` 连内容丢、`<pre>` 整块摘出去再放回、锚文本保留、源码换行按空白）
是踩出来的，分叉一份必然漂移。做法是**先把 `<img>` 替换成私用区占位符**——
`RssText.swift:60` 已经有 `\u{E000}` 的先例，用第二个码位——跑完既有管线，再按占位符
切块。两条路径于是共享同一份规则。

细节：

- `src` 用 `URL(string:relativeTo:)` 解析，base 取 `entry.link`（大量 feed 写相对路径）；
  只留 http/https（`data:` 丢掉——代理端 `_require_http_url` 也会拒）。
- **lazy-load 兜底**：`src` 缺失或是 `data:` 占位图时回落 `data-src` / `data-original`。
  这是真会踩到的坑，很多 WordPress 插件就是这么发的。
- `width`/`height` 属性带出来，UI 用它预留纵横比，图片加载完不跳动。
- `<figcaption>` **不单独建模**：它的文字自然落进下一个文本块，顺序对读者是对的，
  少一个概念。
- 不需要 `.code` case：`<pre>` 的内容经既有管线恢复成保留缩进的纯文本，落在文本块里。
- 空文本块丢弃，相邻文本块合并。
- 有图但一张都解析不出（全是 data URI）时返回单个文本块 —— 调用方不必分辨这种情况。

BDD：先在 `CondenserKit/Tests/CondenserKitTests/` 写用例再实现。至少覆盖 677 的真实
片段（`<figure><img …/></figure>` 夹在段落之间）、相对 URL、lazy-load `data-src`、
无图纯文本（结果等价于 `rssPlainText`）、`<pre>` 保留、`<script>` 丢弃。

### 3. Kit API

`APIClient.rssEntry(id: Int) async throws -> TimelineItem` —— 打
`/api/rss/entries/{id}`，与 web 的 `api.rssEntry` 对称。

### 4. `RssDetailSheet` 打开即取全文

`.task` 里拉一次，三态：

1. **初始**：直接渲染列表已有的 `contentExcerpt`。sheet 打开的瞬间就有东西读，
   不是空白 + 转圈。
2. **成功**：解析成块**在 task 里算一次存 state**——不要在 `body` 里反复算。
   （旧 `contentText` 是计算属性、每次重渲染对全文重跑一遍解析，正是这轮瘦身的起因
   之一，别把它换个地方复活。）文字块 → `SelectableTextView`，图片块 →
   `AuthedAsyncImage`。
3. **失败**：保留 excerpt + 一行「正文加载失败」，措辞与 web 对齐。正文短一截仍然是
   这条条目的真实呈现，空白不是。

图片渲染：宽度撑满内容列；有 `width`/`height` 时按 `aspectRatio` 预留高度；点击进
`ImageViewerScreen`，`ImageViewerItem(urls:startIndex:)` 收**全文所有图片**并从点中的
那张起，所以在查看器里能左右翻。

**收藏条目不要分叉**：records 列表按约定同样只给 excerpt，所以已收藏的条目走同一个
接口（`rss_article` 是它的服务端兜底）。客户端不该知道快照这回事。

摘要块（`AiSummaryBlock`）位置不变：摘要在上、全文接在下面。

### 5. debug 路由跟上

`MainView.swift:205` 挑「第一条有正文的」判据改成 `contentExcerpt`。

### 6. 明确不做

**卡片不加主图 / 缩略图**。列表的账刚刚才瘦下来，卡片再引入每条一张图的请求，要重新
算一遍每屏的网络量与滚动开销，值得单独一轮。本次只动详情。

## 兼容性注意

- 纯客户端改动，不影响生产部署；但依赖后端新契约，所以**后端 + web 先 push 上线**。
- TestFlight 上的 1.1.0 (3) 解的是老字段：服务端一上线，那个 build 的 RSS 卡片正文就
  空了（decode 不炸，字段是 optional）。单用户项目可接受，在
  `kb/docs/status-and-gaps.md` 记一笔并尽快发新 build。
- 开发方法遵循根 CLAUDE.md：新功能 BDD，先写行为测试再实现。

## 验收

- Kit：`make test` 全绿，含上面列的解析用例。
- 模拟器走查：dev DB 里没有 677，先把生产那条灌进去——
  `ssh hh-hk-01 "sqlite3 -readonly /opt/apps/condenser/data/condenser.db \"SELECT content FROM rss_entries WHERE id=677;\""`
  写进 `tmp/rss-fixes-dev.db` 的对应行（该库已插好 `devtoken-ios-sim` 的 device 行，
  起法见 `ios/CLAUDE.md`「跳过授权直连本地后端」+「CLI 驱动的界面走查」）。
  路由 `detail/rss/<id>`，验四样：两张图都出来、加载中先有 excerpt、点图进全屏能翻页、
  断网时降级文案。
- 顺带回归卡片：`rss` 路由截一屏，确认正文回来了（这是当前线上的伤）。
- 截图归档 `tmp/2026-08-23-ios-rss-images/`，测完 `mac-dev-cleanup --only sim`。
- 文档同步：`ios/CLAUDE.md` 的 RSS bullet（「没有媒体」这句作废了）、
  `kb/docs/status-and-gaps.md` 记录本次改动。
- 分阶段 commit；本文档实施完把状态行改成「已完成」。
