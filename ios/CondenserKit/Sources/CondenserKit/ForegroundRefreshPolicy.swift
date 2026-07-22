import Foundation

/// 回前台自动刷新判定：只有在后台待了足够久（默认 5 分钟）才值得静默刷新
/// 并弹「N 条新消息」灰 toast；短暂切走（通知中心、来电）保持阅读现场不动。
/// scenePhase 离开 active 时 noteBackground（inactive → background 连续触发只记首次），
/// 回到 active 时 shouldRefreshOnForeground 判定并清状态，避免重复触发。
public struct ForegroundRefreshPolicy {
    public var minBackgroundGap: TimeInterval
    private var backgroundedAt: Date?

    public init(minBackgroundGap: TimeInterval = 300) {
        self.minBackgroundGap = minBackgroundGap
    }

    public mutating func noteBackground(at date: Date = Date()) {
        if backgroundedAt == nil {
            backgroundedAt = date
        }
    }

    public mutating func shouldRefreshOnForeground(at date: Date = Date()) -> Bool {
        defer { backgroundedAt = nil }
        guard let backgroundedAt else { return false }
        return date.timeIntervalSince(backgroundedAt) >= minBackgroundGap
    }
}
