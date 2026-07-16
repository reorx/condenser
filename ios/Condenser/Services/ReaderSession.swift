import Foundation
import Observation
import CondenserKit

/// 登录后的组合根：持有 APIClient + TimelineStore / RecordsStore / ReadReporter /
/// NewContentPoller + SnapshotCache，统一把 401 接到 AuthSession.handleUnauthorized。
/// unreadOnly 切换时重建 timeline + poller（两者的过滤参数必须一致，见
/// timeline.py:query_new 注释）。快照只服务冷启动的主 timeline（All 视图）与
/// subscriptions；未读/频道视图是临时态，不落快照。
@MainActor
@Observable
final class ReaderSession {
    let api: APIClient
    private(set) var timeline: TimelineStore
    private(set) var records: RecordsStore
    private(set) var readReporter: ReadReporter
    private(set) var poller: NewContentPoller!
    private(set) var subscriptions: [Subscription] = []
    private(set) var unreadOnly = false

    private let snapshots = SnapshotCache()
    private let onUnauthorized: @MainActor () -> Void

    private enum SnapshotKeys {
        static let timeline = "timeline-all"
        static let subscriptions = "subscriptions"
    }

    init(server: URL, token: String, onUnauthorized: @escaping @MainActor () -> Void) {
        let api = APIClient(baseURL: server, token: token)
        self.api = api
        self.onUnauthorized = onUnauthorized
        timeline = TimelineStore(
            api: api, cache: snapshots, cacheKey: SnapshotKeys.timeline)
        records = RecordsStore(api: api)
        readReporter = ReadReporter(api: api)
        timeline.onUnauthorized = onUnauthorized
        records.onUnauthorized = onUnauthorized
        readReporter.onUnauthorized = onUnauthorized
        subscriptions = snapshots.load([Subscription].self, key: SnapshotKeys.subscriptions) ?? []
        poller = makePoller()
    }

    func setUnreadOnly(_ value: Bool) {
        guard value != unreadOnly else { return }
        unreadOnly = value
        poller.stop()
        timeline = TimelineStore(
            api: api, unreadOnly: value,
            cache: value ? nil : snapshots, cacheKey: value ? nil : SnapshotKeys.timeline)
        timeline.onUnauthorized = onUnauthorized
        poller = makePoller()
        poller.start()
    }

    /// 频道 tab push 进来的单频道 timeline（无快照、无轮询）
    func makeChannelStore(channelID: Int) -> TimelineStore {
        let store = TimelineStore(api: api, channelID: channelID)
        store.onUnauthorized = onUnauthorized
        return store
    }

    private func makePoller() -> NewContentPoller {
        let poller = NewContentPoller(api: api, unreadOnly: unreadOnly) { [weak self] in
            self?.timeline.headCursor
        }
        poller.onUnauthorized = onUnauthorized
        return poller
    }

    /// 频道名/username join 数据源（timeline item 只带 channel_id）；
    /// 成功后落快照，冷启动先用快照渲染
    func loadSubscriptions() async {
        do {
            subscriptions = try await api.subscriptions()
            snapshots.save(subscriptions, key: SnapshotKeys.subscriptions)
        } catch APIError.unauthorized {
            onUnauthorized()
        } catch {
            // 标签降级为频道 id 展示，不阻塞阅读
        }
    }

    func subscription(for channelID: Int) -> Subscription? {
        subscriptions.first { $0.channelID == channelID }
    }

    func channelTitle(for channelID: Int) -> String {
        subscription(for: channelID)?.title ?? "频道 \(channelID)"
    }

    /// records 条目自包含 channel 快照，优先于 subscriptions join
    func channelTitle(for message: DisplayMessage) -> String {
        message.channel?.title ?? channelTitle(for: message.channelID)
    }

    func channelUsername(for message: DisplayMessage) -> String? {
        message.channel?.username ?? subscription(for: message.channelID)?.username
    }
}
