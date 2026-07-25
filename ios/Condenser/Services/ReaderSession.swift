import Foundation
import Observation
import CondenserKit

/// 登录后的组合根：持有 APIClient + TimelineStore / RecordsStore / ReadReporter /
/// NewContentChecker + SnapshotCache，统一把 401 接到 AuthSession.handleUnauthorized。
/// unreadOnly / selectedSource 切换时重建 timeline + checker（两者的过滤参数必须一致，
/// 见 timeline.py:query_new 注释）。主 timeline 默认只看未读；每个 (source, unread)
/// 组合各落一份冷启动快照；频道/单 feed 视图是临时态，不落快照。
/// 订阅数据源是 GET /api/sources（信源菜单、订阅 tab、频道名 join 的唯一来源）。
@MainActor
@Observable
final class ReaderSession {
    let api: APIClient
    private(set) var timeline: TimelineStore
    private(set) var records: RecordsStore
    private(set) var readReporter: ReadReporter
    private(set) var newContentChecker: NewContentChecker!
    /// 已添加的信源分组（GET /api/sources）
    private(set) var sources: [SourceGroup] = []
    private(set) var unreadOnly = true
    /// nil = 全部信源；"telegram" / "hn" = 单信源视图
    private(set) var selectedSource: String?

    private let snapshots = SnapshotCache()
    private let onUnauthorized: @MainActor () -> Void

    init(server: URL, token: String, onUnauthorized: @escaping @MainActor () -> Void) {
        let api = APIClient(baseURL: server, token: token)
        self.api = api
        self.onUnauthorized = onUnauthorized
        timeline = TimelineStore(
            api: api, unreadOnly: true, cache: snapshots,
            cacheKey: Self.timelineKey(source: nil, unreadOnly: true))
        records = RecordsStore(api: api)
        readReporter = ReadReporter(api: api)
        timeline.onUnauthorized = onUnauthorized
        records.onUnauthorized = onUnauthorized
        readReporter.onUnauthorized = onUnauthorized
        sources = snapshots.load([SourceGroup].self, key: "sources") ?? []
        newContentChecker = makeChecker()
    }

    func setUnreadOnly(_ value: Bool) {
        guard value != unreadOnly else { return }
        unreadOnly = value
        rebuildTimeline()
    }

    /// 信源切换器（Timeline 顶部左侧 Menu）
    func setSource(_ source: String?) {
        guard source != selectedSource else { return }
        selectedSource = source
        rebuildTimeline()
    }

    private func rebuildTimeline() {
        timeline = TimelineStore(
            api: api, unreadOnly: unreadOnly, source: selectedSource, cache: snapshots,
            cacheKey: Self.timelineKey(source: selectedSource, unreadOnly: unreadOnly))
        timeline.onUnauthorized = onUnauthorized
        newContentChecker = makeChecker()
    }

    private static func timelineKey(source: String?, unreadOnly: Bool) -> String {
        "timeline-\(source ?? "all")-\(unreadOnly ? "unread" : "all")"
    }

    private func makeChecker() -> NewContentChecker {
        let checker = NewContentChecker(
            api: api, unreadOnly: unreadOnly, source: selectedSource
        ) { [weak self] in
            self?.timeline.headCursor
        }
        checker.onUnauthorized = onUnauthorized
        return checker
    }

    /// 订阅 tab push 进来的单频道 timeline（无快照、无轮询）
    func makeChannelStore(channelID: Int) -> TimelineStore {
        let store = TimelineStore(api: api, channelID: channelID)
        store.onUnauthorized = onUnauthorized
        return store
    }

    /// 订阅 tab push 进来的 HN feed timeline（v1 单 feed = source 全量视图）
    func makeHnStore() -> TimelineStore {
        let store = TimelineStore(api: api, source: SourceID.hn)
        store.onUnauthorized = onUnauthorized
        return store
    }

    /// 订阅 tab push 进来的单个 X feed（For You 或某个关注人）；
    /// For You 只能从这里进——它不在聚合流里
    func makeXStore(feed: String) -> TimelineStore {
        let store = TimelineStore(api: api, source: SourceID.x, feed: feed)
        store.onUnauthorized = onUnauthorized
        return store
    }

    /// 信源/订阅数据源；成功后落快照，冷启动先用快照渲染
    func loadSources() async {
        do {
            sources = try await api.sources()
            snapshots.save(sources, key: "sources")
        } catch APIError.unauthorized {
            onUnauthorized()
        } catch {
            // 标签降级为频道 id 展示，不阻塞阅读
        }
    }

    var telegramSubs: [SourceSub] {
        sources.first { $0.source == SourceID.telegram }?.subscriptions ?? []
    }

    var hnSubs: [SourceSub] {
        sources.first { $0.source == SourceID.hn }?.subscriptions ?? []
    }

    var xSubs: [SourceSub] {
        sources.first { $0.source == SourceID.x }?.subscriptions ?? []
    }

    func telegramSub(for channelID: Int) -> SourceSub? {
        telegramSubs.first { $0.channelID.intValue == channelID }
    }

    func channelTitle(for channelID: Int) -> String {
        telegramSub(for: channelID)?.name ?? "频道 \(channelID)"
    }

    /// records 条目自包含 channel 快照，优先于 sources join
    func channelTitle(for message: DisplayMessage) -> String {
        message.channel?.title ?? channelTitle(for: message.channelID)
    }

    func channelUsername(for message: DisplayMessage) -> String? {
        message.channel?.username ?? telegramSub(for: message.channelID)?.username
    }
}
