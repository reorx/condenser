import Foundation
import Testing
@testable import CondenserKit

// X 信息源（计划 Phase 5）的 Kit 行为：envelope 解码（fixture 为真实后端 JSON，
// tmp/make_ios_fixtures.py x 生成）、卡片要用的纯文本逻辑、feed 作用域与反馈写入。
// 契约事实来源 frontend/src/lib/types.ts + condenser/items.py:x_payload。

private func loadXFixture(_ name: String) throws -> Data {
    let url = try #require(Bundle.module.url(forResource: "Fixtures/\(name)", withExtension: "json"))
    return try Data(contentsOf: url)
}

private func decodeShapes() throws -> [String: TimelineItem] {
    try JSONDecoder.condenserAPI.decode([String: TimelineItem].self, from: loadXFixture("x_shapes"))
}

@Suite("X 模型解码")
struct XModelsDecodingTests {
    private let decoder = JSONDecoder.condenserAPI

    @Test("timeline_page_x.json：整页 X envelope，key 前缀 x:，payload 与 source 对应")
    func page() throws {
        let page = try decoder.decode(TimelinePage.self, from: loadXFixture("timeline_page_x"))
        #expect(!page.items.isEmpty)
        for item in page.items {
            #expect(item.source == SourceID.x)
            #expect(item.key.hasPrefix("x:"))
            #expect(item.x != nil)
            #expect(item.telegram == nil && item.hn == nil)
        }
    }

    @Test("snowflake id 是字符串（int64 超出 JS 安全整数，后端一律转字符串）")
    func snowflakeIsString() throws {
        let page = try decoder.decode(TimelinePage.self, from: loadXFixture("timeline_page_x"))
        let tweet = try #require(page.items.first?.x)
        #expect(tweet.id.count >= 18)
        #expect(Int64(tweet.id) != nil, "字符串里装的是完整 int64，没有被浮点截断")
        #expect(page.items.first?.key == "x:\(tweet.id)")
    }

    @Test("引用推：内嵌一层，作者/正文/媒体齐全，不单独成条")
    func quote() throws {
        let item = try #require(try decodeShapes()["quote"])
        let quote = try #require(item.x?.quote)
        #expect(!quote.id.isEmpty)
        #expect(quote.authorHandle != nil)
        #expect(quote.text?.isEmpty == false)
    }

    @Test("转推：只有 rt_of_handle（bird 把转推压平成 RT @x: 前缀）")
    func retweet() throws {
        let item = try #require(try decodeShapes()["retweet"])
        let tweet = try #require(item.x)
        #expect(tweet.rtOfHandle?.isEmpty == false)
        #expect(tweet.text?.hasPrefix("RT @") == true)
    }

    @Test("长文：article 只有标题 + 预览片段")
    func article() throws {
        let item = try #require(try decodeShapes()["article"])
        let article = try #require(item.x?.article)
        #expect(article.title?.isEmpty == false)
    }

    @Test("媒体：type + 宽高 + 预览图（前端据此预留占位）")
    func media() throws {
        let item = try #require(try decodeShapes()["media"])
        let media = try #require(item.x?.media)
        #expect(!media.isEmpty)
        let first = try #require(media.first)
        #expect(!first.type.isEmpty)
        #expect(first.thumbnailURL != nil)
    }

    @Test("verdict：三种判定各自解码，meta 带打分与近邻证据")
    func verdicts() throws {
        let shapes = try decodeShapes()
        #expect(shapes["verdict_positive"]?.x?.verdict == .positive)
        #expect(shapes["verdict_negative"]?.x?.verdict == .negative)
        #expect(shapes["verdict_neutral"]?.x?.verdict == .neutral)

        let meta = try #require(shapes["verdict_positive"]?.x?.verdictMeta)
        #expect(meta.score != nil)
        let neighbors = try #require(meta.neighbors)
        #expect(!neighbors.isEmpty)
        #expect(neighbors.allSatisfy { !$0.tweetID.isEmpty && $0.distance >= 0 })
    }

    @Test("feedback 在 envelope 层（源通用），up/down 都能读回")
    func feedback() throws {
        let shapes = try decodeShapes()
        #expect(shapes["feedback_up"]?.feedback == .up)
        #expect(shapes["feedback_down"]?.feedback == .down)
    }

