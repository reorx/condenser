---
created: 2026-07-25
tags:
  - session
  - x-twitter
  - ios
  - swiftui
  - condenserkit
  - feedback-ranking
---

# X 信息源 Phase 5：iOS 完整适配（计划全部收尾）

## 概要

按 `kb/plans/2026-07-24-x-source-local-probe.md` 推进最后一个 phase：把 X 的全部阅读面搬到
iOS。这一步同时关掉 Phase 2 部署后留下的**空窗**——`MessageListView.card(_:)` 只认
telegram/hn，关注人的推文在聚合流里渲染成空白行。

按 BDD 做：先在 `CondenserKit/Tests/` 写行为测试（fixture 用 `tmp/make_ios_fixtures.py x`
从 dev DB 生成的**真实后端 JSON**，覆盖 For You/关注人、引用推、转推、长文、媒体、三种
verdict、up/down 标签），再实现。Kit 层落 `XTweet` payload 家族 + envelope 的源通用
`feedback` + 贯穿的 `feed` 作用域 + 反馈端点；App 层落 `XCard` / `XDetailSheet` /
`XFeedTimelineScreen`（For You 唯一入口）/ 判定徽标与证据。161 Kit + 256 backend 全绿，
`make build` 通过。

模拟器连本地 dev 后端做了走查（真实 bird 数据 + 真实 DashScope 判定结果），截图在
`tmp/2026-07-25-x-phase5-ios/`。走查中撞上一个环境限制：**本机模拟器窗口拿不到
`System Events` 句柄，合成点击无从下手**，所以「点拇指」这一下真点不了，写入路径只能拆成
两段验证（见「注意事项」）。为此给 debug 深链补了三条路由。

自审时发现「卡片下标 → 查看器下标」的映射在两处各写了一遍且已经不一致（收藏页那份没跳过
视频），把它收进 Kit 的 `photoIndex(forDisplayed:)` 并补了两个场景，重新走查确认渲染无变化。

## 修改的文件

### CondenserKit（纯逻辑 + 单测）

| 文件 | 改动 |
|---|---|
| `Sources/CondenserKit/Models.swift` | 新增 `XMediaItem` / `XMetrics` / `XArticle` / `XQuote` / `XVerdict`(+`XVerdictMeta`/`XVerdictNeighbor`) / `XTweet`，以及源通用的 `ItemFeedback`；`TimelineItem` 加 `x` 与 `feedback`；`SourceID.x`、`XFeed`（`foryou` + 展示名回落）；`XTweet` 上挂卡片要用的纯逻辑（`bodyText` / `displayName` / `tweetURL` / `profileURL` / `displayedMedia` / `photos` / `photoIndex(forDisplayed:)`）与公开的 `xTweetURL(id:handle:)` |
| `Sources/CondenserKit/CondenserAPI.swift` | 协议加 `feed` 参数与 `setFeedback` / `clearFeedback` |
| `Sources/CondenserKit/APIClient.swift` | `timeline` / `timelineNew` 的 `feed` query；`POST /api/feedback`、`DELETE /api/feedback/{key}`；`xAvatarURL(handle:)`、`proxiedImageURL(_:)` |
| `Sources/CondenserKit/TimelineStore.swift` | `feed` 作用域字段 + 三处 API 调用透传；乐观 `setFeedback`（同侧撤销、失败回滚） |
| `Sources/CondenserKit/RecordsStore.swift` | 同款 `setFeedback`（收藏里也能改标签） |
| `Sources/CondenserKit/NewContentChecker.swift` | `feed` 作用域（与 timeline 的过滤参数必须一致） |
| `Tests/CondenserKitTests/XSourceTests.swift` | 新建：模型解码 12 + 卡片文本 8 + 资源 URL 2 + feed/反馈 5 |
| `Tests/CondenserKitTests/APIClientTests.swift` | 新增 feed query 与反馈端点 2 条（走 MockURLProtocol 的必须待在同一个 `.serialized` 套件里） |
| `Tests/CondenserKitTests/TimelineStoreTests.swift` | StubAPI 跟进协议变化 + 记录反馈调用 |
| `Tests/CondenserKitTests/Fixtures/{timeline_page_x,x_shapes,x_record}.json` | 新建：真实后端 JSON |

