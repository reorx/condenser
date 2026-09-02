import Foundation
import Testing
@testable import CondenserKit

// TimelineStore 分页状态机（多信源 envelope）：两页游标衔接、has_more=false 停止、
// 刷新替换+去重、source 透传、401 回调、收藏乐观切换（按 item key）与失败回滚。

func makeMsg(id: Int, channelID: Int = 1) -> DisplayMessage {
    DisplayMessage(
        id: id, channelID: channelID,
        date: Date(timeIntervalSince1970: 1_784_000_000 - Double(id)),
        isEdited: false, editDate: nil, senderID: nil, senderName: nil,
        text: "msg \(id)", isAlbum: false, groupedID: nil, mediaItems: [],
        webpage: nil, isForwarded: false, forwardInfo: nil,
        views: nil, forwardsCount: nil, repliesCount: nil, rawMessageIDs: [id],
        channel: nil)
}

/// TG envelope：key = "tg:{channelID}:{id}"
func makeItem(id: Int, channelID: Int = 1, isRead: Bool = false, isSaved: Bool = false) -> TimelineItem {
    let msg = makeMsg(id: id, channelID: channelID)
    return TimelineItem(
        source: SourceID.telegram, key: "tg:\(channelID):\(id)", datetime: msg.date,
        isRead: isRead, isSaved: isSaved, telegram: msg)
}

/// HN envelope：key = "hn:{id}"
func makeHnItem(id: Int, url: String? = "https://example.com/a", isRead: Bool = false) -> TimelineItem {
    let date = Date(timeIntervalSince1970: 1_784_000_000 - Double(id))
    let story = HnStory(
        id: id, title: "story \(id)", url: url, domain: url.flatMap { URL(string: $0)?.host() },
        author: "pg", type: "story", text: url == nil ? "<p>self text</p>" : nil,
        submittedAt: date, firstSeenAt: date, score: 100, commentsCount: 42,
        dayRank: 3, peakRank: 1, backfilled: false, preview: nil, summary: nil)
    return TimelineItem(
        source: SourceID.hn, key: "hn:\(id)", datetime: date,
        isRead: isRead, isSaved: false, hn: story)
}

func makePage(_ items: [TimelineItem], next: String? = nil, head: String? = nil, end: String? = nil) -> TimelinePage {
    TimelinePage(items: items, nextCursor: next, endCursor: end ?? next, headCursor: head)
}

/// 便捷断言：TG 条目的消息 id 序列
extension [TimelineItem] {
    var tgIDs: [Int] { compactMap(\.telegram?.id) }
}

/// 可编程 stub：按调用顺序出队 timeline 页；记录收到的参数。
final class StubAPI: CondenserAPI, @unchecked Sendable {
    var timelinePages: [Result<TimelinePage, Error>] = []
    var timelineCalls: [(cursor: String?, channelID: Int?, unreadOnly: Bool, source: String?, feed: String?)] = []
    var newResults: [Result<TimelineNew, Error>] = []
    var newCalls: [(after: String, channelID: Int?, unreadOnly: Bool, source: String?, feed: String?)] = []
    var feedbackCalls: [(key: String, verdict: ItemFeedback, reason: ItemFeedbackReason?)] = []
    var clearFeedbackCalls: [String] = []
    var feedbackError: Error?
    var markReadCalls: [[String]] = []
    var markReadError: Error?
    /// 模拟在途请求（测「本批成功不误清在途期间新入队的 key」）
    var markReadDelay: Duration?
    var saveCalls: [String] = []
    var deleteCalls: [String] = []
    var recordError: Error?
    var recordsResults: [Result<[TimelineItem], Error>] = []
    var recordsCalls = 0
    var sourcesResults: [Result<[SourceGroup], Error>] = []
    var fetchOlderResults: [Result<Int, Error>] = []
    var fetchOlderCalls: [(channelID: Int, count: Int)] = []

    func timeline(
        cursor: String?, limit: Int?, channelID: Int?, date: String?, unreadOnly: Bool,
        source: String?, feed: String?
    ) async throws -> TimelinePage {
        timelineCalls.append((cursor, channelID, unreadOnly, source, feed))
        guard !timelinePages.isEmpty else { throw APIError.invalidResponse }
        return try timelinePages.removeFirst().get()
    }

