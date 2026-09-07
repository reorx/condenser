import Foundation
import Testing
@testable import CondenserKit

// ReadingState / ReadingStateStore：启动时恢复「上次读到哪」的持久化状态
// （plan 2026-09-07）。tab、主 timeline 的信源/未读开关、订阅 tab 推入的 feed、
// 每个列表（按 scopeKey）的顶部可见条目 + 打开的详情 sheet。

@Suite("ReadingState")
struct ReadingStateTests {
    private func makeDefaults() -> UserDefaults {
        let name = "reading-state-tests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        defaults.removePersistentDomain(forName: name)
        return defaults
    }

    @Test("空存储 → 默认状态（timeline tab、All、只看未读）")
    func emptyDefaults() {
        let store = ReadingStateStore(defaults: makeDefaults())
        #expect(store.state == ReadingState())
        #expect(store.state.tab == "timeline")
        #expect(store.state.source == nil)
        #expect(store.state.unreadOnly == true)
        #expect(store.state.pushed == nil)
        #expect(store.state.lists.isEmpty)
    }

    @Test("写入后另一个实例读回同一值")
    func roundTrip() {
        let defaults = makeDefaults()
        let store = ReadingStateStore(defaults: defaults)
        store.update { state in
            state.tab = "subscriptions"
            state.source = SourceID.hn
            state.unreadOnly = false
            state.pushed = PushedDestination(
                kind: .xFeed,
                sub: SourceSub(channelID: .string("foryou"), name: "For You", username: nil, enabled: true, unread: 3))
        }
        store.rememberList("all-unread", top: "tg:1:42", open: "tg:1:41")

        let reloaded = ReadingStateStore(defaults: defaults)
        #expect(reloaded.state.tab == "subscriptions")
        #expect(reloaded.state.source == SourceID.hn)
        #expect(reloaded.state.unreadOnly == false)
        #expect(reloaded.state.pushed?.kind == .xFeed)
        #expect(reloaded.state.pushed?.sub.channelID.description == "foryou")
        #expect(reloaded.state.lists["all-unread"]?.topItemKey == "tg:1:42")
        #expect(reloaded.state.lists["all-unread"]?.openItemKey == "tg:1:41")
    }

    @Test("rememberList 只改传入的字段：top 与 open 各自独立更新")
    func rememberListIsPartial() {
        let store = ReadingStateStore(defaults: makeDefaults())
        store.rememberList("k", top: "a", open: nil)
        store.rememberList("k", open: "sheet")
        #expect(store.state.lists["k"]?.topItemKey == "a")
        #expect(store.state.lists["k"]?.openItemKey == "sheet")
        store.rememberList("k", open: .some(nil))
        #expect(store.state.lists["k"]?.topItemKey == "a")
        #expect(store.state.lists["k"]?.openItemKey == nil)
    }

    @Test("列表状态容量有限：超过上限淘汰最久未更新的")
    func listsAreCapped() {
        let store = ReadingStateStore(defaults: makeDefaults())
        let base = Date(timeIntervalSince1970: 1_784_000_000)
        for i in 0..<(ReadingState.maxLists + 5) {
            store.rememberList("k\(i)", top: "t", now: base.addingTimeInterval(Double(i)))
        }
        #expect(store.state.lists.count == ReadingState.maxLists)
        #expect(store.state.lists["k0"] == nil, "最早的被淘汰")
        #expect(store.state.lists["k\(ReadingState.maxLists + 4)"] != nil, "最新的保留")
    }

    @Test("损坏的存储值 → 默认状态，不 crash")
    func corruptValueIsDefault() {
        let defaults = makeDefaults()
        defaults.set(Data("nope{{".utf8), forKey: ReadingStateStore.key)
        let store = ReadingStateStore(defaults: defaults)
        #expect(store.state == ReadingState())
    }

    @Test("PushedDestination 四种 kind 都能编解码")
    func pushedKinds() throws {
        let sub = SourceSub(channelID: .int(-1001), name: "C", username: "c", enabled: true, unread: 0)
        for kind in PushedDestination.Kind.allCases {
            let dest = PushedDestination(kind: kind, sub: sub)
            let data = try JSONEncoder().encode(dest)
            #expect(try JSONDecoder().decode(PushedDestination.self, from: data) == dest)
        }
    }
}
