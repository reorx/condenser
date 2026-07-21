import Foundation

/// APIClient 的可注入抽象：Store/Reporter/Poller 依赖它，测试用 stub。
/// 多信源契约：timeline 条目是 envelope，read/save 以 item key 出入参，
/// source 参数把查询收窄到单一信源（channel_id 隐含 telegram）。
public protocol CondenserAPI: Sendable {
    func timeline(
        cursor: String?, limit: Int?, channelID: Int?, date: String?, unreadOnly: Bool,
        source: String?
    ) async throws -> TimelinePage
    func timelineNew(
        after: String, channelID: Int?, limit: Int, unreadOnly: Bool, source: String?
    ) async throws -> TimelineNew
    /// 已添加（有 ≥1 订阅）的信源及其订阅列表——信源菜单与订阅页的唯一数据源
    func sources() async throws -> [SourceGroup]
    func markRead(keys: [String]) async throws
    func records() async throws -> [TimelineItem]
    func saveRecord(key: String) async throws
    func deleteRecord(key: String) async throws
    /// 触发后端从 Telegram 拉取该频道更早的历史（同步，返回实际入库条数）
    func fetchOlder(channelID: Int, count: Int) async throws -> Int
}

extension APIClient: CondenserAPI {}