    func timelineNew(
        after: String, channelID: Int?, limit: Int, unreadOnly: Bool, source: String?,
        feed: String?
    ) async throws -> TimelineNew {
        newCalls.append((after, channelID, unreadOnly, source, feed))
        guard !newResults.isEmpty else { throw APIError.invalidResponse }
        return try newResults.removeFirst().get()
    }

    func sources() async throws -> [SourceGroup] {
        guard !sourcesResults.isEmpty else { return [] }
        return try sourcesResults.removeFirst().get()
    }

    func markRead(keys: [String]) async throws {
        if let markReadDelay { try? await Task.sleep(for: markReadDelay) }
        if let markReadError { throw markReadError }
        markReadCalls.append(keys)
    }

    func records() async throws -> [TimelineItem] {
        recordsCalls += 1
        guard !recordsResults.isEmpty else { return [] }
        return try recordsResults.removeFirst().get()
    }

    func saveRecord(key: String) async throws {
        if let recordError { throw recordError }
        saveCalls.append(key)
    }

    func deleteRecord(key: String) async throws {
        if let recordError { throw recordError }
        deleteCalls.append(key)
    }

    func fetchOlder(channelID: Int, count: Int) async throws -> Int {
        fetchOlderCalls.append((channelID, count))
        guard !fetchOlderResults.isEmpty else { throw APIError.invalidResponse }
        return try fetchOlderResults.removeFirst().get()
    }

    func setFeedback(key: String, verdict: ItemFeedback, reason: ItemFeedbackReason?) async throws {
        if let feedbackError { throw feedbackError }
        feedbackCalls.append((key, verdict, reason))
    }

    func clearFeedback(key: String) async throws {
        if let feedbackError { throw feedbackError }
        clearFeedbackCalls.append(key)
    }
}

