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
}

extension APIClient: CondenserAPI {}
