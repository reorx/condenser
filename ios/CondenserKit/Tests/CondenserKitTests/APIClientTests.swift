import Foundation
import Testing
@testable import CondenserKit

// APIClient 行为：Bearer header、URL/query 组装、错误映射（401 判别）、body 编码。
// MockURLProtocol 是静态 handler，套件串行执行。

@Suite("APIClient", .serialized)
struct APIClientTests {
    private func makeClient() -> APIClient {
        APIClient(
            baseURL: URL(string: "https://example.com")!,
            token: "tok_test",
            configuration: MockURLProtocol.makeSessionConfiguration())
    }

    @Test("timeline：带 Bearer header，参数进 query，nil 参数省略")
    func timelineRequest() async throws {
        let captured = MockURLProtocol.respond(
            status: 200, json: #"{"items": [], "next_cursor": null, "head_cursor": null}"#)
        let page = try await makeClient().timeline(cursor: "abc", unreadOnly: true)
        #expect(page.items.isEmpty)
        #expect(captured.authorization == "Bearer tok_test")
        let comps = URLComponents(url: captured.url!, resolvingAgainstBaseURL: false)!
        #expect(comps.path == "/api/timeline")
        let names = Set(comps.queryItems!.map(\.name))
        #expect(names.contains("cursor") && names.contains("unread_only"))
        #expect(!names.contains("channel_id"))
    }

    @Test("timelineNew：after/channel_id 传参")
    func timelineNewRequest() async throws {
        let captured = MockURLProtocol.respond(status: 200, json: #"{"count": 3, "items": []}"#)
        let new = try await makeClient().timelineNew(after: "cur1", channelID: 42)
        #expect(new.count == 3)
        let comps = URLComponents(url: captured.url!, resolvingAgainstBaseURL: false)!
        #expect(comps.path == "/api/timeline/new")
        #expect(comps.queryItems!.contains(URLQueryItem(name: "after", value: "cur1")))
        #expect(comps.queryItems!.contains(URLQueryItem(name: "channel_id", value: "42")))
    }

    @Test("markRead：POST /api/read，body {items: [...]} snake_case")
    func markReadBody() async throws {
        let captured = MockURLProtocol.respond(status: 200, json: #"{"ok": true}"#)
        try await makeClient().markRead([MsgRef(channelID: 7, messageID: 99)])
        #expect(captured.method == "POST")
        #expect(captured.url?.path() == "/api/read")
        let items = try #require(captured.bodyJSON?["items"] as? [[String: Int]])
        #expect(items == [["channel_id": 7, "message_id": 99]])
    }

    @Test("401 → APIError.unauthorized")
    func unauthorized() async throws {
        _ = MockURLProtocol.respond(status: 401, json: #"{"detail": "unauthorized"}"#)
        await #expect(throws: APIError.unauthorized) {
            _ = try await makeClient().subscriptions()
        }
    }

    @Test("非 2xx 携带后端 detail")
    func httpErrorDetail() async throws {
        _ = MockURLProtocol.respond(status: 503, json: #"{"detail": "telegram not connected"}"#)
        await #expect(throws: APIError.http(status: 503, detail: "telegram not connected")) {
            _ = try await makeClient().subscriptions()
        }
    }

    @Test("records 的 save/delete：方法与路径")
    func recordEndpoints() async throws {
        var captured = MockURLProtocol.respond(status: 200, json: #"{"ok": true}"#)
        try await makeClient().saveRecord(MsgRef(channelID: 1, messageID: 2))
        #expect(captured.method == "POST")
        #expect(captured.url?.path() == "/api/records")

        captured = MockURLProtocol.respond(status: 200, json: #"{"ok": true}"#)
        try await makeClient().deleteRecord(MsgRef(channelID: 1, messageID: 2))
        #expect(captured.method == "DELETE")
        #expect(captured.url?.path() == "/api/records/1/2")
    }

    @Test("媒体与头像 URL builder")
    func mediaURLs() {
        let client = makeClient()
        #expect(client.mediaURL(channelID: 5, messageID: 10).absoluteString
            == "https://example.com/api/media/5/10")
        #expect(client.mediaURL(channelID: 5, messageID: 10, thumb: true).absoluteString
            == "https://example.com/api/media/5/10?thumb=1")
        #expect(client.avatarURL(channelID: 5).absoluteString
            == "https://example.com/api/channels/5/avatar")
    }
}
