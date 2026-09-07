import Foundation

/// 阅读代理票据的内存缓存 + 过期判定（plan 2026-09-07 §5.1）。纯状态，不做网络。
///
/// 票据是"锦上添花"：点击永远同步、永远用当下缓存的票（可能为 nil，cookie 已种下时
/// `_pt` 缺失无妨）。所以 `cached` 和 `shouldRefresh` 是两个独立问题——进入刷新
/// margin 时该去换一张新的，但手里这张在硬过期前仍然可用。
public struct PurifierTickets: Sendable {
    /// 剩余有效期低于此值就该换票
    public static let refreshMargin: TimeInterval = 60

    private var ticket: String?
    private var expiresAt: Date?

    public init() {}

    /// 当下可用的票；硬过期后为 nil
    public func cached(now: Date = Date()) -> String? {
        guard let ticket, let expiresAt, now < expiresAt else { return nil }
        return ticket
    }

    /// 没票，或剩余不足 `refreshMargin`
    public func shouldRefresh(now: Date = Date()) -> Bool {
        guard let expiresAt, ticket != nil else { return true }
        return expiresAt.timeIntervalSince(now) < Self.refreshMargin
    }

    public mutating func store(ticket: String, ttl: TimeInterval, now: Date = Date()) {
        self.ticket = ticket
        expiresAt = now.addingTimeInterval(ttl)
    }

    public mutating func clear() {
        ticket = nil
        expiresAt = nil
    }
}
