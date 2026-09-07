import Foundation
import Testing
@testable import CondenserKit

// SnapshotCache：JSON 快照落盘（写入→读回），缺失/损坏文件容错返回 nil 不 crash，
// 同 key 覆盖写。TimelineStore 集成：冷启动先渲染快照、网络成功后替换并回写快照。

@Suite("SnapshotCache")
struct SnapshotCacheTests {
    private func makeCache() -> (SnapshotCache, URL) {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("snapshot-tests-\(UUID().uuidString)", isDirectory: true)
        return (SnapshotCache(directory: dir), dir)
    }

    @Test("写入 → 读回同一值")
    func roundTrip() {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        let page = makePage([makeItem(id: 1), makeItem(id: 2)], next: "c2", head: "h1")
        cache.save(page, key: "timeline-all")
        #expect(cache.load(TimelinePage.self, key: "timeline-all") == page)
    }

    @Test("缺失 key → nil")
    func missingKey() {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        #expect(cache.load(TimelinePage.self, key: "nope") == nil)
    }

    @Test("损坏文件 → nil 不 crash")
    func corruptFile() throws {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeItem(id: 1)]), key: "timeline-all")
        try Data("not json{{{".utf8).write(to: cache.fileURL(for: "timeline-all"))
        #expect(cache.load(TimelinePage.self, key: "timeline-all") == nil)
    }

    @Test("同 key 覆盖写，读到最新值")
    func overwrite() {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeItem(id: 1)]), key: "k")
        cache.save(makePage([makeItem(id: 9)]), key: "k")
        #expect(cache.load(TimelinePage.self, key: "k")?.items.tgIDs == [9])
    }

    @Test("remove 后读不到")
    func removeKey() {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeItem(id: 1)]), key: "k")
        cache.remove(key: "k")
        #expect(cache.load(TimelinePage.self, key: "k") == nil)
    }

    @Test("旧契约（envelope 之前的扁平 items）快照 → decode 失败按 miss 处理")
    func preEnvelopeSnapshotIsMiss() throws {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        // Phase 4 之前的 TimelinePage：items 直接是 DisplayMessage 数组
        let legacy = #"""
        {"items": [{"id": 1, "channel_id": 5, "date": "2026-07-16T09:26:05Z",
                    "is_edited": false, "edit_date": null, "sender_id": null,
                    "sender_name": null, "text": "old", "is_album": false,
                    "grouped_id": null, "media_items": [], "webpage": null,
                    "is_forwarded": false, "forward_info": null, "views": null,
                    "forwards_count": null, "replies_count": null,
                    "raw_message_ids": [1], "is_read": false, "is_saved": false}],
         "next_cursor": null, "end_cursor": null, "head_cursor": "h1"}
        """#
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try Data(legacy.utf8).write(to: cache.fileURL(for: "timeline-all"))
        #expect(cache.load(TimelinePage.self, key: "timeline-all") == nil, "旧快照当 miss，不 crash")
    }
}

@MainActor
@Suite("TimelineStore + SnapshotCache")
struct TimelineSnapshotTests {
    private func makeCache() -> (SnapshotCache, URL) {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("snapshot-tests-\(UUID().uuidString)", isDirectory: true)
        return (SnapshotCache(directory: dir), dir)
    }

    @Test("冷启动：有快照先渲染；网络失败时保留快照内容 + error")
    func snapshotRendersWhenNetworkFails() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeItem(id: 5)], next: "c-snap", head: "h-snap"), key: "timeline-all")

        let api = StubAPI()
        api.timelinePages = [.failure(APIError.http(status: 500, detail: "boom"))]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "timeline-all")
        await store.loadInitial()
        #expect(store.items.tgIDs == [5], "网络失败也能读快照")
        #expect(store.headCursor == "h-snap")
        #expect(store.error != nil)
    }

    @Test("冷启动：网络成功后替换快照内容并回写缓存")
    func networkReplacesSnapshotAndSaves() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeItem(id: 5)]), key: "timeline-all")

        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 9), makeItem(id: 8)], next: "c2", head: "h2"))]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "timeline-all")
        await store.loadInitial()
        #expect(store.items.tgIDs == [9, 8])
        #expect(cache.load(TimelinePage.self, key: "timeline-all")?.items.tgIDs == [9, 8],
                "新首页回写快照")
    }

    @Test("preferSnapshot：有快照就停在快照上，不打网络，返回 true；游标随快照恢复")
    func preferSnapshotSkipsNetwork() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeItem(id: 5), makeItem(id: 4)], next: "c-snap", head: "h-snap"), key: "k")

        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 9)], head: "h-net"))]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "k")
        let restored = await store.loadInitial(preferSnapshot: true)
        #expect(restored)
        #expect(api.timelineCalls.isEmpty, "现场来自快照，网络一次都不打")
        #expect(store.items.tgIDs == [5, 4])
        #expect(store.headCursor == "h-snap", "胶囊检查用快照的 head")
        #expect(store.hasMore, "翻页游标也来自快照")

        // 接着翻页用的是快照的 next_cursor
        api.timelinePages = [.success(makePage([makeItem(id: 3)], next: nil))]
        await store.loadMore()
        #expect(api.timelineCalls.map(\.cursor) == ["c-snap"])
        #expect(store.items.tgIDs == [5, 4, 3])
    }

    @Test("preferSnapshot：无快照 / 空快照 → 照常走网络，返回 false")
    func preferSnapshotFallsBackToNetwork() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }

        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 9)], head: "h-net"))]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "k")
        #expect(await store.loadInitial(preferSnapshot: true) == false)
        #expect(store.items.tgIDs == [9])

        cache.save(makePage([], head: "h-empty"), key: "k2")
        let api2 = StubAPI()
        api2.timelinePages = [.success(makePage([makeItem(id: 8)], head: "h-net2"))]
        let store2 = TimelineStore(api: api2, cache: cache, cacheKey: "k2")
        #expect(await store2.loadInitial(preferSnapshot: true) == false, "空快照不算现场")
        #expect(store2.items.tgIDs == [8])
    }

    @Test("persistSnapshot：写回当前已加载的全部页 + 本地已读标记；loadMore 后快照自动跟着长")
    func persistSnapshotWritesCurrentList() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeItem(id: 5), makeItem(id: 4)], next: "c2", head: "h1")),
            .success(makePage([makeItem(id: 3), makeItem(id: 2)], next: "c3")),
        ]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "k")
        await store.loadInitial()
        await store.loadMore()
        let afterMore = cache.load(TimelinePage.self, key: "k")
        #expect(afterMore?.items.tgIDs == [5, 4, 3, 2], "翻页后快照含两页")
        #expect(afterMore?.nextCursor == "c3")
        #expect(afterMore?.headCursor == "h1")

        store.markLocallyRead(["tg:1:5", "tg:1:4"])
        store.persistSnapshot()
        let persisted = cache.load(TimelinePage.self, key: "k")
        #expect(persisted?.items.map(\.isRead) == [true, true, false, false])
    }

    @Test("persistSnapshot 超过上限：截到最后一个装得下的页边界，next_cursor 用那一页的")
    func persistSnapshotCapsAtPageBoundary() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        let api = StubAPI()
        api.timelinePages = [
            .success(makePage([makeItem(id: 9), makeItem(id: 8)], next: "c2", head: "h1")),
            .success(makePage([makeItem(id: 7), makeItem(id: 6)], next: "c3")),
            .success(makePage([makeItem(id: 5), makeItem(id: 4)], next: "c4")),
        ]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "k", snapshotItemCap: 5)
        await store.loadInitial()
        await store.loadMore()
        await store.loadMore()
        #expect(store.items.count == 6)
        let persisted = cache.load(TimelinePage.self, key: "k")
        #expect(persisted?.items.tgIDs == [9, 8, 7, 6], "6 > 5，退到第二页边界")
        #expect(persisted?.nextCursor == "c3", "接着翻页从第三页开始，不漏不重")
        #expect(persisted?.headCursor == "h1")
    }

    @Test("未加载过 / 空列表 / 无 cache 的 store：persistSnapshot 什么也不写")
    func persistSnapshotNoops() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        let store = TimelineStore(api: StubAPI(), cache: cache, cacheKey: "k")
        store.persistSnapshot()
        #expect(cache.load(TimelinePage.self, key: "k") == nil)
    }

    @Test("无快照 → 行为与原来一致；成功后写入快照")
    func noSnapshotStillSaves() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 3)], head: "h1"))]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "timeline-all")
        await store.loadInitial()
        #expect(store.items.tgIDs == [3])
        #expect(cache.load(TimelinePage.self, key: "timeline-all")?.items.tgIDs == [3])
    }

    @Test("不配 cache 的 store 不受影响")
    func withoutCache() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 3)]))]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        #expect(store.items.tgIDs == [3])
    }

    // 2026-09-07 起 loadInitial 不再返回「相对快照的新条目数」——那个数字改由
    // NewContentChecker 问 /timeline/new/count；返回值现在是「是否停在了快照上」。

    @Test("非 preferSnapshot 的冷启动：快照只是占位，网络替换后返回 false")
    func loadInitialNetworkPathReturnsFalse() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeItem(id: 3), makeItem(id: 2)], head: "h1"), key: "k")

        let api = StubAPI()
        api.timelinePages = [.success(makePage(
            [makeItem(id: 5), makeItem(id: 4), makeItem(id: 3)], next: "c2", head: "h2"))]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "k")
        #expect(await store.loadInitial() == false)
        #expect(store.items.tgIDs == [5, 4, 3])
        #expect(store.headCursor == "h2")
    }

    @Test("重复 loadInitial 是 no-op（快照路径也一样），不再打网络")
    func loadInitialTwice() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeItem(id: 2)], head: "h1"), key: "k")

        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeItem(id: 3), makeItem(id: 2)]))]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "k")
        #expect(await store.loadInitial() == false)
        #expect(await store.loadInitial() == false)
        #expect(api.timelineCalls.count == 1)

        let restored = TimelineStore(api: StubAPI(), cache: cache, cacheKey: "k")
        #expect(await restored.loadInitial(preferSnapshot: true) == true)
        #expect(await restored.loadInitial(preferSnapshot: true) == false, "第二次不算恢复")
    }
}
