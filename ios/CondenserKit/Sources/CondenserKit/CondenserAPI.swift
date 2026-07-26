import Foundation

/// APIClient 的可注入抽象：Store/Reporter/Checker 依赖它，测试用 stub。
/// 多信源契约：timeline 条目是 envelope，read/save 以 item key 出入参，
/// source 参数把查询收窄到单一信源（channel_id 隐含 telegram），
/// feed 再收窄到多 feed 信源（X）里的一个 feed。
public protocol CondenserAPI: Sendable {
    func timeline(
        cursor: String?, limit: Int?, channelID: Int?, date: String?, unreadOnly: Bool,
        source: String?, feed: String?
    ) async throws -> TimelinePage
    func timelineNew(
        after: String, channelID: Int?, limit: Int, unreadOnly: Bool, source: String?,
        feed: String?
    ) async throws -> TimelineNew
    /// 已添加（有 ≥1 订阅）的信源及其订阅列表——信源菜单与订阅页的唯一数据源
    func sources() async throws -> [SourceGroup]
    func markRead(keys: [String]) async throws
    func records() async throws -> [TimelineItem]
    func saveRecord(key: String) async throws
    func deleteRecord(key: String) async throws
    /// 触发后端从 Telegram 拉取该频道更早的历史（同步，返回实际入库条数）
    func fetchOlder(channelID: Int, count: Int) async throws -> Int
    /// 给条目打上/改成 up|down 标签（一条目一行，换一侧是改正不是第二个标签）；
    /// reason 是「踩」的理由 chip，一并写入——请求描述的是完整标签
    func setFeedback(key: String, verdict: ItemFeedback, reason: ItemFeedbackReason?) async throws
    /// 撤销标签（再点已选中的那一侧）
    func clearFeedback(key: String) async throws
}

extension APIClient: CondenserAPI {}
