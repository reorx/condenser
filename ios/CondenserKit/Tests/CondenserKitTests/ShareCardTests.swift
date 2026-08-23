import Foundation
import Testing
@testable import CondenserKit

// 「生成图片并分享」（计划 kb/plans/2026-08-23-ios-share-image.md）的内容取舍。
// 这一层决定的是「哪些东西会跟着图发给别人」，所以每条断言都是一次隐私/礼貌上的
// 承诺，而不只是布局：X 的判定与反馈不进图、TG 的实时统计不进图、RSS 用全文而不是
// 列表摘录。fixture 是真实后端 JSON，与其它 Kit 测试共用。

private func loadShareFixture(_ name: String) throws -> Data {
    let url = try #require(Bundle.module.url(forResource: "Fixtures/\(name)", withExtension: "json"))
    return try Data(contentsOf: url)
}

private func shapes(_ name: String) throws -> [String: TimelineItem] {
    try JSONDecoder.condenserAPI.decode([String: TimelineItem].self, from: loadShareFixture(name))
}

/// message_shapes.json 是 envelope 之前留下的 fixture（裸 DisplayMessage），
/// 这里补上外层信封——分享卡片的入口收的是 item，不是 payload
private func tgShapes() throws -> [String: TimelineItem] {
    let messages = try JSONDecoder.condenserAPI
        .decode([String: DisplayMessage].self, from: loadShareFixture("message_shapes"))
    return messages.mapValues {
        TimelineItem(
            source: SourceID.telegram, key: "tg:\($0.channelID):\($0.id)", datetime: $0.date,
            isRead: false, isSaved: false, telegram: $0)
    }
}

private extension ShareCard {
    /// 卡片上所有会被读到的文字，用来断言某样东西「没有跟着发出去」
    var allText: String {
        var parts = [title, subtitle, headline, footnote].compactMap { $0 }
        for block in blocks {
            switch block {
            case let .text(text): parts.append(text)
            case let .summary(text): parts.append(text)
            case let .note(text): parts.append(text)
            case let .fileChip(text): parts.append(text)
            case let .quote(quote): parts.append(contentsOf: [quote.name, quote.text].compactMap { $0 })
            case let .linkCard(card):
                parts.append(contentsOf: [card.site, card.title, card.description].compactMap { $0 })
            case .image, .imageGrid: continue
            }
        }
        return parts.joined(separator: "\n")
    }

    var blockKinds: [String] {
        blocks.map { block in
            switch block {
            case .text: "text"
            case .image: "image"
            case .imageGrid: "imageGrid"
            case .summary: "summary"
            case .quote: "quote"
            case .linkCard: "linkCard"
            case .fileChip: "fileChip"
            case .note: "note"
            }
        }
    }
}

@Suite("分享卡片 · Telegram")
struct TelegramShareCardTests {
    @Test("头部是频道名 + 时间，正文与图片各成一块")
    func mediaMessage() throws {
        let item = try #require(try tgShapes()["media"])
        let card = try #require(ShareCard.build(item: item, channelTitle: "某频道"))
        #expect(card.source == SourceID.telegram)
        #expect(card.title == "某频道")
        #expect(card.subtitle?.isEmpty == false)
        #expect(card.headline == nil, "TG 消息没有标题这回事")
        #expect(card.blockKinds.contains("image"))
        if let text = item.telegram?.text, !text.isEmpty {
            #expect(card.blocks.contains(.text(text)), "正文原样进图，不截断")
        }
    }

    @Test("相册：每张图一块，顺序与消息一致（不并成方格，照抽屉的样子）")
    func album() throws {
        let item = try #require(try tgShapes()["album"])
        let message = try #require(item.telegram)
        let photos = message.mediaItems.filter { $0.mediaType == "photo" && $0.hasMedia }
        let card = try #require(ShareCard.build(item: item, channelTitle: "某频道"))
        #expect(photos.count > 1)
        #expect(card.blockKinds.filter { $0 == "image" }.count == photos.count)
        #expect(!card.blockKinds.contains("imageGrid"))
    }

    @Test("转发：主体是来源，第二行标 Forwarded by 订阅频道")
    func forwarded() throws {
        let item = try #require(try tgShapes()["forward"])
        let source = try #require(item.telegram?.forwardSource)
        let card = try #require(ShareCard.build(item: item, channelTitle: "我的频道"))
        #expect(card.title == source.name)
        #expect(card.subtitle?.contains("Forwarded by 我的频道") == true)
    }

