import Foundation
import Testing
@testable import CondenserKit

// RecordsStore（收藏列表）：加载、刷新替换、unsave 乐观移除 + 失败按原位回滚、
// 401 回调、普通失败保留内容。

@MainActor
@Suite("RecordsStore")
struct RecordsStoreTests {
    @Test("loadInitial → 列表内容；再次调用不重复请求")
    func initialLoad() async {
        let api = StubAPI()
        api.recordsResults = [.success([makeMsg(id: 2, isSaved: true), makeMsg(id: 1, isSaved: true)])]
        let store = RecordsStore(api: api)
        await store.loadInitial()
        #expect(store.items.map(\.id) == [2, 1])
        #expect(store.error == nil)
        await store.loadInitial()
        #expect(api.recordsCalls == 1, "loadInitial 只加载一次")
    }

    @Test("refresh 重新拉取并替换")
    func refreshReplaces() async {
        let api = StubAPI()
        api.recordsResults = [
            .success([makeMsg(id: 1, isSaved: true)]),
            .success([makeMsg(id: 3, isSaved: true), makeMsg(id: 1, isSaved: true)]),
        ]
        let store = RecordsStore(api: api)
        await store.loadInitial()
        await store.refresh()
        #expect(store.items.map(\.id) == [3, 1])
    }

    @Test("unsave 乐观移除 + DELETE 发出")
    func unsaveRemoves() async {
        let api = StubAPI()
        api.recordsResults = [.success([makeMsg(id: 2, isSaved: true), makeMsg(id: 1, isSaved: true)])]
        let store = RecordsStore(api: api)
        await store.loadInitial()
        await store.unsave(store.items[0])
        #expect(store.items.map(\.id) == [1])
        #expect(api.deleteCalls == [MsgRef(channelID: 1, messageID: 2)])
    }

    @Test("unsave 失败 → 按原位置放回")
    func unsaveRollsBack() async {
        let api = StubAPI()
        api.recordsResults = [.success([
            makeMsg(id: 3, isSaved: true), makeMsg(id: 2, isSaved: true), makeMsg(id: 1, isSaved: true),
        ])]
        let store = RecordsStore(api: api)
        await store.loadInitial()
        api.recordError = APIError.http(status: 500, detail: nil)
        await store.unsave(store.items[1])
        #expect(store.items.map(\.id) == [3, 2, 1], "失败回滚保持原顺序")
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
            .success([makeMsg(id: 1, isSaved: true)]),
            .failure(APIError.http(status: 500, detail: "boom")),
        ]
        let store = RecordsStore(api: api)
        await store.loadInitial()
        await store.refresh()
        #expect(store.items.map(\.id) == [1])
        #expect(store.error == "boom")
    }
}
