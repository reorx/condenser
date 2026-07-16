import Foundation
import Observation

/// Timeline 游标分页状态机（date-desc）。同一个类型服务 All/Unread/单频道视图
/// （channelID/unreadOnly 定死在实例上）。错误在此层收敛：401 走 onUnauthorized，
/// 其余进 error 文案且保留已有内容。
@MainActor
@Observable
public final class TimelineStore {
    public private(set) var items: [DisplayMessage] = []
    public private(set) var isLoading = false
    public private(set) var isLoadingMore = false
    public private(set) var hasMore = true
    /// 首页最新单元锚点，供 /timeline/new 轮询
    public private(set) var headCursor: String?
    public var error: String?

    /// 401 时触发（app 层接 AuthSession.handleUnauthorized）
    public var onUnauthorized: (@MainActor () -> Void)?

    public let channelID: Int?
    public let unreadOnly: Bool
    private let api: CondenserAPI
    private let pageSize: Int
    private let cache: SnapshotCache?
    private let cacheKey: String?
    private var nextCursor: String?
    private var loadedOnce = false

    public init(
        api: CondenserAPI, channelID: Int? = nil, unreadOnly: Bool = false, pageSize: Int = 30,
        cache: SnapshotCache? = nil, cacheKey: String? = nil
    ) {
        self.api = api
        self.channelID = channelID
        self.unreadOnly = unreadOnly
        self.pageSize = pageSize
        self.cache = cache
        self.cacheKey = cacheKey
    }

    /// 首次加载；已加载过则无操作（refresh 负责重载）。
    /// 配了 cache 时冷启动先渲染快照，网络成功后整页替换。
    public func loadInitial() async {
        guard !loadedOnce, !isLoading else { return }
        if items.isEmpty, let cache, let cacheKey,
           let snapshot = cache.load(TimelinePage.self, key: cacheKey) {
            apply(page: snapshot)
        }
        await loadFirstPage()
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
                unreadOnly: unreadOnly)
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
        headCursor = page.headCursor
        hasMore = page.nextCursor != nil
    }

    public func loadMore() async {
        guard hasMore, !isLoadingMore, !isLoading, let cursor = nextCursor else { return }
        isLoadingMore = true
        do {
            let page = try await api.timeline(
                cursor: cursor, limit: pageSize, channelID: channelID, date: nil,
                unreadOnly: unreadOnly)
            let seen = Set(items.map(\.unitKey))
            items.append(contentsOf: page.items.filter { !seen.contains($0.unitKey) })
            nextCursor = page.nextCursor
            hasMore = page.nextCursor != nil
        } catch {
            handle(error)
        }
        isLoadingMore = false
    }

    /// 收藏乐观切换；失败回滚（错误文案交给调用方 toast）
    public func toggleSaved(_ message: DisplayMessage) async {
        guard let index = items.firstIndex(where: { $0.unitKey == message.unitKey }) else { return }
        let wasSaved = items[index].isSaved ?? false
        items[index].isSaved = !wasSaved
        do {
            if wasSaved {
                try await api.deleteRecord(message.ref)
            } else {
                try await api.saveRecord(message.ref)
            }
        } catch {
            if let rollback = items.firstIndex(where: { $0.unitKey == message.unitKey }) {
                items[rollback].isSaved = wasSaved
            }
            handle(error)
        }
    }

    /// 本地已读标记（ReadReporter 乐观置位用，不发请求）
    public func markLocallyRead(_ refs: Set<MsgRef>) {
        for index in items.indices where refs.contains(items[index].ref) {
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
