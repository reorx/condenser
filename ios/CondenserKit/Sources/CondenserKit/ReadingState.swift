import Foundation

/// 一个列表（按 `TimelineStore.scopeKey`）的阅读现场：顶部可见条目 + 打开的详情 sheet。
public struct ListState: Codable, Equatable, Sendable {
    /// 视口顶部那张卡片的 item key（`scrollPosition(id:)` 报的），恢复时滚到它
    public var topItemKey: String?
    /// 正开着的详情 sheet 的 item key；nil = 没开
    public var openItemKey: String?
    public var updatedAt: Date

    public init(topItemKey: String? = nil, openItemKey: String? = nil, updatedAt: Date) {
        self.topItemKey = topItemKey
        self.openItemKey = openItemKey
        self.updatedAt = updatedAt
    }
}

/// 订阅 tab 推入的单频道 / 单 feed 视图。带着整个 `SourceSub` 存，恢复时不必等
/// `/api/sources` 回来——推入的界面本来就是拿 sub 自足渲染的。
public struct PushedDestination: Codable, Equatable, Sendable {
    public enum Kind: String, Codable, CaseIterable, Sendable {
        case telegramChannel, hnFeed, xFeed, rssFeed
    }

    public let kind: Kind
    public let sub: SourceSub

    public init(kind: Kind, sub: SourceSub) {
        self.kind = kind
        self.sub = sub
    }
}

/// 启动时要恢复的「上次读到哪」（plan 2026-09-07）：哪个 tab、主 timeline 的信源过滤与
/// 未读开关、订阅 tab 推进去的 feed，以及每个列表各自的滚动锚点与打开的抽屉。
/// 内容本身不在这里——那是 `SnapshotCache` 的事；这里只有「指向内容的键」。
public struct ReadingState: Codable, Equatable, Sendable {
    /// 列表状态条目上限：每进一个单 feed 视图就多一条，不封顶会随订阅数无限长
    public static let maxLists = 32

    public var tab = "timeline"
    /// nil = All
    public var source: String?
    public var unreadOnly = true
    public var pushed: PushedDestination?
    public var lists: [String: ListState] = [:]

    public init() {}
}

/// `ReadingState` 的 UserDefaults 存取。每次改动即写（UserDefaults 自己合并落盘），
/// 损坏 / 缺失一律回默认值——这是便利，不是数据，丢了只是回到顶部。
public final class ReadingStateStore {
    public static let key = "condenser.readingState"

    public private(set) var state: ReadingState
    private let defaults: UserDefaults

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey: Self.key),
           let decoded = try? JSONDecoder().decode(ReadingState.self, from: data) {
            state = decoded
        } else {
            state = ReadingState()
        }
    }

    public func update(_ mutate: (inout ReadingState) -> Void) {
        mutate(&state)
        persist()
    }

    /// 只改传入的字段：`nil`（外层 none）= 不动，`.some(nil)` = 清掉。
    /// 超过 `ReadingState.maxLists` 时淘汰最久没更新的那条。
    public func rememberList(_ scope: String, top: String?? = nil, open: String?? = nil, now: Date = Date()) {
        var entry = state.lists[scope] ?? ListState(updatedAt: now)
        if let top { entry.topItemKey = top }
        if let open { entry.openItemKey = open }
        entry.updatedAt = now
        state.lists[scope] = entry
        while state.lists.count > ReadingState.maxLists,
              let oldest = state.lists.min(by: { $0.value.updatedAt < $1.value.updatedAt }) {
            state.lists.removeValue(forKey: oldest.key)
        }
        persist()
    }

    public func list(_ scope: String) -> ListState? {
        state.lists[scope]
    }

    private func persist() {
        guard let data = try? JSONEncoder().encode(state) else { return }
        defaults.set(data, forKey: Self.key)
    }
}
