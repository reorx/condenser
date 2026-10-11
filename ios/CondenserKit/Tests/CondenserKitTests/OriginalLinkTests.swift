import Foundation
import Testing
@testable import CondenserKit

@Suite("复制条目原始链接")
struct OriginalLinkTests {
    private func fixture<T: Decodable>(_ name: String, as type: T.Type) throws -> T {
        let url = try #require(Bundle.module.url(forResource: "Fixtures/\(name)", withExtension: "json"))
        return try JSONDecoder.condenserAPI.decode(type, from: Data(contentsOf: url))
    }

    @Test("Telegram 复制当前消息链接，无用户名时使用私有频道链接")
    func telegram() throws {
        let messages = try fixture("message_shapes", as: [String: DisplayMessage].self)
        for message in messages.values {
            let item = TimelineItem(source: "telegram", key: "tg:test", datetime: message.date,
                                    isRead: false, isSaved: false, telegram: message)
            #expect(item.originalURL(telegramUsername: "example")?.absoluteString
                    == "https://t.me/example/\(message.id)")
            #expect(item.originalURL()?.absoluteString
                    == "https://t.me/c/\(message.channelID)/\(message.id)")
        }
    }

    @Test("X 复制原始推文链接，不经过 fixup 或阅读代理")
    func x() throws {
        let items = try fixture("x_shapes", as: [String: TimelineItem].self)
        for item in items.values {
            let tweet = try #require(item.x)
            #expect(item.originalURL() == tweet.tweetURL)
            #expect(item.originalURL()?.host() == "x.com")
        }
    }

    @Test("HN 与 RSS 使用原文链接，未知来源没有链接")
    func otherSources() throws {
        for item in try fixture("hn_shapes", as: [String: TimelineItem].self).values {
            #expect(item.originalURL() == item.hn?.primaryURL)
        }
        for item in try fixture("rss_shapes", as: [String: TimelineItem].self).values {
            #expect(item.originalURL() == item.rss?.articleURL)
        }
        let unknown = TimelineItem(source: "future", key: "future:1", datetime: .now,
                                   isRead: false, isSaved: false)
        #expect(unknown.originalURL() == nil)
    }
}
