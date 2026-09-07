import Foundation

/// 回前台检查新内容的判定：只有在后台待了足够久（默认 60 秒）才值得去问一次
/// `/timeline/new/count`；短暂切走（通知中心、来电）不问。
/// 阈值 2026-09-07 从 5 分钟降到 1 分钟：原来的 5 分钟是因为检查到新内容就会回顶 +
/// 刷新、打断阅读位置，所以宁可少问；现在结果只是一个可关闭的胶囊，不动现场，
/// 唯一成本是一次 COUNT 请求。
/// scenePhase 离开 active 时 noteBackground（inactive → background 连续触发只记首次），
/// 回到 active 时 shouldRefreshOnForeground 判定并清状态，避免重复触发。
public struct ForegroundRefreshPolicy {
    public var minBackgroundGap: TimeInterval
    private var backgroundedAt: Date?

    public init(minBackgroundGap: TimeInterval = 60) {
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
