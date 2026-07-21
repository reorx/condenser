import Foundation
import Observation

/// 新内容轮询：GET /api/timeline/new?after=<head_cursor>，发布未读新消息计数。
/// start() 立即查一次再按 interval 循环（scenePhase 回到 active 时 app 层重新 start）；
/// 请求失败静默保留旧计数（下一轮自然纠正）。
@MainActor
@Observable
public final class NewContentPoller {
    public private(set) var count = 0
    /// 401 时触发（app 层接 AuthSession.handleUnauthorized）
    public var onUnauthorized: (@MainActor () -> Void)?

    private let api: CondenserAPI
    private let channelID: Int?
    private let unreadOnly: Bool
    private let source: String?
    private let interval: Duration
    private let headCursor: @MainActor () -> String?
    private var loopTask: Task<Void, Never>?

    public init(
        api: CondenserAPI,
        channelID: Int? = nil,
        unreadOnly: Bool = false,
        source: String? = nil,
        interval: Duration = .seconds(30),
        headCursor: @escaping @MainActor () -> String?
    ) {
        self.api = api
        self.channelID = channelID
        self.unreadOnly = unreadOnly
        self.source = source
        self.interval = interval
        self.headCursor = headCursor
    }

    public func start() {
        stop()
        loopTask = Task { [interval] in
            while !Task.isCancelled {
                await checkNow()
                try? await Task.sleep(for: interval)
            }
        }
    }

    public func stop() {
        loopTask?.cancel()
        loopTask = nil
    }

    /// 刷新完成后清胶囊
    public func reset() {
        count = 0
    }

    public func checkNow() async {
        guard let after = headCursor() else { return }
        do {
            let new = try await api.timelineNew(
                after: after, channelID: channelID, limit: 100, unreadOnly: unreadOnly,
                source: source)
            count = new.count
        } catch APIError.unauthorized {
            onUnauthorized?()
        } catch {
            // 瞬时失败忽略，保留旧计数
        }
    }
}
