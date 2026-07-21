import Foundation
import Testing
@testable import CondenserKit

// RecordsStore（收藏列表，envelope）：加载、刷新替换、unsave 乐观移除（按 item key）
// + 失败按原位回滚、401 回调、普通失败保留内容。HN 条目与 TG 条目同列表。

@MainActor
@Suite("RecordsStore")
struct RecordsStoreTests {
    @Test("loadInitial → 列表内容；再次调用不重复请求")
    func initialLoad() async {
        let api = StubAPI()
        api.recordsResults = [.success([makeItem(id: 2, isSaved: true), makeHnItem(id: 900)])]
        let store = RecordsStore(api: api)
        await store.loadInitial()
        #expect(store.items.map(\.key) == ["tg:1:2", "hn:900"])
        #expect(store.error == nil)
        await store.loadInitial()
        #expect(api.recordsCalls == 1, "loadInitial 只加载一次")
    }

    @Test("refresh 重新拉取并替换")
    func refreshReplaces() async {
        let api = StubAPI()
        api.recordsResults = [
            .success([makeItem(id: 1, isSaved: true)]),
            .success([makeItem(id: 3, isSaved: true), makeItem(id: 1, isSaved: true)]),
        ]
        let store = RecordsStore(api: api)
        await store.loadInitial()
        await store.refresh()
        #expect(store.items.tgIDs == [3, 1])
    }

    @Test("unsave 乐观移除 + DELETE 按 key 发出（HN 条目同样生效）")
    func unsaveRemoves() async {
        let api = StubAPI()
        api.recordsResults = [.success([makeHnItem(id: 900), makeItem(id: 1, isSaved: true)])]
        let store = RecordsStore(api: api)
        await store.loadInitial()
        await store.unsave(store.items[0])
        #expect(store.items.map(\.key) == ["tg:1:1"])
        #expect(api.deleteCalls == ["hn:900"])
    }

    @Test("unsave 失败 → 按原位置放回")
    func unsaveRollsBack() async {
        let api = StubAPI()
        api.recordsResults = [.success([
            makeItem(id: 3, isSaved: true), makeItem(id: 2, isSaved: true), makeItem(id: 1, isSaved: true),
        ])]
        let store = RecordsStore(api: api)
        await store.loadInitial()
        api.recordError = APIError.http(status: 500, detail: nil)
        await store.unsave(store.items[1])
        #expect(store.items.tgIDs == [3, 2, 1], "失败回滚保持原顺序")
        #expect(store.error != nil)
    }

    @Test("401 → onUnauthorized 回调")
    func unauthorized() async {
        let api = StubAPI()
        api.recordsResults = [.failure(APIError.unauthorized)]
        let store = RecordsStore(api: api)
        var fired = false
        store.onUnauthorized = { fired = true }
        await store.loadInitial()
        #expect(fired)
        #expect(store.error == nil)
    }

    @Test("刷新失败 → error 文案，已有内容保留")
    func failureKeepsContent() async {
        let api = StubAPI()
        api.recordsResults = [
            .success([makeItem(id: 1, isSaved: true)]),
            .failure(APIError.http(status: 500, detail: "boom")),
        ]
        let store = RecordsStore(api: api)
        await store.loadInitial()
        await store.refresh()
        #expect(store.items.tgIDs == [1])
        #expect(store.error == "boom")
    }
}
