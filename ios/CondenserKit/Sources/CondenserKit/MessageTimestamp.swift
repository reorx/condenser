import Foundation

/// timeline 卡片时间戳的展示策略：3 天内用相对时间（"2 天前"），
/// 更早的消息直接显示绝对时间（与详情 sheet 一致）。具体格式化在 app 层。
public enum MessageTimestamp {
    public enum Style: Equatable, Sendable {
        case relative
        case absolute
    }

    public static let threshold: TimeInterval = 3 * 86_400

    public static func style(for date: Date, now: Date = Date()) -> Style {
        now.timeIntervalSince(date) > threshold ? .absolute : .relative
    }
}
