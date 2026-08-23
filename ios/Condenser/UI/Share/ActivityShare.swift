import SwiftUI
import UIKit

/// 弹系统分享面板分享一个文件。
///
/// 不用 `ShareLink`：它要求初始化时就持有成品数据，而这里是「点了才生成」——
/// 一条几十张图的长文要预载几秒钟。也不把 `UIActivityViewController` 包成 SwiftUI
/// sheet 的根视图：那样会先弹出一张空白 sheet，面板再从它上面弹出来。
/// 直接从最上层的 view controller present，视觉上就是详情抽屉上直接升起面板。
@MainActor
func presentShareSheet(fileURL: URL, onFinish: @escaping () -> Void) {
    guard let top = topmostViewController() else {
        onFinish()
        return
    }
    let controller = UIActivityViewController(activityItems: [fileURL], applicationActivities: nil)
    controller.completionWithItemsHandler = { _, _, _, _ in onFinish() }
    // iPhone 竖屏 only，但 iPad 兼容模式下 popover 没有锚点会直接崩
    if let popover = controller.popoverPresentationController {
        popover.sourceView = top.view
        popover.sourceRect = CGRect(x: top.view.bounds.midX, y: top.view.bounds.maxY,
                                    width: 0, height: 0)
    }
    top.present(controller, animated: true)
}

/// 当前真正在最上面的 VC——详情抽屉本身就是一个 presented VC，
/// 从 root 直接 present 会报「已经在 present 了」。
@MainActor
private func topmostViewController() -> UIViewController? {
    let scene = UIApplication.shared.connectedScenes
        .compactMap { $0 as? UIWindowScene }
        .first { $0.activationState == .foregroundActive }
    var controller = scene?.keyWindow?.rootViewController
    while let presented = controller?.presentedViewController {
        controller = presented
    }
    return controller
}
