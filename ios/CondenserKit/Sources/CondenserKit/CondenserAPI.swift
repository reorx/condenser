import Foundation

/// APIClient 的可注入抽象：Store/Reporter/Poller 依赖它，测试用 stub。
public protocol CondenserAPI: Sendable {
    func timeline(
        cursor: String?, limit: Int?, channelID: Int?, date: String?, unreadOnly: Bool
    ) async throws -> TimelinePage
    func timelineNew(
        after: String, channelID: Int?, limit: Int, unreadOnly: Bool
    ) async throws -> TimelineNew
    func subscriptions() async throws -> [Subscription]
    func markRead(_ items: [MsgRef]) async throws
    func records() async throws -> [DisplayMessage]
    func saveRecord(_ ref: MsgRef) async throws
    func deleteRecord(_ ref: MsgRef) async throws
    /// 触发后端从 Telegram 拉取该频道更早的历史（同步，返回实际入库条数）
    func fetchOlder(channelID: Int, count: Int) async throws -> Int
}

extension APIClient: CondenserAPI {}
