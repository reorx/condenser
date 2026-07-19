import CoreGraphics
import Foundation

/// 底部「继续上拉加载更早」的手势决策（纯逻辑，UI 层喂 overscroll 距离 + 滚动 phase）。
///
/// overscroll = 视口底边越过内容底边的距离（>0 表示已拉出内容底部的回弹区）。
/// 触发规则：用户拖拽中越过阈值触发一次；之后必须回弹到内容底部以内（overscroll ≈ 0）
/// 才会重新武装，避免同一次手势/回弹动画重复触发。
public struct PullToLoadOlderModel: Equatable, Sendable {
    private let threshold: CGFloat
    private var firedThisGesture = false

    public init(threshold: CGFloat = 70) {
        self.threshold = threshold
    }

    /// 返回 true 表示应触发一次加载。
    public mutating func handleOverscroll(_ overscroll: CGFloat, isDragging: Bool) -> Bool {
        if overscroll <= 1 {
            firedThisGesture = false
            return false
        }
        guard isDragging, !firedThisGesture, overscroll >= threshold else { return false }
        firedThisGesture = true
        return true
    }

    /// ScrollGeometry → 底部 overscroll 距离。offset 语义与 SwiftUI 一致：
    /// 顶部静止时 contentOffset.y = -topInset；短内容（不满一屏）静止在顶部也算 0。
    public static func bottomOverscroll(
        contentOffsetY: CGFloat, contentHeight: CGFloat, containerHeight: CGFloat,
        topInset: CGFloat, bottomInset: CGFloat
    ) -> CGFloat {
        let maxOffset = max(contentHeight + bottomInset - containerHeight, -topInset)
        return contentOffsetY - maxOffset
    }
}
