import Foundation
import Observation

/// Timeline 游标分页状态机（date-desc，多信源 envelope）。同一个类型服务
/// All/单信源/单频道视图（channelID/unreadOnly/source 定死在实例上）。
/// 错误在此层收敛：401 走 onUnauthorized，其余进 error 文案且保留已有内容。
@MainActor
@Observable
public final class TimelineStore {
    public private(set) var items: [TimelineItem] = []
    public private(set) var isLoading = false
    public private(set) var isLoadingMore = false
    public private(set) var hasMore = true
    /// fetch-older 进行中（底部上拉触发的后端拉取）
    public private(set) var isFetchingOlder = false
    /// 上次 fetch-older 返回 0：Telegram 上也没有更早的消息了
    public private(set) var olderExhausted = false
    /// 首页最新单元锚点，供 /timeline/new 轮询
    public private(set) var headCursor: String?
    public var error: String?

    /// 401 时触发（app 层接 AuthSession.handleUnauthorized）
    public var onUnauthorized: (@MainActor () -> Void)?

    public let channelID: Int?
    public let unreadOnly: Bool
    /// nil = 全部启用的信源；"telegram" / "hn" / "x" = 单信源视图
    public let source: String?
    /// 多 feed 信源（X）里的单个 feed；For You 只能从这条路进（不进聚合流）
    public let feed: String?
    private let api: CondenserAPI
    private let pageSize: Int
    private let cache: SnapshotCache?
    private let cacheKey: String?
    private let snapshotItemCap: Int
    private var nextCursor: String?
    /// 已加载内容最后一个单元的锚点：本地到底后仍存在，fetch-older 之后用它续接
    private var endCursor: String?
    private var loadedOnce = false
    /// 每页结束时的 (已加载条数, 下一页游标)：persistSnapshot 截断到某一页的边界时，
    /// 要拿得到那一页的 next_cursor，否则快照接着翻页会跳过一段
    private var pageEnds: [(count: Int, cursor: String?)] = []

    public init(
        api: CondenserAPI, channelID: Int? = nil, unreadOnly: Bool = false,
        source: String? = nil, feed: String? = nil, pageSize: Int = 30,
        cache: SnapshotCache? = nil, cacheKey: String? = nil, snapshotItemCap: Int = 300
    ) {
        self.api = api
        self.channelID = channelID
        self.unreadOnly = unreadOnly
        self.source = source
        self.feed = feed
        self.pageSize = pageSize
        self.cache = cache
        self.cacheKey = cacheKey
        self.snapshotItemCap = snapshotItemCap
    }

    /// 这个列表的身份，`ReadingState.lists` 按它落滚动锚点与打开的抽屉：
    /// 单频道 = `channel-<id>`，其余 = `<source|all>[|<feed>]|<unread|all>`
    public var scopeKey: String {
        if let channelID { return "channel-\(channelID)" }
        var parts = [source ?? "all"]
        if let feed { parts.append(feed) }
        parts.append(unreadOnly ? "unread" : "all")
        return parts.joined(separator: "|")
    }

    /// 首次加载；已加载过则无操作（refresh 负责重载）。
    /// 配了 cache 时先渲染快照；`preferSnapshot = true`（启动恢复现场，plan 2026-09-07）
    /// 且快照非空时**到此为止、不打网络**——快照就是上次离开时的列表，滚动锚点要在
    /// 它里面才找得到；有没有更新由 `NewContentChecker` 单独问一次、用胶囊告知。
    /// 否则（无快照 / 切信源重建的 store）快照只是首屏占位，网络成功后整页替换。
    /// 返回是否停在了快照上。
    @discardableResult
    public func loadInitial(preferSnapshot: Bool = false) async -> Bool {
        guard !loadedOnce, !isLoading else { return false }
        if items.isEmpty, let cache, let cacheKey,
           let snapshot = cache.load(TimelinePage.self, key: cacheKey) {
            apply(page: snapshot)
            if preferSnapshot, !snapshot.items.isEmpty {
                loadedOnce = true
                return true
            }
        }
        await loadFirstPage()
        return false
    }

    /// 把当前已加载的列表（本地已读标记在内）连同游标写回快照——退后台时调一次，
    /// 下次启动 `loadInitial(preferSnapshot:)` 读回来的就是这一刻的现场。
    /// 超过 `snapshotItemCap` 时截到最后一个装得下的**页边界**，next_cursor 用那一页的，
    /// 恢复后继续翻页不会漏掉一段。
    public func persistSnapshot() {
        guard let cache, let cacheKey, loadedOnce, !items.isEmpty else { return }
        var kept = items.count
        var next = nextCursor
        if items.count > snapshotItemCap,
           let boundary = pageEnds.last(where: { $0.count <= snapshotItemCap }) {
            kept = boundary.count
            next = boundary.cursor
        }
        let page = TimelinePage(
            items: Array(items.prefix(kept)), nextCursor: next, endCursor: next ?? endCursor,
            headCursor: headCursor)
        cache.save(page, key: cacheKey)
    }

    /// 重载第一页并替换内容、重置分页（下拉刷新 / 新消息胶囊点击）
    public func refresh() async {
        guard !isLoading else { return }
        await loadFirstPage()
    }

