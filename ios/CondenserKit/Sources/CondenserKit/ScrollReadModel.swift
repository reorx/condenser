import CoreGraphics
import Foundation

/// 「滚过即已读」的判定（纯逻辑，UI 层喂行的几何 + 滚动 phase）。
///
/// 判读线是**视口下边界**：卡片下边界进到视口里（maxY <= viewportHeight）就算看过——
/// 旧规则「整体移出视口上方」（maxY < 0）是它的子集，天然覆盖。
/// 光有这条线还不够：首屏一渲染就有半屏卡片满足它，什么都没看就被判读。
/// 所以要 armed —— 用户在本视图真正滚动过一次判定才生效，
/// 而刷新（下拉 / 回前台静默更新）替换列表时 `reset()`，免得新首屏被瞬间批量标记。
public struct ScrollReadModel: Equatable, Sendable {
    /// 用户是否已在本视图滚动过；false 时一律不判读
    public private(set) var armed = false

    public init() {}

    /// 卡片下边界是否已越过判读线。
    /// `frameMaxY` 是行在 `.scrollView` 坐标空间里的 maxY（视口顶为 0），
    /// `viewportHeight` 是视口高度；拿不到视口高度时传 0——
    /// 那样退化成旧规则（移出视口上方），而不是把整屏判成已读。
    public static func hasPassedReadLine(frameMaxY: CGFloat, viewportHeight: CGFloat) -> Bool {
        frameMaxY <= viewportHeight
    }

    /// 用户手势滚动（程序化回顶不算，否则回前台静默刷新会自己武装自己）
    public mutating func noteUserScroll() {
        armed = true
    }

    /// 列表被替换（下拉刷新 / 回前台静默刷新）时解除武装
    public mutating func reset() {
        armed = false
    }
}