    @Test("feed 决定排序时间：For You 用 first_seen_at，关注人用 created_at")
    func sortTimestamp() throws {
        let shapes = try decodeShapes()
        let foryou = try #require(shapes["foryou"]?.x)
        #expect(foryou.feed == XFeed.foryou)
        #expect(foryou.isForYou)
        #expect(shapes["foryou"]?.datetime == foryou.firstSeenAt)

        let user = try #require(shapes["user"]?.x)
        #expect(!user.isForYou)
        #expect(shapes["user"]?.datetime == user.createdAt)
    }

    @Test("收藏快照：records 里的 X 条目脱离归档表仍可渲染")
    func savedRecord() throws {
        let records = try decoder.decode([TimelineItem].self, from: loadXFixture("x_record"))
        let item = try #require(records.first)
        #expect(item.source == SourceID.x)
        #expect(item.isSaved)
        let tweet = try #require(item.x)
        #expect(!tweet.id.isEmpty)
        #expect(tweet.feed.isEmpty == false)
    }

    @Test("未知 verdict / feedback 值降级而不炸解码（后端先行升级时的前向兼容）")
    func forwardCompatibility() throws {
        let json = #"""
        {"source": "x", "key": "x:1", "datetime": "2026-07-25T10:00:00Z",
         "is_read": false, "is_saved": false, "feedback": "shrug",
         "x": {"id": "1", "author_id": null, "author_handle": "a", "author_name": null,
               "text": "hi", "created_at": null, "first_seen_at": "2026-07-25T10:00:00Z",
               "media": null, "metrics": null, "quote": null, "rt_of_handle": null,
               "reply_to_id": null, "article": null, "feed": "foryou", "feed_kind": "home",
               "verdict": "sideways", "verdict_meta": null}}
        """#
        let item = try decoder.decode(TimelineItem.self, from: Data(json.utf8))
        #expect(item.feedback == .other)
        #expect(item.x?.verdict == .other)
        #expect(item.x?.verdict?.isFinding == false, "看不懂的判定不该画徽标")
    }
}

@Suite("X 卡片文本逻辑")
struct XTweetTextTests {
    /// 卡片正文：转推的 "RT @orig:" 前缀由标题行承载，正文里剥掉
    @Test("转推：正文剥掉 RT 前缀")
    func retweetPrefixStripped() {
        let tweet = makeTweet(text: "RT @colebemis: Pro tip: ask your agent", rtOfHandle: "colebemis")
        #expect(tweet.bodyText == "Pro tip: ask your agent")
    }

    @Test("非转推的正文原样保留（含正文里恰好出现的 RT 字样）")
    func nonRetweetUntouched() {
        let tweet = makeTweet(text: "RT is a bad feature")
        #expect(tweet.bodyText == "RT is a bad feature")
    }

    @Test("长文：text 就是文章标题，正文不重复打印")
    func articleTitleNotDuplicated() {
        let tweet = makeTweet(
            text: "Superrepos and why Claude Code is the best worktree manager",
            article: XArticle(title: "Superrepos and why Claude Code is the best worktree manager",
                              previewText: "..."))
        #expect(tweet.bodyText == nil)
    }

    @Test("空正文 → nil（只有媒体的推）")
    func emptyBody() {
        #expect(makeTweet(text: nil).bodyText == nil)
        #expect(makeTweet(text: "  ").bodyText == nil)
    }

    @Test("展示名回落链：name → @handle → Unknown")
    func displayName() {
        #expect(makeTweet(authorHandle: "jonny", authorName: "Jonny").displayName == "Jonny")
        #expect(makeTweet(authorHandle: "jonny", authorName: nil).displayName == "@jonny")
        #expect(makeTweet(authorHandle: nil, authorName: nil).displayName == "Unknown")
    }

    @Test("原推 / 主页链接")
    func urls() {
        let tweet = makeTweet(id: "2080466972039622848", authorHandle: "jonnygravity")
        #expect(tweet.tweetURL.absoluteString == "https://x.com/jonnygravity/status/2080466972039622848")
        #expect(tweet.profileURL?.absoluteString == "https://x.com/jonnygravity")
        // handle 缺失时 x.com 仍能用 /i/status/<id> 打开原推
        #expect(makeTweet(id: "42", authorHandle: nil).tweetURL.absoluteString
            == "https://x.com/i/status/42")
        #expect(makeTweet(authorHandle: nil).profileURL == nil)
    }

    @Test("图片集合：视频只留缩略图不进查看器")
    func photos() {
        let tweet = makeTweet(media: [makePhoto(), makeVideo()])
        #expect(tweet.photos.count == 1)
        #expect(makeVideo().isVideo)
        #expect(!makePhoto().isVideo)
        #expect(abs((makePhoto().aspectRatio ?? 0) - 1.5) < 0.001)
    }

    /// 卡片下标含视频、查看器下标不含——视频排在前面时直接拿 index 会错位
    @Test("查看器下标：跳过视频重新对齐，点视频不开查看器")
    func viewerIndexMapping() {
        let tweet = makeTweet(media: [makeVideo(), makePhoto("a"), makePhoto("b")])
        #expect(tweet.photoIndex(forDisplayed: 0) == nil, "第 0 张是视频")
        #expect(tweet.photoIndex(forDisplayed: 1) == 0)
        #expect(tweet.photoIndex(forDisplayed: 2) == 1)
        #expect(tweet.photoIndex(forDisplayed: 9) == nil, "越界不崩")
    }

    /// 没有缩略图的媒体两边都不画，两套下标才对得上
    @Test("无缩略图的媒体不参与展示")
    func mediaWithoutThumbnail() {
        let blank = XMediaItem(
            type: "photo", url: nil, previewUrl: nil, videoUrl: nil,
            width: nil, height: nil, durationMs: nil)
        let tweet = makeTweet(media: [blank, makePhoto()])
        #expect(tweet.displayedMedia.count == 1)
        #expect(tweet.photoIndex(forDisplayed: 0) == 0)
    }
}

private func makePhoto(_ name: String = "a") -> XMediaItem {
    XMediaItem(
        type: "photo", url: "https://pbs.twimg.com/\(name).jpg", previewUrl: nil,
        videoUrl: nil, width: 1200, height: 800, durationMs: nil)
}

private func makeVideo() -> XMediaItem {
    XMediaItem(
        type: "video", url: "https://pbs.twimg.com/thumb.jpg", previewUrl: nil,
        videoUrl: "https://video.twimg.com/v.mp4", width: 1920, height: 1080, durationMs: 30_000)
}

/// 测试用 XTweet 构造（默认最小可用形态）
func makeTweet(
    id: String = "2080000000000000000",
    text: String? = "hello",
    authorHandle: String? = "someone",
    authorName: String? = "Some One",
    media: [XMediaItem]? = nil,
    quote: XQuote? = nil,
    rtOfHandle: String? = nil,
    article: XArticle? = nil,
    feed: String = XFeed.foryou,
    feedKind: String = "home",
    verdict: XVerdict? = nil,
    verdictMeta: XVerdictMeta? = nil
) -> XTweet {
    XTweet(
        id: id, authorID: nil, authorHandle: authorHandle, authorName: authorName,
        text: text, createdAt: Date(timeIntervalSince1970: 1_784_000_000),
        firstSeenAt: Date(timeIntervalSince1970: 1_784_000_100),
        media: media, metrics: nil, quote: quote, rtOfHandle: rtOfHandle,
        replyToID: nil, article: article, feed: feed, feedKind: feedKind,
        verdict: verdict, verdictMeta: verdictMeta)
}

/// X envelope：key = "x:{tweet id}"
func makeXItem(
    id: String = "2080000000000000000", isRead: Bool = false, isSaved: Bool = false,
    feedback: ItemFeedback? = nil, feed: String = XFeed.foryou
) -> TimelineItem {
    let tweet = makeTweet(id: id, feed: feed, feedKind: feed == XFeed.foryou ? "home" : "user")
    return TimelineItem(
        source: SourceID.x, key: "x:\(id)", datetime: tweet.firstSeenAt ?? Date(),
        isRead: isRead, isSaved: isSaved, feedback: feedback, x: tweet)
}

@MainActor
@Suite("X feed 作用域与反馈")
struct XStoreTests {
    @Test("feed 作用域透传到 timeline 与 /timeline/new（For You 只有专属入口）")
    func feedScope() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeXItem()], head: "h1"))]
        api.newResults = [.success(TimelineNew(count: 2, items: []))]
        let store = TimelineStore(api: api, source: SourceID.x, feed: XFeed.foryou)
        await store.loadInitial()
        #expect(api.timelineCalls.first?.source == SourceID.x)
        #expect(api.timelineCalls.first?.feed == XFeed.foryou)

        let checker = NewContentChecker(
            api: api, source: SourceID.x, feed: XFeed.foryou) { store.headCursor }
        #expect(await checker.check() == 2)
        #expect(api.newCalls.first?.feed == XFeed.foryou)
    }

    @Test("打标：乐观置位 + 调用 POST /api/feedback")
    func setFeedback() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeXItem(id: "1"), makeXItem(id: "2")]))]
        let store = TimelineStore(api: api)
        await store.loadInitial()

        await store.setFeedback(store.items[0], .up)
        #expect(store.items[0].feedback == .up)
        #expect(store.items[1].feedback == nil, "只影响被标注的那一条")
        #expect(api.feedbackCalls.map(\.verdict) == [.up])
        #expect(api.feedbackCalls.first?.key == "x:1")
    }

    @Test("再点同一侧 = 撤销（DELETE），换一侧 = 改正（一条目仍只有一个标签）")
    func toggleAndSwitch() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeXItem(id: "1")]))]
        let store = TimelineStore(api: api)
        await store.loadInitial()

        await store.setFeedback(store.items[0], .up)
        await store.setFeedback(store.items[0], .down)
        #expect(store.items[0].feedback == .down)
        #expect(api.feedbackCalls.map(\.verdict) == [.up, .down])

        await store.setFeedback(store.items[0], .down)
        #expect(store.items[0].feedback == nil)
        #expect(api.clearFeedbackCalls == ["x:1"])
    }

    @Test("失败回滚到点击前的标签")
    func rollback() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeXItem(id: "1", feedback: .up)]))]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        api.feedbackError = APIError.http(status: 500, detail: "boom")

        await store.setFeedback(store.items[0], .down)
        #expect(store.items[0].feedback == .up)
        #expect(store.error == "boom")
    }

    @Test("收藏列表同样可改标签（标签是活状态，不进快照）")
    func recordsFeedback() async {
        let api = StubAPI()
        api.recordsResults = [.success([makeXItem(id: "1", isSaved: true, feedback: .down)])]
        let store = RecordsStore(api: api)
        await store.loadInitial()

        await store.setFeedback(store.items[0], .up)
        #expect(store.items[0].feedback == .up)
        #expect(api.feedbackCalls.map(\.key) == ["x:1"])
    }
}

// 走网络的 X 端点断言（反馈 POST/DELETE）在 APIClientTests 里——MockURLProtocol
// 是静态 handler，所有用到它的测试必须待在同一个 .serialized 套件内。

@Suite("X 认证资源 URL")
struct XResourceURLTests {
    private func makeClient() -> APIClient {
        APIClient(baseURL: URL(string: "https://example.com")!, token: "tok_test")
    }

    @Test("作者头像走后端 unavatar 代理（浏览/阅读推文不直连 X）")
    func avatarURL() {
        #expect(makeClient().xAvatarURL(handle: "novoreorx").absoluteString
            == "https://example.com/api/x/avatar/novoreorx")
    }

    @Test("推文媒体走 /api/preview/image 代理，原始 URL 进 query")
    func mediaProxy() throws {
        let url = makeClient().proxiedImageURL("https://pbs.twimg.com/media/a b.jpg?x=1")
        let comps = try #require(URLComponents(url: url, resolvingAgainstBaseURL: false))
        #expect(comps.path == "/api/preview/image")
        #expect(comps.queryItems?.first(where: { $0.name == "url" })?.value
            == "https://pbs.twimg.com/media/a b.jpg?x=1")
    }
}