    @Test("网页预览卡跟着进图——TG 消息经常只有一句话加一个链接")
    func webpage() throws {
        let item = try #require(try tgShapes()["webpage"])
        let webpage = try #require(item.telegram?.webpage)
        let card = try #require(ShareCard.build(item: item, channelTitle: "某频道"))
        #expect(card.blockKinds.contains("linkCard"))
        if let title = webpage.title {
            #expect(card.allText.contains(title))
        }
    }

    @Test("频道名拿不到时退回「频道 <id>」，不画一个空标题")
    func missingChannelTitle() throws {
        let item = try #require(try tgShapes()["media"])
        let message = try #require(item.telegram)
        let card = try #require(ShareCard.build(item: item))
        #expect(card.title == "频道 \(message.channelID)")
    }
}

@Suite("分享卡片 · Hacker News")
struct HnShareCardTests {
    @Test("标题是主角，分数 / 评论数 / 域名进元信息行")
    func linkStory() throws {
        let item = try #require(try shapes("hn_shapes")["link"])
        let story = try #require(item.hn)
        let card = try #require(ShareCard.build(item: item))
        #expect(card.headline == story.title)
        #expect(card.meta.contains(.score(story.score)))
        #expect(card.meta.contains(.comments(story.commentsCount)))
        #expect(card.meta.contains(.text(try #require(story.domain))))
        #expect(card.avatar == .glyph(.hn))
    }

    @Test("self-post 的 HTML 正文转成纯文本（图里没有可点的 <a>）")
    func selfPost() throws {
        let item = try #require(try shapes("hn_shapes")["self"])
        let story = try #require(item.hn)
        let card = try #require(ShareCard.build(item: item))
        let text = try #require(card.blocks.compactMap { block -> String? in
            if case let .text(text) = block { return text }
            return nil
        }.first)
        #expect(text == hnPlainText(fromHTML: try #require(story.text)))
        #expect(!text.contains("<a "))
    }

    @Test("ingest 预取到的链接预览进图；描述为空串时不占一行")
    func preview() throws {
        let item = try #require(try shapes("hn_shapes")["preview"])
        let card = try #require(ShareCard.build(item: item))
        let linkCard = try #require(card.blocks.compactMap { block -> ShareLinkCard? in
            if case let .linkCard(card) = block { return card }
            return nil
        }.first)
        #expect(linkCard.title?.isEmpty == false)
        #expect(linkCard.description == nil, "后端给的是空串，不是描述")
    }

    @Test("落款用域名——头部已经印了提交时间，再印一遍是浪费")
    func footnoteIsTheDomain() throws {
        let item = try #require(try shapes("hn_shapes")["link"])
        #expect(ShareCard.build(item: item)?.footnote == item.hn?.domain)
    }
}

