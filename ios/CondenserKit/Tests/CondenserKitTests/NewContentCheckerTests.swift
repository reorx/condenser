import Foundation
import Testing
@testable import CondenserKit

// NewContentChecker：一次性问 /timeline/new/count 拿新内容条数（冷启动 / 回前台的胶囊用）。
// after=head_cursor 传参、无游标不请求、失败按 0 处理、401 走回调。
// 2026-09-07 起只走 count 接口——不再为了一个数字把 100 条 envelope 拉回来。

@MainActor
@Suite("NewContentChecker")
struct NewContentCheckerTests {
    @Test("check：走 count 接口，after/channel_id/unread_only/source 传参正确并返回计数")
    func checkReturnsCount() async {
        let api = StubAPI()
        api.countResults = [.success(5)]
        let checker = NewContentChecker(
            api: api, channelID: 42, unreadOnly: true, headCursor: { "h1" })
        #expect(await checker.check() == 5)
        #expect(api.countCalls.count == 1)
        #expect(api.countCalls[0].after == "h1")
        #expect(api.countCalls[0].channelID == 42)
        #expect(api.countCalls[0].unreadOnly == true)
        #expect(api.countCalls[0].source == nil)
        #expect(api.newCalls.isEmpty, "全量 /timeline/new 一次都不该打")
    }

    @Test("单信源 / 单 feed 视图：source、feed 透传")
    func sourceScoped() async {
        let api = StubAPI()
        api.countResults = [.success(1)]
        let checker = NewContentChecker(api: api, source: SourceID.x, feed: "foryou", headCursor: { "h1" })
        _ = await checker.check()
        #expect(api.countCalls[0].source == SourceID.x)
        #expect(api.countCalls[0].feed == "foryou")
    }

    @Test("head_cursor 为 nil 时不请求，返回 0")
    func skipsWithoutCursor() async {
        let api = StubAPI()
        let checker = NewContentChecker(api: api, headCursor: { nil })
        #expect(await checker.check() == 0)
        #expect(api.countCalls.isEmpty)
    }

    @Test("请求失败 → 0（静默，不打扰阅读）")
    func failureIsZero() async {
        let api = StubAPI()
        api.countResults = [.failure(APIError.http(status: 500, detail: nil))]
        let checker = NewContentChecker(api: api, headCursor: { "h1" })
        #expect(await checker.check() == 0)
    }

    @Test("401 → onUnauthorized 回调，返回 0")
    func unauthorized() async {
        let api = StubAPI()
        api.countResults = [.failure(APIError.unauthorized)]
        let checker = NewContentChecker(api: api, headCursor: { "h1" })
        var fired = false
        checker.onUnauthorized = { fired = true }
        #expect(await checker.check() == 0)
        #expect(fired)
    }
}
