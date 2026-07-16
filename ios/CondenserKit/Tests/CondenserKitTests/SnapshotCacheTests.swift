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
        let page = makePage([makeMsg(id: 1), makeMsg(id: 2)], next: "c2", head: "h1")
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
        cache.save(makePage([makeMsg(id: 1)]), key: "timeline-all")
        try Data("not json{{{".utf8).write(to: cache.fileURL(for: "timeline-all"))
        #expect(cache.load(TimelinePage.self, key: "timeline-all") == nil)
    }

    @Test("同 key 覆盖写，读到最新值")
    func overwrite() {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeMsg(id: 1)]), key: "k")
        cache.save(makePage([makeMsg(id: 9)]), key: "k")
        #expect(cache.load(TimelinePage.self, key: "k")?.items.map(\.id) == [9])
    }

    @Test("remove 后读不到")
    func removeKey() {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeMsg(id: 1)]), key: "k")
        cache.remove(key: "k")
        #expect(cache.load(TimelinePage.self, key: "k") == nil)
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
        cache.save(makePage([makeMsg(id: 5)], next: "c-snap", head: "h-snap"), key: "timeline-all")

        let api = StubAPI()
        api.timelinePages = [.failure(APIError.http(status: 500, detail: "boom"))]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "timeline-all")
        await store.loadInitial()
        #expect(store.items.map(\.id) == [5], "网络失败也能读快照")
        #expect(store.headCursor == "h-snap")
        #expect(store.error != nil)
    }

    @Test("冷启动：网络成功后替换快照内容并回写缓存")
    func networkReplacesSnapshotAndSaves() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        cache.save(makePage([makeMsg(id: 5)]), key: "timeline-all")

        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeMsg(id: 9), makeMsg(id: 8)], next: "c2", head: "h2"))]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "timeline-all")
        await store.loadInitial()
        #expect(store.items.map(\.id) == [9, 8])
        #expect(cache.load(TimelinePage.self, key: "timeline-all")?.items.map(\.id) == [9, 8],
                "新首页回写快照")
    }

    @Test("无快照 → 行为与原来一致；成功后写入快照")
    func noSnapshotStillSaves() async {
        let (cache, dir) = makeCache()
        defer { try? FileManager.default.removeItem(at: dir) }
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeMsg(id: 3)], head: "h1"))]
        let store = TimelineStore(api: api, cache: cache, cacheKey: "timeline-all")
        await store.loadInitial()
        #expect(store.items.map(\.id) == [3])
        #expect(cache.load(TimelinePage.self, key: "timeline-all")?.items.map(\.id) == [3])
    }

    @Test("不配 cache 的 store 不受影响")
    func withoutCache() async {
        let api = StubAPI()
        api.timelinePages = [.success(makePage([makeMsg(id: 3)]))]
        let store = TimelineStore(api: api)
        await store.loadInitial()
        #expect(store.items.map(\.id) == [3])
    }
}
