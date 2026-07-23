import Foundation

/// 新内容一次性探测：GET /api/timeline/new?after=<head_cursor> 返回新内容条数。
/// 只在「回前台自动更新」路径上用一次——先问有没有新内容，再决定要不要回顶 + 刷新，
/// 没有就完全不打扰当前阅读位置。**没有后台轮询**：前台阅读期间不主动打断用户
/// （旧的 30s 轮询 + 蓝色可点胶囊已移除），刷新只靠下拉与回前台。
/// 失败一律按 0 处理（静默），401 走 onUnauthorized。
@MainActor
public final class NewContentChecker {
    /// 401 时触发（app 层接 AuthSession.handleUnauthorized）
    public var onUnauthorized: (@MainActor () -> Void)?

    private let api: CondenserAPI
    private let channelID: Int?
    private let unreadOnly: Bool
    private let source: String?
    private let headCursor: @MainActor () -> String?

    public init(
        api: CondenserAPI,
        channelID: Int? = nil,
        unreadOnly: Bool = false,
        source: String? = nil,
        headCursor: @escaping @MainActor () -> String?
    ) {
        self.api = api
        self.channelID = channelID
        self.unreadOnly = unreadOnly
        self.source = source
        self.headCursor = headCursor
    }

    public func check() async -> Int {
        guard let after = headCursor() else { return 0 }
        do {
            let new = try await api.timelineNew(
                after: after, channelID: channelID, limit: 100, unreadOnly: unreadOnly,
                source: source)
            return new.count
        } catch APIError.unauthorized {
            onUnauthorized?()
            return 0
        } catch {
            return 0
        }
    }
}
