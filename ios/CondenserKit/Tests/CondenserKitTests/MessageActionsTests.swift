import Foundation
import Testing
@testable import CondenserKit

// 消息 stats + 转发至本频道（2026-07-22 批次）：
// GET /api/messages/{cid}/{mid}/stats（实时 views/forwards/reactions）、
// POST .../forward（空评论 = 原生 forward，有评论 = quote 新消息）、
// GET/PATCH /api/app/meta 的 forward_channel。
// 字段事实来源 frontend/src/lib/types.ts（ReactionCount/MessageStats/ForwardResult/AppMeta）。

@Suite("Message stats models")
struct MessageStatsModelTests {
    private let decoder = JSONDecoder.condenserAPI

    @Test("MessageStats：emoji + custom（含 chosen）全字段解码")
    func fullDecode() throws {
        let json = #"""
        {"views": 1234, "forwards": 56, "reactions": [
          {"kind": "emoji", "emoji": "👍", "document_id": null, "count": 12, "chosen": false},
          {"kind": "custom", "emoji": null, "document_id": 5368221678337263242, "count": 3, "chosen": true}
        ]}
        """#
        let stats = try decoder.decode(MessageStats.self, from: Data(json.utf8))
        #expect(stats.views == 1234)
        #expect(stats.forwards == 56)
        #expect(stats.reactions.count == 2)
        #expect(stats.reactions[0].kind == .emoji)
        #expect(stats.reactions[0].emoji == "👍")
        #expect(stats.reactions[0].documentID == nil)
        #expect(stats.reactions[0].count == 12)
        #expect(stats.reactions[0].chosen == false)
        #expect(stats.reactions[1].kind == .custom)
        #expect(stats.reactions[1].documentID == 5_368_221_678_337_263_242)
        #expect(stats.reactions[1].chosen == true)
    }

    @Test("views/forwards 为 null（频道不带该数据）→ nil，不炸解码")
    func nullNumbers() throws {
        let json = #"{"views": null, "forwards": null, "reactions": []}"#
        let stats = try decoder.decode(MessageStats.self, from: Data(json.utf8))
        #expect(stats.views == nil)
        #expect(stats.forwards == nil)
        #expect(stats.reactions.isEmpty)
        #expect(stats.isEmpty)
    }

    @Test("未知 reaction kind（未来 TL 类型）→ .other 前向兼容")
    func unknownKindDegrades() throws {
        let json = #"""
        {"views": 1, "forwards": null, "reactions": [
          {"kind": "paid", "emoji": null, "document_id": null, "count": 5, "chosen": false}
        ]}
        """#
        let stats = try decoder.decode(MessageStats.self, from: Data(json.utf8))
        #expect(stats.reactions[0].kind == .other)
    }

    @Test("AppMeta：forward_channel 有值与 null 两种形态")
    func appMetaDecode() throws {
        let set = try decoder.decode(AppMeta.self, from: Data(
            #"{"schema_version": 5, "backfill_days": 30, "forward_channel": "@my_channel"}"#.utf8))
        #expect(set.schemaVersion == 5)
        #expect(set.backfillDays == 30)
        #expect(set.forwardChannel == "@my_channel")

        let unset = try decoder.decode(AppMeta.self, from: Data(
            #"{"schema_version": 5, "backfill_days": 30, "forward_channel": null}"#.utf8))
        #expect(unset.forwardChannel == nil)
    }
}

// 嵌套进 APIClientTests：MockURLProtocol 的静态 handler 要求所有网络套件同域串行，
// 父套件的 .serialized 对子套件递归生效
extension APIClientTests {
    @Suite("message actions")
    struct MessageActions {
        private func makeClient() -> APIClient {
            APIClient(
                baseURL: URL(string: "https://example.com")!,
                token: "tok_test",
                configuration: MockURLProtocol.makeSessionConfiguration())
        }

        @Test("messageStats：GET /api/messages/{cid}/{mid}/stats，带 Bearer")
        func statsRequest() async throws {
            let captured = MockURLProtocol.respond(
                status: 200, json: #"{"views": 10, "forwards": 2, "reactions": []}"#)
            let stats = try await makeClient().messageStats(channelID: 7, messageID: 99)
            #expect(stats.views == 10)
            #expect(captured.method == "GET")
            #expect(captured.url?.path() == "/api/messages/7/99/stats")
            #expect(captured.authorization == "Bearer tok_test")
        }

        @Test("forwardMessage 带评论：POST body {comment}，解析 quote 模式 + link")
        func forwardWithComment() async throws {
            let captured = MockURLProtocol.respond(
                status: 200, json: #"{"status": "ok", "mode": "quote", "link": "https://t.me/mych/123"}"#)
            let result = try await makeClient().forwardMessage(
                channelID: 7, messageID: 99, comment: "值得一读")
            #expect(result.mode == .quote)
            #expect(result.link == "https://t.me/mych/123")
            #expect(captured.method == "POST")
            #expect(captured.url?.path() == "/api/messages/7/99/forward")
            #expect(captured.bodyJSON?["comment"] as? String == "值得一读")
        }

        @Test("forwardMessage 空/纯空白评论 → body 不带 comment（原生 forward）")
        func forwardEmptyComment() async throws {
            var captured = MockURLProtocol.respond(
                status: 200, json: #"{"status": "ok", "mode": "forward", "link": "https://t.me/mych/124"}"#)
            var result = try await makeClient().forwardMessage(channelID: 7, messageID: 99, comment: nil)
            #expect(result.mode == .forward)
            #expect(captured.bodyJSON?["comment"] == nil)

            captured = MockURLProtocol.respond(
                status: 200, json: #"{"status": "ok", "mode": "forward", "link": "https://t.me/mych/125"}"#)
            result = try await makeClient().forwardMessage(channelID: 7, messageID: 99, comment: "  \n ")
            #expect(result.mode == .forward)
            #expect(captured.bodyJSON?["comment"] == nil)
        }

        @Test("forwardMessage 评论两侧空白被 trim")
        func forwardTrimsComment() async throws {
            let captured = MockURLProtocol.respond(
                status: 200, json: #"{"status": "ok", "mode": "quote", "link": "https://t.me/mych/126"}"#)
            _ = try await makeClient().forwardMessage(channelID: 7, messageID: 99, comment: "  好文 \n")
            #expect(captured.bodyJSON?["comment"] as? String == "好文")
        }

        @Test("appMeta：GET /api/app/meta")
        func appMetaRequest() async throws {
            let captured = MockURLProtocol.respond(
                status: 200,
                json: #"{"schema_version": 5, "backfill_days": 30, "forward_channel": "@mych"}"#)
            let meta = try await makeClient().appMeta()
            #expect(meta.forwardChannel == "@mych")
            #expect(captured.url?.path() == "/api/app/meta")
        }

        @Test("setForwardChannel：PATCH body {forward_channel}，返回新 meta；'' 清除读回 nil")
        func setForwardChannel() async throws {
            var captured = MockURLProtocol.respond(
                status: 200,
                json: #"{"schema_version": 5, "backfill_days": 30, "forward_channel": "@mych"}"#)
            var meta = try await makeClient().setForwardChannel("@mych")
            #expect(captured.method == "PATCH")
            #expect(captured.url?.path() == "/api/app/meta")
            #expect(captured.bodyJSON?["forward_channel"] as? String == "@mych")
            #expect(meta.forwardChannel == "@mych")

            captured = MockURLProtocol.respond(
                status: 200,
                json: #"{"schema_version": 5, "backfill_days": 30, "forward_channel": null}"#)
            meta = try await makeClient().setForwardChannel("")
            #expect(captured.bodyJSON?["forward_channel"] as? String == "")
            #expect(meta.forwardChannel == nil)
        }
    }
}
