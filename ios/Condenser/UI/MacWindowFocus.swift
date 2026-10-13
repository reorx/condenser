import SwiftUI
import UIKit

/// Catalyst 的窗口 focus 不能只靠 scenePhase（切到其他 app 时场景仍可能 active）。
/// 用挂在当前列表上的 UIView 识别所属 window；tab 隐藏后停止投递，避免多个列表请求。
private struct MacWindowFocus: ViewModifier {
    let onChange: (Bool) -> Void
    @State private var isVisible = false

    func body(content: Content) -> some View {
        if Platform.isMac {
            content
                .background(WindowFocusObserver(enabled: isVisible, onChange: onChange))
                .onAppear { isVisible = true }
                .onDisappear {
                    isVisible = false
                    onChange(false)
                }
        } else {
            content
        }
    }
}

private struct WindowFocusObserver: UIViewRepresentable {
    let enabled: Bool
    let onChange: (Bool) -> Void

    func makeUIView(context: Context) -> ObserverView { ObserverView() }

    func updateUIView(_ view: ObserverView, context: Context) {
        view.onChange = onChange
        view.enabled = enabled
        // UIKit 进 window / SwiftUI 更新时不能同步修改 SwiftUI state。
        view.scheduleUpdate()
    }

    static func dismantleUIView(_ view: ObserverView, coordinator: ()) {
        view.enabled = false
        view.scheduleUpdate()
    }

    final class ObserverView: UIView {
        var enabled = false {
            didSet {
                if !enabled { hasWindowFocus = false }
            }
        }
        var onChange: ((Bool) -> Void)?
        private var hasWindowFocus = false
        private var applicationFocused = true
        // Catalyst 不可 import AppKit，但这些公开通知仍通过默认 NotificationCenter 投递。
        private static let macDidActivate = Notification.Name("NSApplicationDidBecomeActiveNotification")
        private static let macWillDeactivate = Notification.Name("NSApplicationWillResignActiveNotification")

        override init(frame: CGRect) {
            super.init(frame: frame)
            let center = NotificationCenter.default
            for name in [UIWindow.didBecomeKeyNotification, UIWindow.didResignKeyNotification,
                         UIApplication.didBecomeActiveNotification, UIApplication.willResignActiveNotification,
                         UIScene.didActivateNotification, UIScene.willDeactivateNotification,
                         Self.macDidActivate, Self.macWillDeactivate] {
                center.addObserver(self, selector: #selector(focusChanged(_:)), name: name, object: nil)
            }
        }

        required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

        deinit { NotificationCenter.default.removeObserver(self) }

        override func didMoveToWindow() {
            super.didMoveToWindow()
            scheduleUpdate()
        }

        func scheduleUpdate() {
            DispatchQueue.main.async { [weak self] in self?.updateFocus() }
        }

        @objc private func focusChanged(_ notification: Notification) {
            if let changedWindow = notification.object as? UIWindow, changedWindow !== window { return }
            if let scene = notification.object as? UIScene, scene !== window?.windowScene { return }
            if notification.name == Self.macWillDeactivate || notification.name == UIApplication.willResignActiveNotification {
                applicationFocused = false
                setFocused(false)
            } else if notification.name == Self.macDidActivate || notification.name == UIApplication.didBecomeActiveNotification {
                applicationFocused = true
                updateFocus()
            } else if notification.name == UIScene.willDeactivateNotification {
                setFocused(false)
            } else {
                updateFocus()
            }
        }

        private func updateFocus() {
            setFocused(enabled && applicationFocused && window?.isKeyWindow == true
                       && window?.windowScene?.activationState == .foregroundActive)
        }

        private func setFocused(_ value: Bool) {
            guard value != hasWindowFocus else { return }
            hasWindowFocus = value
            onChange?(value)
        }
    }
}

extension View {
    func onMacWindowFocusChange(_ onChange: @escaping (Bool) -> Void) -> some View {
        modifier(MacWindowFocus(onChange: onChange))
    }
}
