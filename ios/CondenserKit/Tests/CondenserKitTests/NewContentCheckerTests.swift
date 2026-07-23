import Foundation
import Testing
@testable import CondenserKit

// NewContentChecker：一次性问 /timeline/new 拿新内容条数（回前台自动更新用）。
// after=head_cursor 传参、无游标不请求、失败按 0 处理、401 走回调。

@MainActor
@Suite("NewContentChecker")
struct NewContentCheckerTests {
    @Test("check：after/channel_id/unread_only/source 传参正确并返回计数")
    func checkReturnsCount() async {
        let api = StubAPI()
        api.newResults = [.success(TimelineNew(count: 5, items: []))]
        let checker = NewContentChecker(
            api: api, channelID: 42, unreadOnly: true, headCursor: { "h1" })
        #expect(await checker.check() == 5)
        #expect(api.newCalls.count == 1)
        #expect(api.newCalls[0].after == "h1")
        #expect(api.newCalls[0].channelID == 42)
        #expect(api.newCalls[0].unreadOnly == true)
        #expect(api.newCalls[0].source == nil)
    }

    @Test("单信源视图：source 透传到 /timeline/new")
    func sourceScoped() async {
        let api = StubAPI()
        api.newResults = [.success(TimelineNew(count: 1, items: []))]
        let checker = NewContentChecker(api: api, source: SourceID.hn, headCursor: { "h1" })
        _ = await checker.check()
        #expect(api.newCalls[0].source == SourceID.hn)
    }

    @Test("head_cursor 为 nil 时不请求，返回 0")
    func skipsWithoutCursor() async {
        let api = StubAPI()
        let checker = NewContentChecker(api: api, headCursor: { nil })
        #expect(await checker.check() == 0)
        #expect(api.newCalls.isEmpty)
    }

    @Test("请求失败 → 0（静默，不打扰阅读）")
    func failureIsZero() async {
        let api = StubAPI()
        api.newResults = [.failure(APIError.http(status: 500, detail: nil))]
        let checker = NewContentChecker(api: api, headCursor: { "h1" })
        #expect(await checker.check() == 0)
    }

    @Test("401 → onUnauthorized 回调，返回 0")
    func unauthorized() async {
        let api = StubAPI()
        api.newResults = [.failure(APIError.unauthorized)]
        let checker = NewContentChecker(api: api, headCursor: { "h1" })
        var fired = false
        checker.onUnauthorized = { fired = true }
        #expect(await checker.check() == 0)
        #expect(fired)
    }
}
