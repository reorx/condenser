import SwiftUI
import CondenserKit

/// 阅读时最大化可读面积：向上滑（继续读）隐藏导航栏 + tab 栏，
/// 向下滑或回到顶部时恢复。附着在 ScrollView 上（onScrollGeometryChange 依赖它）。
/// 显隐决策在 CondenserKit.BarsVisibilityModel —— bars 切换会改变 safe-area insets、
/// 反过来产生虚假滚动位移，直接按位移切换会自激振荡把主线程钉死（2026-07-18 卡死 bug），
/// 模型用「仅用户滚动时判定 + 切换后冷却窗口」双重防护。
struct AutoHideBars: ViewModifier {
    @State private var model = BarsVisibilityModel()

    func body(content: Content) -> some View {
        content
            .onScrollPhaseChange { _, newPhase in
                let scrolling = newPhase == .tracking
                    || newPhase == .interacting
                    || newPhase == .decelerating
                if model.isUserScrolling != scrolling {
                    model.isUserScrolling = scrolling
                }
            }
            .onScrollGeometryChange(for: CGFloat.self) { geo in
                geo.contentOffset.y + geo.contentInsets.top
            } action: { oldOffset, newOffset in
                var next = model
                guard next.handleScroll(from: oldOffset, to: newOffset, now: .now) else { return }
                withAnimation(.easeInOut(duration: 0.2)) { model = next }
            }
            .toolbarVisibility(model.barsHidden ? .hidden : .visible, for: .navigationBar)
            .toolbarVisibility(model.barsHidden ? .hidden : .visible, for: .tabBar)
    }
}

extension View {
    func autoHideBars() -> some View {
        modifier(AutoHideBars())
    }
}
