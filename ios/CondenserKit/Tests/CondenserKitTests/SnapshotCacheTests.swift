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
}
