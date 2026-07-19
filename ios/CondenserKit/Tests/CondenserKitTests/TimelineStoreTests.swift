import Foundation
import Testing
@testable import CondenserKit

// TimelineStore 分页状态机：两页游标衔接、has_more=false 停止、刷新替换+去重、
// 401 回调、收藏乐观切换与失败回滚。

func makeMsg(id: Int, channelID: Int = 1, dateOffset: TimeInterval = 0, isSaved: Bool = false) -> DisplayMessage {
    DisplayMessage(
        id: id, channelID: channelID,
        date: Date(timeIntervalSince1970: 1_784_000_000 - Double(id) - dateOffset),
        isEdited: false, editDate: nil, senderID: nil, senderName: nil,
        text: "msg \(id)", isAlbum: false, groupedID: nil, mediaItems: [],
        webpage: nil, isForwarded: false, forwardInfo: nil,
        views: nil, forwardsCount: nil, repliesCount: nil, rawMessageIDs: [id],
        isRead: false, isSaved: isSaved, channel: nil)
}

func makePage(_ items: [DisplayMessage], next: String? = nil, head: String? = nil, end: String? = nil) -> TimelinePage {
    TimelinePage(items: items, nextCursor: next, endCursor: end ?? next, headCursor: head)
}

/// 可编程 stub：按调用顺序出队 timeline 页；记录收到的参数。
final class StubAPI: CondenserAPI, @unchecked Sendable {
    var timelinePages: [Result<TimelinePage, Error>] = []
    var timelineCalls: [(cursor: String?, channelID: Int?, unreadOnly: Bool)] = []
    var newResults: [Result<TimelineNew, Error>] = []
    var newCalls: [(after: String, channelID: Int?, unreadOnly: Bool)] = []
    var markReadCalls: [[MsgRef]] = []
    var markReadError: Error?
    var saveCalls: [MsgRef] = []
    var deleteCalls: [MsgRef] = []
    var recordError: Error?
    var recordsResults: [Result<[DisplayMessage], Error>] = []
    var recordsCalls = 0
    var fetchOlderResults: [Result<Int, Error>] = []
    var fetchOlderCalls: [(channelID: Int, count: Int)] = []

    func timeline(cursor: String?, limit: Int?, channelID: Int?, date: String?, unreadOnly: Bool) async throws -> TimelinePage {
        timelineCalls.append((cursor, channelID, unreadOnly))
        guard !timelinePages.isEmpty else { throw APIError.invalidResponse }
        return try timelinePages.removeFirst().get()
    }

    func timelineNew(after: String, channelID: Int?, limit: Int, unreadOnly: Bool) async throws -> TimelineNew {
        newCalls.append((after, channelID, unreadOnly))
        guard !newResults.isEmpty else { throw APIError.invalidResponse }
        return try newResults.removeFirst().get()
    }

    func subscriptions() async throws -> [Subscription] { [] }

    func markRead(_ items: [MsgRef]) async throws {
        if let markReadError { throw markReadError }
        markReadCalls.append(items)
    }

    func records() async throws -> [DisplayMessage] {
        recordsCalls += 1
        guard !recordsResults.isEmpty else { return [] }
        return try recordsResults.removeFirst().get()
    }

    func saveRecord(_ ref: MsgRef) async throws {
        if let recordError { throw recordError }
        saveCalls.append(ref)
    }

    func deleteRecord(_ ref: MsgRef) async throws {
        if let recordError { throw recordError }
        deleteCalls.append(ref)
    }

    func fetchOlder(channelID: Int, count: Int) async throws -> Int {
        fetchOlderCalls.append((channelID, count))
        guard !fetchOlderResults.isEmpty else { throw APIError.invalidResponse }
        return try fetchOlderResults.removeFirst().get()
    }
}

