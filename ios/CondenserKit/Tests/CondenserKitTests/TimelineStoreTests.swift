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

func makePage(_ items: [DisplayMessage], next: String? = nil, head: String? = nil) -> TimelinePage {
    TimelinePage(items: items, nextCursor: next, headCursor: head)
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

    func records() async throws -> [DisplayMessage] { [] }

    func saveRecord(_ ref: MsgRef) async throws {
        if let recordError { throw recordError }
        saveCalls.append(ref)
    }

    func deleteRecord(_ ref: MsgRef) async throws {
        if let recordError { throw recordError }
        deleteCalls.append(ref)
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