@Suite("分享卡片 · X")
struct XShareCardTests {
    @Test("作者 + 正文 + 媒体 + 互动数：转/赞/回复在元信息行里")
    func mediaTweet() throws {
        let item = try #require(try shapes("x_shapes")["media"])
        let tweet = try #require(item.x)
        let metrics = try #require(tweet.metrics)
        let card = try #require(ShareCard.build(item: item))
        #expect(card.title == tweet.displayName)
        #expect(card.subtitle?.contains("@\(try #require(tweet.authorHandle))") == true)
        #expect(card.meta == [.likes(metrics.likeCount), .retweets(metrics.retweetCount),
                              .replies(metrics.replyCount)])
        #expect(card.blockKinds == ["text", "image"])
    }

    @Test("判定不进图：同一条推文带不带 verdict，卡片一模一样")
    func verdictNeverTravels() throws {
        let item = try #require(try shapes("x_shapes")["verdict_positive"])
        let tweet = try #require(item.x)
        #expect(tweet.verdict != nil, "fixture 本身带判定，否则这条测什么都没测")
        var stripped = item
        stripped.x = XTweet(
            id: tweet.id, authorID: tweet.authorID, authorHandle: tweet.authorHandle,
            authorName: tweet.authorName, text: tweet.text, createdAt: tweet.createdAt,
            firstSeenAt: tweet.firstSeenAt, media: tweet.media, metrics: tweet.metrics,
            quote: tweet.quote, rtOfHandle: tweet.rtOfHandle, replyToID: tweet.replyToID,
            article: tweet.article, urls: tweet.urls, feed: tweet.feed, feedKind: tweet.feedKind,
            verdict: nil, verdictMeta: nil)
        #expect(ShareCard.build(item: item) == ShareCard.build(item: stripped))
    }

    @Test("反馈不进图：读者的拇指是他与机器之间的事")
    func feedbackNeverTravels() throws {
        let item = try #require(try shapes("x_shapes")["feedback_down"])
        #expect(item.feedback == .down, "fixture 本身带反馈")
        var stripped = item
        stripped.feedback = nil
        stripped.feedbackReason = nil
        #expect(ShareCard.build(item: item) == ShareCard.build(item: stripped))
    }

    @Test("引用推整块带走（作者 + 文字 + 一张缩略图）")
    func quoted() throws {
        let item = try #require(try shapes("x_shapes")["quote"])
        let quote = try #require(item.x?.quote)
        let card = try #require(ShareCard.build(item: item))
        let block = try #require(card.blocks.compactMap { block -> ShareQuote? in
            if case let .quote(quote) = block { return quote }
            return nil
        }.first)
        #expect(block.name == quote.displayName)
        #expect(block.text == quote.text)
    }

    @Test("转推：RT 前缀改由一行小字承载，与卡片同一条规则")
    func retweet() throws {
        let item = try #require(try shapes("x_shapes")["retweet"])
        let handle = try #require(item.x?.rtOfHandle)
        let card = try #require(ShareCard.build(item: item))
        #expect(card.blocks.first == .note("转推自 @\(handle)"))
        #expect(card.allText.contains("RT @\(handle):") == false, "前缀不重复出现在正文里")
    }

    @Test("长文推：bird 只给标题 + 预览，按链接卡画，不假装有正文")
    func article() throws {
        let item = try #require(try shapes("x_shapes")["article"])
        let article = try #require(item.x?.article)
        let card = try #require(ShareCard.build(item: item))
        let block = try #require(card.blocks.compactMap { block -> ShareLinkCard? in
            if case let .linkCard(card) = block { return card }
            return nil
        }.first)
        #expect(block.title == article.title)
        #expect(block.description == article.previewText)
    }
}

@Suite("分享卡片 · RSS")
struct RssShareCardTests {
    private func entry(
        excerpt: String?, content: String? = nil, summary: String? = nil
    ) -> RssEntry {
        RssEntry(
            id: 7, guid: nil, feedURL: "https://example.com/feed", feedTitle: "示例博客",
            title: "标题", link: "https://example.com/a", author: nil,
            contentExcerpt: excerpt, content: content, summary: summary,
            publishedAt: Date(timeIntervalSince1970: 1_700_000_000),
            firstSeenAt: Date(timeIntervalSince1970: 1_700_000_000),
            sortAt: Date(timeIntervalSince1970: 1_700_000_000))
    }

    private func item(_ entry: RssEntry) -> TimelineItem {
        TimelineItem(
            source: SourceID.rss, key: "rss:\(entry.id)",
            datetime: entry.firstSeenAt, isRead: false, isSaved: false, rss: entry)
    }

    @Test("正文用详情取回的全文，不是列表里那 500 字摘录")
    func usesTheArticleNotTheExcerpt() throws {
        let entry = entry(excerpt: "开头 500 字…")
        let blocks: [RssBlock] = [.text("第一段"), .image(RssImage(src: "https://example.com/a.png")),
                                  .text("第二段")]
        let card = try #require(ShareCard.build(item: item(entry), articleBlocks: blocks))
        #expect(card.blockKinds == ["text", "image", "text"])
        #expect(card.allText.contains("第二段"))
        #expect(!card.allText.contains("开头 500 字"))
    }

    @Test("全文没到手（取失败）时退回摘录——短，但分享得出去")
    func fallsBackToTheExcerpt() throws {
        let card = try #require(ShareCard.build(item: item(entry(excerpt: "开头 500 字…"))))
        #expect(card.blocks == [.text("开头 500 字…")])
    }

    @Test("AI 摘要作为标注过的块排在正文前，不混进正文")
    func summaryIsLabeledAndFirst() throws {
        let entry = entry(excerpt: nil, summary: "三句话摘要")
        let card = try #require(ShareCard.build(
            item: item(entry), articleBlocks: [.text("全文")]))
        #expect(card.blocks == [.summary("三句话摘要"), .text("全文")])
    }

    @Test("标题 + feed 名 + 发布时间都在头部，落款是原文域名")
    func header() throws {
        let card = try #require(ShareCard.build(item: item(entry(excerpt: "x"))))
        #expect(card.title == "示例博客")
        #expect(card.headline == "标题")
        #expect(card.subtitle?.contains("发布于") == true)
        #expect(card.footnote == "example.com")
        #expect(card.avatar == .glyph(.rss))
    }

    @Test("真实全文 fixture：正文块与图片块都进图")
    func realArticle() throws {
        let full = try JSONDecoder.condenserAPI
            .decode(TimelineItem.self, from: loadShareFixture("rss_article"))
        let entry = try #require(full.rss)
        let blocks = rssBlocks(fromHTML: try #require(entry.content), baseURL: entry.articleURL)
        let card = try #require(ShareCard.build(item: full, articleBlocks: blocks))
        #expect(card.blockKinds.contains("text"))
        #expect(card.allText.count > (entry.contentExcerpt?.count ?? 0))
    }
}

