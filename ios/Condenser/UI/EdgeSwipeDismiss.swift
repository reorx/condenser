import SwiftUI

/// 从左边缘右滑关闭当前 sheet。读长文的抽屉滚到底部后，下拉手势先变成回滚内容，
/// 系统自带的关闭手段只剩顶部的 grabber——单手够不着，所以补一条顺手的退路。
/// 只在左边缘一条窄带上收手势（宽度参照系统返回手势的响应区），
/// 不碰内容区自身的滚动与链接点击。
struct EdgeSwipeDismiss: ViewModifier {
    @Environment(\.dismiss) private var dismiss

    func body(content: Content) -> some View {
        content.overlay(alignment: .leading) {
            Color.clear
                .frame(width: 24)
                .contentShape(Rectangle())
                // 普通 gesture 而不是 highPriorityGesture：从边缘起手的纵向滚动
                // 要照常归 ScrollView，横向滑动 ScrollView 本来就不认领，抢不走
                .gesture(
                    DragGesture(minimumDistance: 20)
                        .onEnded { value in
                            // 明确向右、且横向位移压过纵向的才算：竖着滚到边缘不该关抽屉
                            if value.translation.width > 60,
                               value.translation.width > abs(value.translation.height) {
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
