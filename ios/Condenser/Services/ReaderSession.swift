import Foundation
import Observation
import CondenserKit

/// 登录后的组合根：持有 APIClient + TimelineStore / ReadReporter / NewContentPoller，
/// 统一把 401 接到 AuthSession.handleUnauthorized。unreadOnly 切换时重建
/// timeline + poller（两者的过滤参数必须一致，见 timeline.py:query_new 注释）。
@MainActor
@Observable
final class ReaderSession {
    let api: APIClient
    private(set) var timeline: TimelineStore
    private(set) var readReporter: ReadReporter
    private(set) var poller: NewContentPoller!
    private(set) var subscriptions: [Subscription] = []
    private(set) var unreadOnly = false

    private let onUnauthorized: @MainActor () -> Void

    init(server: URL, token: String, onUnauthorized: @escaping @MainActor () -> Void) {
        let api = APIClient(baseURL: server, token: token)
        self.api = api
        self.onUnauthorized = onUnauthorized
        timeline = TimelineStore(api: api)
        readReporter = ReadReporter(api: api)
        timeline.onUnauthorized = onUnauthorized
        readReporter.onUnauthorized = onUnauthorized
        poller = makePoller()
    }

    func setUnreadOnly(_ value: Bool) {
        guard value != unreadOnly else { return }
        unreadOnly = value
        poller.stop()
        timeline = TimelineStore(api: api, unreadOnly: value)
        timeline.onUnauthorized = onUnauthorized
        poller = makePoller()
        poller.start()
    }

    private func makePoller() -> NewContentPoller {
        let poller = NewContentPoller(api: api, unreadOnly: unreadOnly) { [weak self] in
            self?.timeline.headCursor
        }
        poller.onUnauthorized = onUnauthorized
        return poller
    }

    /// 频道名/username join 数据源（timeline item 只带 channel_id）
    func loadSubscriptions() async {
        do {
            subscriptions = try await api.subscriptions()
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
}
