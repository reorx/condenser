import Foundation
import Testing
@testable import CondenserKit

// Models 解码回归：fixture 为真实后端 JSON（tmp/make_ios_fixtures.py 从 dev DB 生成）。
// 字段事实来源 frontend/src/lib/types.ts。

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

    @Test("timeline_page.json：整页解码，游标与条目字段齐全")
    func timelinePage() throws {
        let page = try decoder.decode(TimelinePage.self, from: loadFixture("timeline_page"))
        #expect(page.items.count == 30)
        #expect(page.nextCursor != nil)
        #expect(page.headCursor != nil)

        let first = try #require(page.items.first)
        #expect(first.id == 18249)
        #expect(first.channelID == 1_283_701_973)
        #expect(first.isAlbum)
        #expect(first.isEdited)
        #expect(first.editDate != nil)
        #expect(first.mediaItems.count >= 2)
        #expect(first.mediaItems[0].width == 2560)
        #expect(first.mediaItems[0].height == 1920)
        #expect(first.text?.contains("广州") == true)
    }

    @Test("message_shapes.json：转发与网页预览形态")
    func messageShapes() throws {
        let shapes = try decoder.decode(
            [String: DisplayMessage].self, from: loadFixture("message_shapes"))

        let fwd = try #require(shapes["forward"])
        #expect(fwd.isForwarded)
        let info = try #require(fwd.forwardInfo)
        #expect(info.fromChannelName == "harukachan eats delicious meals")
        #expect(info.postAuthor == "nowano")
        #expect(info.originalDate != nil)

        let webpageMsg = try #require(shapes["webpage"])
        let wp = try #require(webpageMsg.webpage)
        #expect(wp.siteName == "Nowledge Labs")
        #expect(wp.url?.hasPrefix("https://") == true)
    }

    @Test("subscriptions.json 解码")
    func subscriptions() throws {
        let subs = try decoder.decode([Subscription].self, from: loadFixture("subscriptions"))
        #expect(!subs.isEmpty)
        let first = try #require(subs.first)
        #expect(first.channelID == 1_037_603_752)
        #expect(first.title == "KAIX.IN")
        #expect(first.username == "kaix_in")
        #expect(first.enabled)
    }

    @Test("timeline_new.json 解码")
    func timelineNew() throws {
        let new = try decoder.decode(TimelineNew.self, from: loadFixture("timeline_new"))
        #expect(new.count == 0)
        #expect(new.items.isEmpty)
    }

    @Test("MsgRef 编码为 snake_case（POST /api/read body）")
    func msgRefEncoding() throws {
        let data = try JSONEncoder.condenserAPI.encode(MsgRef(channelID: 1, messageID: 2))
        let obj = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Int])
        #expect(obj == ["channel_id": 1, "message_id": 2])
    }

    @Test("DisplayMessage.unitKey 唯一标识跨频道消息")
    func unitKey() throws {
        let page = try decoder.decode(TimelinePage.self, from: loadFixture("timeline_page"))
        let keys = page.items.map(\.unitKey)
        #expect(Set(keys).count == keys.count)
    }
}
