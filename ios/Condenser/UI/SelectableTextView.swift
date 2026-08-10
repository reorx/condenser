import CondenserKit
import SwiftUI
import UIKit

/// 详情 sheet 正文：UITextView 包装，支持长按后拖动选择柄选取部分文字
/// （SwiftUI Text 的 textSelection 只能整段拷贝）。链接点击仍走 openURL
/// 环境（→ 应用内 Safari），字号跟随 readingFontScale 设定的 dynamicTypeSize。
struct SelectableTextView: UIViewRepresentable {
    let text: String
    /// X 专用（schema v13）：t.co → 原始链接的替换元数据
    var urlEntities: [XUrlEntity]? = nil

    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.openURL) private var openURL

    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.isEditable = false
        view.isScrollEnabled = false
        view.backgroundColor = .clear
        view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0
        view.delegate = context.coordinator
        // 字号由 SwiftUI 环境（readingFontScale）驱动，不跟系统动态字号
        view.adjustsFontForContentSizeCategory = false
        return view
    }

    func updateUIView(_ view: UITextView, context: Context) {
        context.coordinator.openURL = openURL
        let font = UIFont.preferredFont(
            forTextStyle: .body,
            compatibleWith: UITraitCollection(
                preferredContentSizeCategory: typeSize.contentSizeCategory))
        view.attributedText = linkifiedNS(text, font: font, urlEntities: urlEntities)
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize, uiView: UITextView, context: Context
    ) -> CGSize? {
        guard let width = proposal.width, width > 0, width.isFinite else { return nil }
        return uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, UITextViewDelegate {
        var openURL: OpenURLAction?

        func textView(
            _ textView: UITextView, primaryActionFor textItem: UITextItem,
            defaultAction: UIAction
        ) -> UIAction? {
            if case .link(let url) = textItem.content {
                let open = openURL
                return UIAction { _ in open?(url) }
            }
            return defaultAction
        }
    }
}

private extension DynamicTypeSize {
    var contentSizeCategory: UIContentSizeCategory {
        switch self {
        case .xSmall: .extraSmall
        case .small: .small
        case .medium: .medium
        case .large: .large
        case .xLarge: .extraLarge
        case .xxLarge: .extraExtraLarge
        case .xxxLarge: .extraExtraExtraLarge
        case .accessibility1: .accessibilityMedium
        case .accessibility2: .accessibilityLarge
        case .accessibility3: .accessibilityExtraLarge
        case .accessibility4: .accessibilityExtraExtraLarge
        case .accessibility5: .accessibilityExtraExtraExtraLarge
        @unknown default: .large
        }
    }
}
