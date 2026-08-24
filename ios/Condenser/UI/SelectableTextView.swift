import CondenserKit
import SwiftUI
import UIKit

/// 一条已定位的高亮：标注 id + 它在**屏幕显示文本**里的 NSRange
/// （重定位在 Kit 的 locateAnnotation，这里只管画和点）。
struct TextHighlight: Equatable {
    let id: Int
    let range: NSRange
}

/// 选中文字按「高亮」时回调的锚点素材：引文 + 前后各约 30 字的上下文，
/// 全部取自屏幕显示的字符串（X 的 t.co 替换之后），与重定位读到的是同一份。
struct TextSelectionContext {
    let quote: String
    let prefix: String
    let suffix: String
}

// 浅黄底 + 深黄下划线（有无评论外观相同——点开才知道，界面不再多一种记号）
private let highlightBackground = UIColor.systemYellow.withAlphaComponent(0.28)
private let highlightUnderline = UIColor(red: 0.72, green: 0.54, blue: 0.05, alpha: 1)
private let contextChars = 30

/// 详情 sheet 正文：UITextView 包装，支持长按后拖动选择柄选取部分文字
/// （SwiftUI Text 的 textSelection 只能整段拷贝）。链接点击仍走 openURL
/// 环境（→ 应用内 Safari），字号跟随 readingFontScale 设定的 dynamicTypeSize。
///
/// 标注（2026-08-24）：`highlights` 把已定位的标注画成浅黄底 + 深黄下划线；
/// `onHighlightSelection` 非 nil 时系统选中菜单里插一项「高亮」；点已有高亮
/// 会经 UIEditMenuInteraction 程序化弹出「评论」「删除」（重叠不合并，命中
/// 范围最短的那条）。全走系统编辑菜单，不自绘 popover。
struct SelectableTextView: UIViewRepresentable {
    let text: String
    /// X 专用（schema v13）：t.co → 原始链接的替换元数据
    var urlEntities: [XUrlEntity]? = nil
    var highlights: [TextHighlight] = []
    var onHighlightSelection: ((TextSelectionContext) -> Void)? = nil
    var onAnnotationComment: ((Int) -> Void)? = nil
    var onAnnotationDelete: ((Int) -> Void)? = nil

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

        // 高亮的点击菜单：交互与手势常驻，行为由 updateUIView 写进 coordinator 的
        // 回调门控——makeUIView 只跑一次，回调却可能随渲染变化
        let menu = UIEditMenuInteraction(delegate: context.coordinator)
        view.addInteraction(menu)
        context.coordinator.menuInteraction = menu
        let tap = UITapGestureRecognizer(
            target: context.coordinator, action: #selector(Coordinator.handleTap(_:)))
        tap.delegate = context.coordinator
        view.addGestureRecognizer(tap)
        return view
    }

