import SwiftUI
import UIKit

/// Mac 侧栏的显隐（2026-09-04）。`MainView` 的 `.sidebarAdaptable` TabView 在 Catalyst 上
/// 底层是 tabSidebar 模式的 `UITabBarController`，但 SwiftUI 没暴露收起它的入口，也不像
/// `NavigationSplitView` 那样自带工具栏按钮——侧栏就是常驻的。`UITabBarController.sidebar.isHidden`
/// 是公开 API，实测能直接收起并让内容铺满，这里做的只是把它接到一个 AppStorage 开关上：
/// 四个 tab 根界面的工具栏按钮与 View 菜单「显示/隐藏侧栏」⌥⌘S 各翻这一个值，
/// `MacSidebarApplier` 负责把值写进控制器（首屏进 window 时恢复上次的开关，之后随开关变）。
///
/// 两条走过的弯路：① UIKit 已经在响应链上注册了 ⌃⌘S → `toggleSidebar:`，所以自己的菜单项
/// 不能用 ⌃⌘S（建菜单时因快捷键重复直接崩），改用 Finder 同款的 ⌥⌘S；② 那个
/// `toggleSidebar:` 用 `sendAction` 发上去什么也不发生（View 菜单里也没有它的菜单项），
/// 所以不借它，直接写 `isHidden`。iPhone 上这些全都不出现。
enum MacSidebar {
    static let storageKey = "condenser.mac.sidebarHidden"
}

/// 挂在 TabView 的 `.background` 上：借一个 UIView 拿到 window → rootViewController，
/// 找到 UITabBarController 后应用显隐。
struct MacSidebarApplier: UIViewRepresentable {
    let hidden: Bool

    func makeUIView(context: Context) -> ApplierView {
        ApplierView()
    }

    func updateUIView(_ view: ApplierView, context: Context) {
        view.sidebarHidden = hidden
    }

    final class ApplierView: UIView {
        var sidebarHidden = false {
            didSet { apply() }
        }

        override func didMoveToWindow() {
            super.didMoveToWindow()
            apply()
        }

        private func apply() {
            guard let root = window?.rootViewController,
                  let tab = Self.findTabController(root) else { return }
            if tab.sidebar.isHidden != sidebarHidden {
                tab.sidebar.isHidden = sidebarHidden
            }
        }

        private static func findTabController(_ vc: UIViewController) -> UITabBarController? {
            if let tab = vc as? UITabBarController { return tab }
            for child in vc.children {
                if let tab = findTabController(child) { return tab }
            }
            return nil
        }
    }
}

/// 翻开关的按钮。工具栏与 View 菜单共用；快捷键只挂在菜单那份上。
struct MacSidebarToggleButton: View {
    @AppStorage(MacSidebar.storageKey) private var hidden = false
    var withShortcut = false

    var body: some View {
        Button {
            hidden.toggle()
        } label: {
            Label(hidden ? "显示侧栏" : "隐藏侧栏", systemImage: "sidebar.leading")
        }
        .keyboardShortcut(withShortcut ? KeyboardShortcut("s", modifiers: [.command, .option]) : nil)
    }
}

/// View 菜单里的「显示/隐藏侧栏」⌥⌘S
struct MacSidebarCommands: Commands {
    var body: some Commands {
        CommandGroup(after: .sidebar) {
            if Platform.isMac {
                MacSidebarToggleButton(withShortcut: true)
            }
        }
    }
}

private struct MacSidebarToolbar: ViewModifier {
    func body(content: Content) -> some View {
        if Platform.isMac {
            content.toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    MacSidebarToggleButton()
                        .help("显示/隐藏侧栏（⌥⌘S）")
                }
            }
        } else {
            content
        }
    }
}

private struct MacSidebarHost: ViewModifier {
    @AppStorage(MacSidebar.storageKey) private var hidden = false

    func body(content: Content) -> some View {
        if Platform.isMac {
            content.background(MacSidebarApplier(hidden: hidden))
        } else {
            content
        }
    }
}

extension View {
    /// 四个 tab 根界面：Mac 上在工具栏放侧栏开关，iPhone 不动
    func macSidebarToggleToolbar() -> some View {
        modifier(MacSidebarToolbar())
    }

    /// 挂在 TabView 上：把开关的值应用到底层的 UITabBarController
    func macSidebarHost() -> some View {
        modifier(MacSidebarHost())
    }
}