@Suite("分享卡片 · 图片收集")
struct ShareCardImageTests {
    @Test("TG：频道头像 + 正文图 + 预览图，全部要预载")
    func telegram() throws {
        let item = try #require(try tgShapes()["media"])
        let message = try #require(item.telegram)
        let card = try #require(ShareCard.build(item: item, channelTitle: "某频道"))
        let refs = card.imageRefs
        #expect(refs.first?.source == .channelAvatar(message.channelID))
        #expect(refs.contains { if case .tgMedia = $0.source { return true } else { return false } })
        #expect(refs.allSatisfy { ref in
            if case let .tgMedia(_, _, thumb) = ref.source { return !thumb } else { return true }
        }, "正文图取原图：缩略图放大到 1200px 是糊的")
    }

    @Test("X：作者头像 + 媒体 + 引用推的头像与缩略图")
    func x() throws {
        let item = try #require(try shapes("x_shapes")["quote"])
        let tweet = try #require(item.x)
        let handle = try #require(tweet.authorHandle)
        let card = try #require(ShareCard.build(item: item))
        let refs = card.imageRefs
        #expect(refs.contains { $0.source == .xAvatar(handle: handle) })
        #expect(refs.contains { if case .proxied = $0.source { return true } else { return false } },
                "推文媒体走服务端代理，客户端不直连 X")
    }

    @Test("同一张图出现两次只预载一次")
    func deduplicates() throws {
        let image = RssImage(src: "https://example.com/same.png")
        let entry = RssEntry(
            id: 1, guid: nil, feedURL: "https://e.com/f", feedTitle: nil, title: "t",
            link: nil, author: nil, contentExcerpt: nil, content: nil, summary: nil,
            publishedAt: nil, firstSeenAt: Date(timeIntervalSince1970: 0), sortAt: nil)
        let item = TimelineItem(
            source: SourceID.rss, key: "rss:1", datetime: Date(timeIntervalSince1970: 0),
            isRead: false, isSaved: false, rss: entry)
        let card = try #require(ShareCard.build(
            item: item, articleBlocks: [.image(image), .text("中间"), .image(image)]))
        #expect(card.blockKinds == ["image", "text", "image"], "版面上还是两张")
        #expect(card.imageRefs.count == 1, "但只下载一次")
    }

    @Test("图片数封顶：超出的渲染成占位块，不把一次点击拖成一分钟")
    func caps() throws {
        let entry = RssEntry(
            id: 1, guid: nil, feedURL: "https://e.com/f", feedTitle: nil, title: "t",
            link: nil, author: nil, contentExcerpt: nil, content: nil, summary: nil,
            publishedAt: nil, firstSeenAt: Date(timeIntervalSince1970: 0), sortAt: nil)
        let item = TimelineItem(
            source: SourceID.rss, key: "rss:1", datetime: Date(timeIntervalSince1970: 0),
            isRead: false, isSaved: false, rss: entry)
        let many = (0..<(ShareCard.maxImages + 10)).map {
            RssBlock.image(RssImage(src: "https://example.com/\($0).png"))
        }
        let card = try #require(ShareCard.build(item: item, articleBlocks: many))
        #expect(card.blocks.count == many.count, "全文一张不少地画")
        #expect(card.imageRefs.count == ShareCard.maxImages)
    }

    @Test("文件名带 item key，接收端看到的不是 IMG_0001")
    func fileName() throws {
        let item = try #require(try shapes("x_shapes")["media"])
        let card = try #require(ShareCard.build(item: item))
        #expect(card.fileName == "condenser-x-\(try #require(item.x).id).png")
    }

    @Test("未知信源的 envelope 没有卡片可画")
    func unknownSource() {
        let item = TimelineItem(
            source: "mastodon", key: "m:1", datetime: Date(timeIntervalSince1970: 0),
            isRead: false, isSaved: false)
        #expect(ShareCard.build(item: item) == nil)
    }
}
