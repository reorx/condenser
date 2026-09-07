import Foundation

/// 新内容一次性探测：GET /api/timeline/new/count?after=<head_cursor> 只拿条数
/// （2026-09-07 起不再走 /timeline/new——那条会把最多 100 条 envelope 一起拉回来）。
/// 冷启动渲染快照后与回前台时各问一次，结果只用来在列表上方浮一个可关闭的蓝色胶囊
/// 「N 条新内容」，**不回顶、不刷新、不动内容**——回顶 + 刷新是用户点胶囊才发生的事。
/// **没有后台轮询**：前台阅读期间不主动打断用户。
/// 失败一律按 0 处理（静默），401 走 onUnauthorized。
@MainActor
public final class NewContentChecker {
    /// 401 时触发（app 层接 AuthSession.handleUnauthorized）
    public var onUnauthorized: (@MainActor () -> Void)?

    private let api: CondenserAPI
    private let channelID: Int?
    private let unreadOnly: Bool
    private let source: String?
    private let feed: String?
    private let headCursor: @MainActor () -> String?

    public init(
        api: CondenserAPI,
        channelID: Int? = nil,
        unreadOnly: Bool = false,
        source: String? = nil,
        feed: String? = nil,
        headCursor: @escaping @MainActor () -> String?
    ) {
        self.api = api
        self.channelID = channelID
        self.unreadOnly = unreadOnly
        self.source = source
        self.feed = feed
        self.headCursor = headCursor
    }

    public func check() async -> Int {
        guard let after = headCursor() else { return 0 }
        do {
            return try await api.timelineNewCount(
                after: after, channelID: channelID, unreadOnly: unreadOnly,
                source: source, feed: feed)
        } catch APIError.unauthorized {
            onUnauthorized?()
            return 0
        } catch {
            return 0
        }
    }
}
