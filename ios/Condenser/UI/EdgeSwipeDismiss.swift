import SwiftUI
import CondenserKit

/// 从左边缘右滑关闭当前 sheet。读长文的抽屉滚到底部后，下拉手势先变成回滚内容，
/// 系统自带的关闭手段只剩顶部的 grabber——单手够不着，所以补一条顺手的退路。
/// 只在左边缘一条窄带上收手势（宽度参照系统返回手势的响应区），
/// 不碰内容区自身的滚动与链接点击。
///
/// 不直接挂在某个详情抽屉上：`detailSheetPresentation()` 的 iPhone 分支替四个源统一挂
/// （2026-09-19 之前只有 RSS 抽屉有，X / HN / Telegram 三个关不掉）。判定规则在 Kit 的
/// `EdgeSwipe`（有测试）。
struct EdgeSwipeDismiss: ViewModifier {
    @Environment(\.dismiss) private var dismiss

    func body(content: Content) -> some View {
        content.overlay(alignment: .leading) {
            Color.clear
                .frame(width: EdgeSwipe.bandWidth)
                .contentShape(Rectangle())
                // 普通 gesture 而不是 highPriorityGesture：从边缘起手的纵向滚动
                // 要照常归 ScrollView，横向滑动 ScrollView 本来就不认领，抢不走
                .gesture(
                    DragGesture(minimumDistance: EdgeSwipe.minimumDistance)
                        .onEnded { value in
                            if EdgeSwipe.shouldDismiss(
                                dx: value.translation.width, dy: value.translation.height) {
                                dismiss()
                            }
                        }
                )
        }
    }
}

extension View {
    func edgeSwipeToDismiss() -> some View {
        modifier(EdgeSwipeDismiss())
    }
}
