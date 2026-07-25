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
        #expect(!names.contains("source"))
    }

    @Test("timeline：source 参数透传")
    func timelineSourceParam() async throws {
        let captured = MockURLProtocol.respond(
            status: 200, json: #"{"items": [], "next_cursor": null, "head_cursor": null}"#)
        _ = try await makeClient().timeline(source: "hn")
        let comps = URLComponents(url: captured.url!, resolvingAgainstBaseURL: false)!
        #expect(comps.queryItems!.contains(URLQueryItem(name: "source", value: "hn")))
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

    @Test("markRead：POST /api/read，body {keys: [...]}")
    func markReadBody() async throws {
        let captured = MockURLProtocol.respond(status: 200, json: #"{"ok": true}"#)
        try await makeClient().markRead(keys: ["tg:7:99", "hn:123"])
        #expect(captured.method == "POST")
        #expect(captured.url?.path() == "/api/read")
        let keys = try #require(captured.bodyJSON?["keys"] as? [String])
        #expect(keys == ["tg:7:99", "hn:123"])
    }

    @Test("sources：GET /api/sources 解码分组")
    func sourcesRequest() async throws {
        let captured = MockURLProtocol.respond(status: 200, json: #"""
        [{"source": "telegram",
          "subscriptions": [{"channel_id": 42, "name": "Chan", "username": "c42",
                             "enabled": true, "unread": 3, "config": null}]},
         {"source": "hn",
          "subscriptions": [{"channel_id": "front", "name": "Hacker News Front Page",
                             "username": null, "enabled": true, "unread": 7,
                             "config": {"display_mode": "top20"}}]}]
        """#)
        let groups = try await makeClient().sources()
        #expect(captured.url?.path() == "/api/sources")
        #expect(groups.count == 2)
        #expect(groups[0].subscriptions[0].channelID.intValue == 42)
        #expect(groups[1].subscriptions[0].channelID == .string("front"))
        #expect(groups[1].subscriptions[0].unread == 7)
    }

    @Test("timeline：feed 参数把多 feed 信源收窄到一个 feed（X）")
    func timelineFeedParam() async throws {
        let captured = MockURLProtocol.respond(
            status: 200, json: #"{"items": [], "next_cursor": null, "head_cursor": null}"#)
        _ = try await makeClient().timeline(source: "x", feed: "foryou")
        let comps = URLComponents(url: captured.url!, resolvingAgainstBaseURL: false)!
        #expect(comps.queryItems!.contains(URLQueryItem(name: "source", value: "x")))
        #expect(comps.queryItems!.contains(URLQueryItem(name: "feed", value: "foryou")))
    }

    @Test("反馈端点：POST /api/feedback {key, verdict}，撤销走 DELETE /api/feedback/{key}")
    func feedbackEndpoints() async throws {
        let posted = MockURLProtocol.respond(status: 200, json: #"{"ok": true}"#)
        try await makeClient().setFeedback(key: "x:42", verdict: .down)
        #expect(posted.method == "POST")
        #expect(posted.url?.path() == "/api/feedback")
        #expect(posted.bodyJSON?["key"] as? String == "x:42")
        #expect(posted.bodyJSON?["verdict"] as? String == "down")

        let deleted = MockURLProtocol.respond(status: 200, json: #"{"ok": true}"#)
        try await makeClient().clearFeedback(key: "x:42")
        #expect(deleted.method == "DELETE")
        #expect(deleted.url?.path() == "/api/feedback/x:42")
    }

    @Test("401 → APIError.unauthorized")
    func unauthorized() async throws {
        _ = MockURLProtocol.respond(status: 401, json: #"{"detail": "unauthorized"}"#)
        await #expect(throws: APIError.unauthorized) {
            _ = try await makeClient().sources()
        }
    }

    @Test("非 2xx 携带后端 detail")
    func httpErrorDetail() async throws {
        _ = MockURLProtocol.respond(status: 503, json: #"{"detail": "telegram not connected"}"#)
        await #expect(throws: APIError.http(status: 503, detail: "telegram not connected")) {
            _ = try await makeClient().sources()
        }
    }

    @Test("fetchOlder：POST /api/tg/fetch-older/{id}?count=，解析 fetched")
    func fetchOlderRequest() async throws {
        let captured = MockURLProtocol.respond(
            status: 200, json: #"{"status": "ok", "fetched": 42}"#)
        let fetched = try await makeClient().fetchOlder(channelID: 7, count: 200)
        #expect(fetched == 42)
        #expect(captured.method == "POST")
        let comps = URLComponents(url: captured.url!, resolvingAgainstBaseURL: false)!
        #expect(comps.path == "/api/tg/fetch-older/7")
        #expect(comps.queryItems!.contains(URLQueryItem(name: "count", value: "200")))
    }

    @Test("records 的 save/delete：item key 出入参")
    func recordEndpoints() async throws {
        var captured = MockURLProtocol.respond(status: 200, json: #"{"ok": true}"#)
        try await makeClient().saveRecord(key: "hn:123")
        #expect(captured.method == "POST")
        #expect(captured.url?.path() == "/api/records")
        #expect(captured.bodyJSON?["key"] as? String == "hn:123")

        captured = MockURLProtocol.respond(status: 200, json: #"{"ok": true}"#)
        try await makeClient().deleteRecord(key: "tg:1:2")
        #expect(captured.method == "DELETE")
        #expect(captured.url?.path() == "/api/records/tg:1:2")
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