@MainActor
@Suite("TimelineStore")
struct TimelineStoreTests {
    @Test("loadInitial → 首页内容 + head_cursor 记录")
    func initialLoad() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 3), makeItem(id: 2)], next: "c2", head: "h1"))]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        #expect(store.items.tgIDs == [3, 2])
        #expect(store.headCursor == "h1")
        #expect(store.hasMore)
        #expect(store.error == nil)
    }

    @Test("跨源页面按 envelope 原样保序（TG 与 HN 混排）")
    func mixedSourcePage() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 3), makeHnItem(id: 900), makeItem(id: 2)]))]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        #expect(store.items.map(\.key) == ["tg:1:3", "hn:900", "tg:1:2"])
        #expect(store.items[1].hn?.commentsURL.absoluteString == "https://news.ycombinator.com/item?id=900")
    }

    @Test("loadMore：游标衔接两页，next_cursor=nil 后停止")
    func pagination() async {
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeItem(id: 3)], next: "c2", head: "h1")),
            .success(makePage([makeItem(id: 2)], next: nil)),
        ]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        await store.loadMore()
        #expect(store.items.tgIDs == [3, 2])
        #expect(api.timelineCalls.map(\.cursor) == [nil, "c2"])
        #expect(!store.hasMore)
        await store.loadMore()
        #expect(api.timelineCalls.count == 2, "hasMore=false 后不再请求")
    }

    @Test("loadMore 按 item key 去重重叠条目")
    func dedupeOnAppend() async {
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeItem(id: 3), makeItem(id: 2)], next: "c2")),
            .success(makePage([makeItem(id: 2), makeItem(id: 1)], next: nil)),
        ]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        await store.loadMore()
        #expect(store.items.tgIDs == [3, 2, 1])
    }

    @Test("refresh 替换为新的第一页并重置分页")
    func refreshReplaces() async {
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeItem(id: 2)], next: "c2", head: "h1")),
            .success(makePage([makeItem(id: 5), makeItem(id: 4)], next: "c9", head: "h2")),
        ]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        await store.refresh()
        #expect(store.items.tgIDs == [5, 4])
        #expect(store.headCursor == "h2")
        #expect(api.timelineCalls.last?.cursor == nil)
        #expect(store.hasMore)
    }

    @Test("channelID/unreadOnly/source 透传到 API")
    func filterParams() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([]))]
        let store = TimelineStore(api: api, channelID: 42, unreadOnly: true)
        await store.loadInitial()
        #expect(api.timelineCalls.first?.channelID == 42)
        #expect(api.timelineCalls.first?.unreadOnly == true)
        #expect(api.timelineCalls.first?.source == nil)

        let hnAPI = StubAPI()
        hnAPI.timelinePages = [.success(makePage([makeHnItem(id: 1)], next: "c2"))]
        let hnStore = TimelineStore(api: hnAPI, source: SourceID.hn)
        await hnStore.loadInitial()
        await hnStore.loadMore()
        #expect(hnAPI.timelineCalls.map(\.source) == [SourceID.hn, SourceID.hn])
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
            .success(makePage([makeItem(id: 3)], next: "c2")),
            .failure(APIError.http(status: 500, detail: "boom")),
        ]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        await store.loadMore()
        #expect(store.items.tgIDs == [3])
        #expect(store.error != nil)
    }

    @Test("fetchOlderFromServer：触发后端拉取，再用 end_cursor 接上翻页")
    func fetchOlderResumesPaging() async {
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeItem(id: 3), makeItem(id: 2)], next: nil, end: "e1")),
            .success(makePage([makeItem(id: 1)], next: "c9", end: "e2")),
        ]
        api.fetchOlderResults = [.success(2)]
        let store = TimelineStore(api: api, channelID: 42)
        await store.loadInitial()
        #expect(!store.hasMore)

        await store.fetchOlderFromServer()
        #expect(api.fetchOlderCalls.map(\.channelID) == [42])
        #expect(api.fetchOlderCalls.first?.count == 200)
        #expect(api.timelineCalls.last?.cursor == "e1", "用 end_cursor 续接，而不是从头拉")
        #expect(store.items.tgIDs == [3, 2, 1])
        #expect(store.hasMore, "拉到的历史多于一页时恢复无限滚动")
        #expect(!store.olderExhausted)
    }

    @Test("fetchOlderFromServer：后端返回 0 → 标记没有更早消息，不再发时间线请求")
    func fetchOlderExhausted() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 3)], next: nil, end: "e1"))]
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
        all.timelinePages = [.success(makePage([makeItem(id: 3)], next: nil, end: "e1"))]
        let allStore = TimelineStore(api: all)
        await allStore.loadInitial()
        await allStore.fetchOlderFromServer()
        #expect(all.fetchOlderCalls.isEmpty, "All/Unread 视图无频道语义")

        let channel = StubAPI()
        channel.timelinePages = [.success(makePage([makeItem(id: 3)], next: "c2", end: "e1"))]
        let channelStore = TimelineStore(api: channel, channelID: 42)
        await channelStore.loadInitial()
        await channelStore.fetchOlderFromServer()
        #expect(channel.fetchOlderCalls.isEmpty, "本地分页未走完时不触发")
    }

    @Test("fetchOlderFromServer 失败 → error 文案，可再次触发")
    func fetchOlderFailure() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 3)], next: nil, end: "e1"))]
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
            .success(makePage([makeItem(id: 3)], next: nil, end: "e1")),
            .success(makePage([makeItem(id: 3)], next: nil, end: "e1")),
        ]
        api.fetchOlderResults = [.success(0)]
        let store = TimelineStore(api: api, channelID: 42)
        await store.loadInitial()
        await store.fetchOlderFromServer()
        #expect(store.olderExhausted)

        await store.refresh()
        #expect(!store.olderExhausted)
    }

    @Test("toggleSaved 乐观置位（按 item key 上报），失败回滚")
    func toggleSaved() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 3)]))]
        let store = TimelineStore(api: api)
        await store.loadInitial()

        await store.toggleSaved(store.items[0])
        #expect(store.items[0].isSaved)
        #expect(api.saveCalls == ["tg:1:3"])

        api.recordError = APIError.http(status: 500, detail: nil)
        await store.toggleSaved(store.items[0])
        #expect(store.items[0].isSaved, "unsave 失败回滚为已收藏")
    }

    @Test("HN 条目 toggleSaved 用 hn: key")
    func toggleSavedHn() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeHnItem(id: 77)]))]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        await store.toggleSaved(store.items[0])
        #expect(api.saveCalls == ["hn:77"])
    }

    @Test("markLocallyRead 按 key 置位")
    func markLocallyRead() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 3), makeHnItem(id: 900)]))]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        store.markLocallyRead(["hn:900"])
        #expect(store.items[0].isRead == false)
        #expect(store.items[1].isRead)
    }
}
