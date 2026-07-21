import Foundation
import Testing
@testable import CondenserKit

// NewContentPoller：after=head_cursor 传参、计数发布、reset 归零、start/stop 循环。

@MainActor
@Suite("NewContentPoller")
struct NewContentPollerTests {
    @Test("checkNow：after/channel_id/unread_only/source 传参正确并发布计数")
    func checkPublishesCount() async {
        let api = StubAPI()
        api.newResults = [.success(TimelineNew(count: 5, items: []))]
        let poller = NewContentPoller(
            api: api, channelID: 42, unreadOnly: true, interval: .seconds(60),
            headCursor: { "h1" })
        await poller.checkNow()
        #expect(poller.count == 5)
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
        let poller = NewContentPoller(
            api: api, source: SourceID.hn, interval: .seconds(60), headCursor: { "h1" })
        await poller.checkNow()
        #expect(api.newCalls[0].source == SourceID.hn)
    }

    @Test("head_cursor 为 nil 时不请求")
    func skipsWithoutCursor() async {
        let api = StubAPI()
        let poller = NewContentPoller(api: api, interval: .seconds(60), headCursor: { nil })
        await poller.checkNow()
        #expect(api.newCalls.isEmpty)
        #expect(poller.count == 0)
    }

    @Test("reset 归零（刷新后清胶囊）")
    func reset() async {
        let api = StubAPI()
        api.newResults = [.success(TimelineNew(count: 3, items: []))]
        let poller = NewContentPoller(api: api, interval: .seconds(60), headCursor: { "h1" })
        await poller.checkNow()
        #expect(poller.count == 3)
        poller.reset()
        #expect(poller.count == 0)
    }

    @Test("start 先立即查一次再按间隔轮询；stop 停止")
    func loop() async throws {
        let api = StubAPI()
        api.newResults = (0..<20).map { _ in .success(TimelineNew(count: 1, items: [])) }
        let poller = NewContentPoller(api: api, interval: .milliseconds(30), headCursor: { "h1" })
        poller.start()
        try await Task.sleep(for: .milliseconds(100))
        poller.stop()
        // stop 时可能有一次在途请求，先沉降再断言不增长
        try await Task.sleep(for: .milliseconds(30))
        let calls = api.newCalls.count
        #expect(calls >= 2, "立即一次 + 至少一轮间隔")
        try await Task.sleep(for: .milliseconds(80))
        #expect(api.newCalls.count == calls, "stop 后不再请求")
    }

    @Test("请求失败静默保留旧计数")
    func failureKeepsCount() async {
        let api = StubAPI()
        api.newResults = [
            .success(TimelineNew(count: 2, items: [])),
            .failure(APIError.http(status: 500, detail: nil)),
        ]
        let poller = NewContentPoller(api: api, interval: .seconds(60), headCursor: { "h1" })
        await poller.checkNow()
        await poller.checkNow()
        #expect(poller.count == 2)
    }
}
