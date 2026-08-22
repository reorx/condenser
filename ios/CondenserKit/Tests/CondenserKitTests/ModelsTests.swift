import Foundation
import Testing
@testable import CondenserKit

// Models 解码回归：fixture 为真实后端 JSON（tmp/make_ios_fixtures.py 从 dev DB 生成）。
// 字段事实来源 frontend/src/lib/types.ts；多信源契约下条目是 TimelineItem envelope。

private func loadFixture(_ name: String) throws -> Data {
    let url = try #require(Bundle.module.url(forResource: "Fixtures/\(name)", withExtension: "json"))
    return try Data(contentsOf: url)
}

@Suite("API date parsing")
struct APIDateTests {
    @Test("tz-aware（Z / +00:00）与 naive 解析到同一时刻")
    func forms() throws {
        let z = try #require(parseAPIDate("2026-07-16T09:26:05Z"))
        let offset = try #require(parseAPIDate("2026-07-16T09:26:05+00:00"))
        let naive = try #require(parseAPIDate("2026-07-16T09:26:05"))
        #expect(z == offset)
        #expect(z == naive)
        #expect(z.timeIntervalSince1970 == 1_784_193_965)
    }

    @Test("带小数秒也能解析")
    func fractionalSeconds() throws {
        let d = try #require(parseAPIDate("2026-07-16T09:26:05.123456Z"))
        #expect(abs(d.timeIntervalSince1970 - 1_784_193_965.123456) < 0.001)
    }

    @Test("垃圾输入返回 nil")
    func garbage() {
        #expect(parseAPIDate("not a date") == nil)
        #expect(parseAPIDate("") == nil)
    }
}

@Suite("Models decoding")
struct ModelsDecodingTests {
    private let decoder = JSONDecoder.condenserAPI

    @Test("timeline_page.json：envelope 整页解码，key 唯一、payload 与 source 匹配")
    func timelinePage() throws {
        let page = try decoder.decode(TimelinePage.self, from: loadFixture("timeline_page"))
        #expect(page.items.count == 30)
        #expect(page.nextCursor != nil)
        #expect(page.headCursor != nil)

        let keys = page.items.map(\.key)
        #expect(Set(keys).count == keys.count, "item key 全局唯一")
        for item in page.items {
            switch item.source {
            case SourceID.telegram:
                #expect(item.telegram != nil && item.hn == nil)
                #expect(item.key.hasPrefix("tg:"))
            case SourceID.hn:
                #expect(item.hn != nil && item.telegram == nil)
                #expect(item.key.hasPrefix("hn:"))
            default:
                Issue.record("unexpected source \(item.source)")
            }
        }
    }

    @Test("timeline_page_tg.json：TG envelope 与 DisplayMessage 字段")
    func telegramPage() throws {
        let page = try decoder.decode(TimelinePage.self, from: loadFixture("timeline_page_tg"))
        let first = try #require(page.items.first)
        #expect(first.source == SourceID.telegram)
        let msg = try #require(first.telegram)
        #expect(first.key == "tg:\(msg.channelID):\(msg.id)")
        #expect(first.datetime == msg.date)
        #expect(!page.items.isEmpty && page.items.allSatisfy { $0.telegram != nil })
    }

    @Test("timeline_page_hn.json：HnStory 字段与派生 URL")
    func hnPage() throws {
        let page = try decoder.decode(TimelinePage.self, from: loadFixture("timeline_page_hn"))
        let first = try #require(page.items.first)
        #expect(first.source == SourceID.hn)
        let story = try #require(first.hn)
        #expect(first.key == "hn:\(story.id)")
        #expect(story.score >= 0)
        #expect(story.firstSeenAt != nil)
        #expect(story.commentsURL.absoluteString == "https://news.ycombinator.com/item?id=\(story.id)")
        // day_rank 是 query-time 排名，单源页上应存在
        #expect(page.items.contains { $0.hn?.dayRank != nil })
    }

    @Test("hn_shapes.json：链接 / self-post / 预取 preview 三种形态")
    func hnShapes() throws {
        let shapes = try decoder.decode(
            [String: TimelineItem].self, from: loadFixture("hn_shapes"))

        let link = try #require(shapes["link"]?.hn)
        #expect(link.url != nil)
        #expect(link.externalURL != nil)
        #expect(link.primaryURL == link.externalURL)
        #expect(link.domain != nil)

        let selfPost = try #require(shapes["self"]?.hn)
        #expect(selfPost.url == nil)
        #expect(selfPost.externalURL == nil)
        #expect(selfPost.primaryURL == selfPost.commentsURL, "self-post 主链接回落评论页")
        #expect(selfPost.text?.isEmpty == false)

        let preview = try #require(shapes["preview"]?.hn?.preview)
        #expect(preview.title?.isEmpty == false)
        #expect(preview.url.hasPrefix("http"))
    }

    @Test("message_shapes.json：转发与网页预览形态（telegram payload）")
    func messageShapes() throws {
        let shapes = try decoder.decode(
            [String: DisplayMessage].self, from: loadFixture("message_shapes"))

        let fwd = try #require(shapes["forward"])
        #expect(fwd.isForwarded)
        #expect(fwd.forwardInfo != nil)

        let webpageMsg = try #require(shapes["webpage"])
        let wp = try #require(webpageMsg.webpage)
        #expect(wp.url?.hasPrefix("https://") == true)

        let album = try #require(shapes["album"])
        #expect(album.isAlbum)
        #expect(album.mediaItems.count >= 2)
    }

    @Test("sources.json：分组解码，TG channel_id 是 int、HN 是 string")
    func sources() throws {
        let groups = try decoder.decode([SourceGroup].self, from: loadFixture("sources"))
        #expect(groups.map(\.source) == [SourceID.telegram, SourceID.hn])

        let tg = try #require(groups.first?.subscriptions.first)
        #expect(tg.channelID.intValue != nil)

        let hn = try #require(groups.last?.subscriptions.first)
        #expect(hn.channelID == .string("front"))
        #expect(hn.channelID.intValue == nil)
        #expect(hn.name == "Hacker News Front Page")
    }

    @Test("records.json：两种 source 的自包含 envelope")
    func records() throws {
        let items = try decoder.decode([TimelineItem].self, from: loadFixture("records"))
        let tg = try #require(items.first { $0.source == SourceID.telegram })
        #expect(tg.isSaved)
        #expect(tg.telegram?.channel != nil, "TG record 自带 channel 快照")

        let hn = try #require(items.first { $0.source == SourceID.hn })
        #expect(hn.isSaved)
        #expect(hn.hn != nil)
        #expect(hn.hn?.dayRank == nil, "saved 快照不含 query-time 排名")
    }

    @Test("timeline_new.json 解码")
    func timelineNew() throws {
        let new = try decoder.decode(TimelineNew.self, from: loadFixture("timeline_new"))
        #expect(new.count == 0)
        #expect(new.items.isEmpty)
    }

    @Test("SourceID.label 展示名")
    func sourceLabels() {
        #expect(SourceID.label("telegram") == "Telegram")
        #expect(SourceID.label("hn") == "Hacker News")
        #expect(SourceID.label("rss") == "RSS")
        #expect(SourceID.label("mastodon") == "mastodon", "未知信源原样展示")
    }
}