### App

| 文件 | 改动 |
|---|---|
| `Condenser/UI/XCard.swift` | 新建：`XGlyph` / `XAvatarView` / `XCard` / `XArticleCard` / `XQuoteCard` / `XMediaView` / `XMediaThumb` / `XVerdictBadge` / `XFeedbackButtons` |
| `Condenser/UI/XDetailSheet.swift` | 新建：全文 + 媒体 + 引用推 + 互动数 + 反馈行 + 判定证据（中文）+ 发布/抓取时间 + 打开原推/主页；`XVerdictNeighborRow` |
| `Condenser/UI/MessageListView.swift` | 卡片与详情 sheet 分发接上 X；`setFeedback`；推文图片查看器入口 |
| `Condenser/UI/SavedScreen.swift` | 同上（收藏视图） |
| `Condenser/UI/SubscriptionsScreen.swift` | `SubDestination.xFeed` + X 行（For You 用 `XGlyph`、关注人用头像）+ `XFeedTimelineScreen`；`scrollToSource`（走查用） |
| `Condenser/UI/ImageViewerScreen.swift` | `ImageViewerItem` 泛化成 `ViewerPhoto`（`.telegram(cid,mid)` / `.proxied(url)`）+ 两个便捷 init |
| `Condenser/UI/MainView.swift` | debug 路由 `x[/<feed>]`、`detail/x/<feed>[/<id>]`、`tab/subs/<source>`；debug 详情 sheet 认 X |
| `Condenser/UI/MessageCard.swift` | `TruncatableText` 解除 private，TG / X 共用 |
| `Condenser/Services/ReaderSession.swift` | `makeXStore(feed:)`、`xSubs` |

### 文档与工具

| 文件 | 改动 |
|---|---|
| `AGENTS.md` | iOS 段落补 Phase 5；Phase 2 的「iOS 空窗」警告改为已关闭；Phase 3/4 里「iOS 顺延」的说法更新；X 计划状态补 Phase 5 |
| `ios/AGENTS.md` | 顶部 X 段落；debug 路由表补三条新路由与「模拟器收不到合成手势」的原因 |
| `kb/plans/2026-07-24-x-source-local-probe.md` | Phase 5 标完成 + 实现纪要；未决问题补第 6 条的 iOS 分工与新的第 7 条（iOS 只读） |
| `tmp/make_ios_fixtures.py` | 新增 `make_x()` 与 `x` 子命令（只重生成 X fixture，不 churn 既有的） |

## 注意事项

- **卡片的纯文本逻辑要放 Kit，不放 View**。`bodyText`（剥 bird 的 `RT @orig:` 前缀、丢掉与
  长文标题重复的正文）、`displayName` 回落链、URL 拼装这些都是会出错的分支逻辑，放在
  `XTweet` 上才进得了 `swift test`。这条其实是 `ios/AGENTS.md` 既有的分层规则，X 只是把它的
  收益放大了——bird 的两个上游怪癖全靠这里吸收。
- **一个映射只能有一个实现**。「卡片上点了第 i 张（含视频）→ 查看器里的第几张（只有图片）」
  在 timeline 和收藏页各写了一遍，写第二遍时就已经忘了跳过视频。收进
  `XTweet.photoIndex(forDisplayed:)` 并让 `XMediaView` 直接收 `displayedMedia`（不再二次
  过滤），两套下标才由一个地方对齐。
- **未知枚举值降级，而不是让整页解码失败**。`XVerdict` / `ItemFeedback` 都有 `other` 兜底
  （沿用 `ReactionCount.Kind` 的先例）。后端先长出新判定值时，旧 app 少画一个徽标而不是白屏。