@MainActor
@Suite("TimelineStore")
struct TimelineStoreTests {
    @Test("loadInitial → 首页内容 + head_cursor 记录")
    func initialLoad() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeMsg(id: 3), makeMsg(id: 2)], next: "c2", head: "h1"))]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        #expect(store.items.map(\.id) == [3, 2])
        #expect(store.headCursor == "h1")
        #expect(store.hasMore)
        #expect(store.error == nil)
    }

    @Test("loadMore：游标衔接两页，next_cursor=nil 后停止")
    func pagination() async {
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeMsg(id: 3)], next: "c2", head: "h1")),
            .success(makePage([makeMsg(id: 2)], next: nil)),
        ]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        await store.loadMore()
        #expect(store.items.map(\.id) == [3, 2])
        #expect(api.timelineCalls.map(\.cursor) == [nil, "c2"])
        #expect(!store.hasMore)
        await store.loadMore()
        #expect(api.timelineCalls.count == 2, "hasMore=false 后不再请求")
    }

    @Test("loadMore 按 unitKey 去重重叠条目")
    func dedupeOnAppend() async {
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeMsg(id: 3), makeMsg(id: 2)], next: "c2")),
            .success(makePage([makeMsg(id: 2), makeMsg(id: 1)], next: nil)),
        ]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        await store.loadMore()
        #expect(store.items.map(\.id) == [3, 2, 1])
    }

    @Test("refresh 替换为新的第一页并重置分页")
    func refreshReplaces() async {
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeMsg(id: 2)], next: "c2", head: "h1")),
            .success(makePage([makeMsg(id: 5), makeMsg(id: 4)], next: "c9", head: "h2")),
        ]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        await store.refresh()
        #expect(store.items.map(\.id) == [5, 4])
        #expect(store.headCursor == "h2")
        #expect(api.timelineCalls.last?.cursor == nil)
        #expect(store.hasMore)
    }

    @Test("channelID/unreadOnly 透传到 API")
    func filterParams() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([]))]
        let store = TimelineStore(api: api, channelID: 42, unreadOnly: true)
        await store.loadInitial()
        #expect(api.timelineCalls.first?.channelID == 42)
        #expect(api.timelineCalls.first?.unreadOnly == true)
    }

    @Test("401 → onUnauthorized 回调，不留错误文案")
    func unauthorized() async {
        let api = StubAPI()
        api.timelinePages = [.failure(APIError.unauthorized)]
        let store = TimelineStore(api: api)
        var fired = false
        store.onUnauthorized = { fired = true }
        await store.loadInitial()
        #expect(fired)
        #expect(store.error == nil)
    }

    @Test("普通失败 → error 文案，已有内容保留")
    func failureKeepsContent() async {
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeMsg(id: 3)], next: "c2")),
            .failure(APIError.http(status: 500, detail: "boom")),
        ]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        await store.loadMore()
        #expect(store.items.map(\.id) == [3])
        #expect(store.error != nil)
    }

    @Test("fetchOlderFromServer：触发后端拉取，再用 end_cursor 接上翻页")
    func fetchOlderResumesPaging() async {
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeMsg(id: 3), makeMsg(id: 2)], next: nil, end: "e1")),
            .success(makePage([makeMsg(id: 1)], next: "c9", end: "e2")),
        ]
        api.fetchOlderResults = [.success(2)]
        let store = TimelineStore(api: api, channelID: 42)
        await store.loadInitial()
        #expect(!store.hasMore)

        await store.fetchOlderFromServer()
        #expect(api.fetchOlderCalls.map(\.channelID) == [42])
        #expect(api.fetchOlderCalls.first?.count == 200)
        #expect(api.timelineCalls.last?.cursor == "e1", "用 end_cursor 续接，而不是从头拉")
        #expect(store.items.map(\.id) == [3, 2, 1])
        #expect(store.hasMore, "拉到的历史多于一页时恢复无限滚动")
        #expect(!store.olderExhausted)
    }

    @Test("fetchOlderFromServer：后端返回 0 → 标记没有更早消息，不再发时间线请求")
    func fetchOlderExhausted() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeMsg(id: 3)], next: nil, end: "e1"))]
        api.fetchOlderResults = [.success(0), .success(1)]
        let store = TimelineStore(api: api, channelID: 42)
        await store.loadInitial()

        await store.fetchOlderFromServer()
        #expect(store.olderExhausted)
        #expect(api.timelineCalls.count == 1, "fetched=0 时不再请求时间线")

        await store.fetchOlderFromServer()
        #expect(api.fetchOlderCalls.count == 1, "olderExhausted 后不再触发")
    }

    @Test("fetchOlderFromServer：非频道视图 / 本地还有分页时都是 no-op")
    func fetchOlderGuards() async {
        let all = StubAPI()
        all.timelinePages = [.success(makePage([makeMsg(id: 3)], next: nil, end: "e1"))]
        let allStore = TimelineStore(api: all)
        await allStore.loadInitial()
        await allStore.fetchOlderFromServer()
        #expect(all.fetchOlderCalls.isEmpty, "All/Unread 视图无频道语义")

        let channel = StubAPI()
        channel.timelinePages = [.success(makePage([makeMsg(id: 3)], next: "c2", end: "e1"))]
        let channelStore = TimelineStore(api: channel, channelID: 42)
        await channelStore.loadInitial()
        await channelStore.fetchOlderFromServer()
        #expect(channel.fetchOlderCalls.isEmpty, "本地分页未走完时不触发")
    }

    @Test("fetchOlderFromServer 失败 → error 文案，可再次触发")
    func fetchOlderFailure() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeMsg(id: 3)], next: nil, end: "e1"))]
        api.fetchOlderResults = [.failure(APIError.http(status: 503, detail: "telegram not authorized"))]
        let store = TimelineStore(api: api, channelID: 42)
        await store.loadInitial()

        await store.fetchOlderFromServer()
        #expect(store.error != nil)
        #expect(!store.olderExhausted)
        #expect(!store.isFetchingOlder)
    }

    @Test("refresh 重置 olderExhausted")
    func refreshResetsOlderExhausted() async {
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeMsg(id: 3)], next: nil, end: "e1")),
            .success(makePage([makeMsg(id: 3)], next: nil, end: "e1")),
        ]
        api.fetchOlderResults = [.success(0)]
        let store = TimelineStore(api: api, channelID: 42)
        await store.loadInitial()
        await store.fetchOlderFromServer()
        #expect(store.olderExhausted)

        await store.refresh()
        #expect(!store.olderExhausted)
    }

    @Test("toggleSaved 乐观置位，失败回滚")
    func toggleSaved() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeMsg(id: 3)]))]
        let store = TimelineStore(api: api)
        await store.loadInitial()

        await store.toggleSaved(store.items[0])
        #expect(store.items[0].isSaved == true)
        #expect(api.saveCalls == [MsgRef(channelID: 1, messageID: 3)])

        api.recordError = APIError.http(status: 500, detail: nil)
        await store.toggleSaved(store.items[0])
        #expect(store.items[0].isSaved == true, "unsave 失败回滚为已收藏")
    }
}
