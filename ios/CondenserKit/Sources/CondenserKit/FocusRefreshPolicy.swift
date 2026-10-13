import Foundation

/// Mac 列表重新获得焦点时，只按两次真实 focus 的间隔检查新内容。
/// 首次 focus 由启动加载负责；持续阅读不轮询，重复系统通知不重置时间。
public struct FocusRefreshPolicy {
    public let minFocusGap: TimeInterval
    private var lastFocusedAt: Date?
    private var isFocused = false

    public init(minFocusGap: TimeInterval = 10 * 60) {
        self.minFocusGap = minFocusGap
    }

    public mutating func noteFocus(at date: Date = Date()) -> Bool {
        guard !isFocused else { return false }
        isFocused = true
        let previous = lastFocusedAt
        lastFocusedAt = date
        guard let previous else { return false }
        return date.timeIntervalSince(previous) > minFocusGap
    }

    public mutating func noteBlur() {
        isFocused = false
    }
}
