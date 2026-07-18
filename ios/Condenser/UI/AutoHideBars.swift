import SwiftUI

/// 阅读时最大化可读面积：向上滑（继续读）隐藏导航栏 + tab 栏，
/// 向下滑或回到顶部时恢复。附着在 ScrollView 上（onScrollGeometryChange 依赖它）。
struct AutoHideBars: ViewModifier {
    @State private var hidden = false

    func body(content: Content) -> some View {
        content
            .onScrollGeometryChange(for: CGFloat.self) { geo in
                geo.contentOffset.y + geo.contentInsets.top
            } action: { oldOffset, newOffset in
                if newOffset <= 0 {
                    setHidden(false)
                } else if newOffset - oldOffset > 8 {
                    setHidden(true)
                } else if oldOffset - newOffset > 8 {
                    setHidden(false)
                }
            }
            .toolbarVisibility(hidden ? .hidden : .visible, for: .navigationBar)
            .toolbarVisibility(hidden ? .hidden : .visible, for: .tabBar)
    }

    private func setHidden(_ value: Bool) {
        guard value != hidden else { return }
        withAnimation(.easeInOut(duration: 0.2)) { hidden = value }
    }
}

extension View {
    func autoHideBars() -> some View {
        modifier(AutoHideBars())
    }
}