    func updateUIView(_ view: UITextView, context: Context) {
        context.coordinator.openURL = openURL
        context.coordinator.highlights = highlights
        context.coordinator.onHighlightSelection = onHighlightSelection
        context.coordinator.onAnnotationComment = onAnnotationComment
        context.coordinator.onAnnotationDelete = onAnnotationDelete
        let font = UIFont.preferredFont(
            forTextStyle: .body,
            compatibleWith: UITraitCollection(
                preferredContentSizeCategory: typeSize.contentSizeCategory))
        let attributed = NSMutableAttributedString(
            attributedString: linkifiedNS(text, font: font, urlEntities: urlEntities))
        let length = attributed.length
        for highlight in highlights {
            // 范围钳到当前文本内：重定位与渲染之间正文若有出入，宁可画短也别越界崩溃
            guard highlight.range.location < length, highlight.range.length > 0 else { continue }
            let clamped = NSRange(
                location: highlight.range.location,
                length: min(highlight.range.length, length - highlight.range.location))
            attributed.addAttributes([
                .backgroundColor: highlightBackground,
                .underlineStyle: NSUnderlineStyle.single.rawValue,
                .underlineColor: highlightUnderline,
            ], range: clamped)
        }
        view.attributedText = attributed
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize, uiView: UITextView, context: Context
    ) -> CGSize? {
        guard let width = proposal.width, width > 0, width.isFinite else { return nil }
        return uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, UITextViewDelegate, UIEditMenuInteractionDelegate,
        UIGestureRecognizerDelegate
    {
        var openURL: OpenURLAction?
        var highlights: [TextHighlight] = []
        var onHighlightSelection: ((TextSelectionContext) -> Void)?
        var onAnnotationComment: ((Int) -> Void)?
        var onAnnotationDelete: ((Int) -> Void)?
        var menuInteraction: UIEditMenuInteraction?
        /// 点中的高亮，handleTap 写入、editMenu delegate 读出（同一主线程内的一次弹出）
        private var tappedAnnotationID: Int?

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

        // MARK: 选中 → 「高亮」

        func textView(
            _ textView: UITextView, editMenuForTextIn range: NSRange,
            suggestedActions: [UIMenuElement]
        ) -> UIMenu? {
            guard let onHighlightSelection, range.length > 0 else { return nil }
            let ns = textView.attributedText.string as NSString
            guard range.location + range.length <= ns.length else { return nil }
            let quote = ns.substring(with: range)
            guard !quote.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            // 前后各取约 30 个 UTF-16 码元的上下文，按组合字符序列对齐防止劈开 emoji
            let prefixRange = ns.rangeOfComposedCharacterSequences(
                for: NSRange(
                    location: max(0, range.location - contextChars),
                    length: min(contextChars, range.location)))
            let selectionEnd = range.location + range.length
            let suffixRange = ns.rangeOfComposedCharacterSequences(
                for: NSRange(
                    location: selectionEnd,
                    length: min(contextChars, ns.length - selectionEnd)))
            let context = TextSelectionContext(
                quote: quote,
                prefix: ns.substring(with: prefixRange),
                suffix: ns.substring(with: suffixRange))
            let highlight = UIAction(
                title: "高亮", image: UIImage(systemName: "highlighter")
            ) { [weak textView] _ in
                textView?.selectedTextRange = nil
                onHighlightSelection(context)
            }
            return UIMenu(children: [highlight] + suggestedActions)
        }

        // MARK: 点已有高亮 → 「评论」「删除」

        /// 只在点中高亮时揽下这一击，别处的点击（链接、选择手势）原样放行
        func gestureRecognizer(
            _ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch
        ) -> Bool {
            guard onAnnotationComment != nil || onAnnotationDelete != nil,
                  let view = gestureRecognizer.view as? UITextView
            else { return false }
            return annotationID(at: touch.location(in: view), in: view) != nil
        }

        func gestureRecognizer(
            _ gestureRecognizer: UIGestureRecognizer,
            shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer
        ) -> Bool { true }

        @objc func handleTap(_ gesture: UITapGestureRecognizer) {
            guard gesture.state == .ended,
                  let view = gesture.view as? UITextView,
                  let menuInteraction
            else { return }
            let point = gesture.location(in: view)
            guard let id = annotationID(at: point, in: view) else { return }
            tappedAnnotationID = id
            menuInteraction.presentEditMenu(
                with: UIEditMenuConfiguration(identifier: nil, sourcePoint: point))
        }

        /// 命中判定：字符索引落进的高亮里**范围最短**那条（重叠不合并的配套规则）
        private func annotationID(at point: CGPoint, in view: UITextView) -> Int? {
            guard let position = view.closestPosition(to: point) else { return nil }
            let index = view.offset(from: view.beginningOfDocument, to: position)
            return highlights
                .filter { $0.range.location <= index && index < $0.range.location + $0.range.length }
                .min { $0.range.length < $1.range.length }?
                .id
        }

        func editMenuInteraction(
            _ interaction: UIEditMenuInteraction,
            menuFor configuration: UIEditMenuConfiguration,
            suggestedActions: [UIMenuElement]
        ) -> UIMenu? {
            guard let id = tappedAnnotationID else { return nil }
            tappedAnnotationID = nil
            let comment = onAnnotationComment
            let delete = onAnnotationDelete
            return UIMenu(children: [
                UIAction(title: "评论", image: UIImage(systemName: "text.bubble")) { _ in
                    comment?(id)
                },
                UIAction(
                    title: "删除", image: UIImage(systemName: "trash"), attributes: .destructive
                ) { _ in
                    delete?(id)
                },
            ])
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