- **`feed` 作用域是 X 特有的形状**。X 是第一个「一个信源多个 feed」的源（HN 只有 `front`，
  TG 用 `channel_id`），Kit 里 `TimelineStore` / `NewContentChecker` / 两个 timeline 端点都要
  带上它；`NewContentChecker` 的过滤参数必须与它盯着的 store 完全一致，否则轮询会答非所问。
- **MockURLProtocol 是静态 handler，跨套件会打架**。新建的 `.serialized` 套件仍然会和既有的
  `APIClient` 套件并行跑，导致两边互相抢 handler（表现为莫名其妙的 `keyNotFound`）。凡是走
  网络的断言都得放进同一个 `.serialized` 套件里；纯 URL 拼装的断言不碰 handler，可以另开套件。
- **走查手段的限制值得记下来**：本机模拟器窗口拿不到 `System Events` 句柄（`window 1` 报
  invalid index），`cliclick` 也就无从下手，所以点击类交互没法真点。写入路径拆成两段验证——
  按钮→store→API 由 Kit 行为测试盯，API→服务端→读回渲染用 app 同一个 device token curl 打标
  后重启 app 看渲染，走查结束把 dev DB 改回原样。导航一律靠启动环境变量深链，这次为此补了
  `tab/subs/<source>`（订阅列表已经一屏放不下）和 `detail/x/<feed>[/<id>]`（X 条目要单独走一次
  网络查——For You 根本不在 `reader.timeline.items` 里）。
- **fixture 生成脚本要支持只重生成一部分**。`tmp/make_ios_fixtures.py` 全量跑会重写既有
  fixture，而老测试对它们断言了确切条数；加个 `x` 子命令就避开了这次改动去 churn 别人的断言。

## 遗留问题

- ⚠️ **dev DB 里原有的 4 条 X 标注在走查期间消失了**：23:12 的截图里还看得到 👎 高亮，23:20
  查表已空。不是本次改动造成的——代码里删 `item_feedback` 只有 `clear_feedback`（DELETE 端点）
  一条路径，iOS 端没有任何点击发生，`delete_saved_item` 不触碰标签表；当时用户的浏览器还开着
  在轮询 dev 后端，最可能是在 web 上手动撤销的。若不是，值得单独查一次。
- **判定阈值仍未标定**（Phase 4 遗留，不因 iOS 落地而改变）：真实标注量太少，生产闸门
  20/20 挡着，攒够后跑 `scripts/x_verdict_backtest.py --sweep` 再定 D_MAX / M / ± 阈值。
- **iOS 上的 X 是只读的**：订阅增删改、probe 状态、判定闸门倒计时都只在 web 的订阅页。这是既有
  约定的延续，不是缺陷，但如果以后想在手机上加订阅，得先破这个约定。
- **推文视频不内嵌播放**（与 TG 一致的 v1 非目标）：只画缩略图 + 播放角标，点了不开查看器，
  要看得去原推。
- dev 后端在本次 session 中挂过一次，我重启的那个进程在收尾时也被停掉了；下次走查前记得先
  `CONDENSER_DB_PATH=tmp/condenser.db uv run uvicorn condenser.app:create_app --factory --reload --reload-dir condenser --port 8792`。

## 相关文档

- [X 信息源：local probe + 反馈判定](../plans/2026-07-24-x-source-local-probe.md) — 本次 session 按此计划实现 Phase 5，并更新了其进展表与实现纪要（计划至此全部完成）
- [X 信息源 Phase 4：Embedding 判定上线](2026-07-25-x-source-phase4-embedding-verdict.md) — 上一个 phase 的 session，本次把它做出来的判定搬上 iOS
- [X 信息源 Phase 1：probe + ingest + 存档](2026-07-24-x-source-phase1-probe-ingest.md) — 数据模型与 bird 输出实测结论的来源
- [iOS 阅读客户端计划](../plans/2026-07-16-ios-reader-app.md) — iOS 端的整体设计依据