    private func loadFirstPage() async {
        isLoading = true
        error = nil
        do {
            let page = try await api.timeline(
                cursor: nil, limit: pageSize, channelID: channelID, date: nil,
                unreadOnly: unreadOnly, source: source, feed: feed)
            apply(page: page)
            loadedOnce = true
            if let cache, let cacheKey {
                cache.save(page, key: cacheKey)
            }
        } catch {
            handle(error)
        }
        isLoading = false
    }

    private func apply(page: TimelinePage) {
        items = page.items
        nextCursor = page.nextCursor
        endCursor = page.endCursor
        headCursor = page.headCursor
        hasMore = page.nextCursor != nil
        olderExhausted = false
        pageEnds = [(items.count, page.nextCursor)]
    }

    public func loadMore() async {
        guard hasMore, !isLoadingMore, !isLoading, let cursor = nextCursor else { return }
        isLoadingMore = true
        do {
            let page = try await api.timeline(
                cursor: cursor, limit: pageSize, channelID: channelID, date: nil,
                unreadOnly: unreadOnly, source: source, feed: feed)
            append(page: page)
            // 快照跟着长：恢复现场时滚动锚点可能在第 5 页
            persistSnapshot()
        } catch {
            handle(error)
        }
        isLoadingMore = false
    }

    private func append(page: TimelinePage) {
        let seen = Set(items.map(\.key))
        items.append(contentsOf: page.items.filter { !seen.contains($0.key) })
        nextCursor = page.nextCursor
        hasMore = page.nextCursor != nil
        if let cursor = page.endCursor {
            endCursor = cursor
        }
        pageEnds.append((items.count, page.nextCursor))
    }

    /// 本地历史走完后（hasMore=false），触发后端从 Telegram 拉更早消息，
    /// 再用 end_cursor 把新入库的历史接到列表尾部。仅频道视图有意义。
    public func fetchOlderFromServer(count: Int = 200) async {
        guard let channelID, !hasMore, !olderExhausted,
              !isFetchingOlder, !isLoading, !isLoadingMore else { return }
        isFetchingOlder = true
        error = nil
        do {
            let fetched = try await api.fetchOlder(channelID: channelID, count: count)
            if fetched == 0 {
                olderExhausted = true
            } else {
                let page = try await api.timeline(
                    cursor: endCursor, limit: pageSize, channelID: channelID, date: nil,
                    unreadOnly: unreadOnly, source: source, feed: feed)
                if endCursor == nil {
                    // 此前列表为空（无锚点）：当作第一页整页替换
                    apply(page: page)
                } else {
                    append(page: page)
                }
            }
        } catch {
            handle(error)
        }
        isFetchingOlder = false
    }

    /// 收藏乐观切换；失败回滚（错误文案交给调用方 toast）
    public func toggleSaved(_ item: TimelineItem) async {
        guard let index = items.firstIndex(where: { $0.key == item.key }) else { return }
        let wasSaved = items[index].isSaved
        items[index].isSaved = !wasSaved
        do {
            if wasSaved {
                try await api.deleteRecord(key: item.key)
            } else {
                try await api.saveRecord(key: item.key)
            }
        } catch {
            if let rollback = items.firstIndex(where: { $0.key == item.key }) {
                items[rollback].isSaved = wasSaved
            }
            handle(error)
        }
    }

    /// up/down 打标：乐观置位 + 失败回滚。点已选中的那一侧即撤销。
    /// 只记录标签——不隐藏、不标已读、不改排序（判定是服务端 ingest 时的事）。
    /// 拇指本身不带理由，所以这一下会清掉旧理由：换一侧是改正，过期的成因不该留下。
    public func setFeedback(_ item: TimelineItem, _ tapped: ItemFeedback) async {
        let next = ItemFeedback.next(current: item.feedback, tapped: tapped)
        await write(item, verdict: next, reason: nil)
    }

    /// 选理由 chip：verdict 保持 down（这不是第二次点拇指，不能撤销），
    /// 连同理由把整条标签重发一次。
    public func setReason(_ item: TimelineItem, _ reason: ItemFeedbackReason) async {
        await write(item, verdict: item.feedback ?? .down, reason: reason)
    }

    private func write(_ item: TimelineItem, verdict: ItemFeedback?, reason: ItemFeedbackReason?) async {
        guard let index = items.firstIndex(where: { $0.key == item.key }) else { return }
        let previous = (items[index].feedback, items[index].feedbackReason)
        items[index].feedback = verdict
        items[index].feedbackReason = verdict == nil ? nil : reason
        do {
            if let verdict {
                try await api.setFeedback(key: item.key, verdict: verdict, reason: reason)
            } else {
                try await api.clearFeedback(key: item.key)
            }
        } catch {
            if let rollback = items.firstIndex(where: { $0.key == item.key }) {
                (items[rollback].feedback, items[rollback].feedbackReason) = previous
            }
            handle(error)
        }
    }

    /// 本地已读标记（ReadReporter 乐观置位用，不发请求）
    public func markLocallyRead(_ keys: Set<String>) {
        for index in items.indices where keys.contains(items[index].key) {
            items[index].isRead = true
        }
    }

    private func handle(_ error: Error) {
        if case APIError.unauthorized = error {
            onUnauthorized?()
            return
        }
        if case let APIError.http(status, detail) = error {
            self.error = detail ?? "请求失败（\(status)）"
        } else {
            self.error = error.localizedDescription
        }
    }
}
