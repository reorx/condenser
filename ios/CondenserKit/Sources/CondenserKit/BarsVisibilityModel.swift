import CoreGraphics
import Foundation

/// 滚动方向感知的导航/tab 栏显隐决策（纯逻辑，UI 层喂滚动几何事件）。
///
/// bars 显隐会改变 ScrollView 的 safe-area insets，而 insets 又是滚动几何的一部分，
/// 直接按位移方向切换会形成自激振荡（隐藏 → insets 动画产生反向"位移" → 恢复 → 循环，
/// 主线程被全量重排钉死）。两道防线：
/// 1. 方向判定只在用户真正滚动时生效（`isUserScrolling`，由 scroll phase 驱动）；
/// 2. 每次切换后有冷却窗口，吞掉 bars 动画期间的虚假位移（含顶部规则）。
public struct BarsVisibilityModel {
    public private(set) var barsHidden = false
    /// 由 UI 层的 onScrollPhaseChange 维护：tracking/interacting/decelerating 为 true
    public var isUserScrolling = false

    private let threshold: CGFloat
    private let cooldown: Duration
    private var cooldownUntil: ContinuousClock.Instant?

    public init(threshold: CGFloat = 8, cooldown: Duration = .milliseconds(400)) {
        self.threshold = threshold
        self.cooldown = cooldown
    }

    /// offset 语义：contentOffset.y + contentInsets.top，0 即列表顶部。
    /// 返回 barsHidden 是否发生了切换（UI 层据此决定是否做动画）。
    public mutating func handleScroll(
        from oldOffset: CGFloat, to newOffset: CGFloat, now: ContinuousClock.Instant
    ) -> Bool {
        if let until = cooldownUntil, now < until { return false }
        let target: Bool
        if newOffset <= 0 {
            target = false
        } else if !isUserScrolling {
            return false
        } else if newOffset - oldOffset > threshold {
            target = true
        } else if oldOffset - newOffset > threshold {
            target = false
        } else {
            return false
        }
        guard target != barsHidden else { return false }
        barsHidden = target
        cooldownUntil = now.advanced(by: cooldown)
        return true
    }
}
