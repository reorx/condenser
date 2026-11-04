import SwiftUI
import CondenserKit

// 详情底部动作区：上行保留信源专有动作的文字，下行用图标展示各信源共用的动作。

extension View {
    /// 上行按钮是等分的半行宽：iPhone 最大字号下「在 Telegram 打开」连图标放不下，
    /// 这时先去掉图标、字号不变；纯文字也放不下（更窄的机型）才把字缩小。
    func actionTextLabel() -> some View {
        ViewThatFits(in: .horizontal) {
            labelStyle(.titleAndIcon)
                .readingFont(.footnote)
                .lineLimit(1)
            labelStyle(.titleOnly)
                .readingFont(.footnote)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .frame(maxWidth: .infinity)
    }

    func actionIconLabel() -> some View {
        labelStyle(.iconOnly)
            .readingFont(.footnote)
            .imageScale(.large)
            .frame(maxWidth: .infinity)
    }
}

/// 四个信源共用的收藏、评论、转发、复制链接图标按钮；文字供读屏和悬停提示使用。
///
/// 转发对 Telegram 条目是原生 forward / 引用发布，对其他信源是服务端渲染的标题 + 链接；
/// 差别只在 `ForwardDialog` 的文案里，调用方不必关心。
struct ItemActionButtons: View {
    let item: TimelineItem
    var onToggleSaved: () -> Void

    @Environment(ReaderSession.self) private var reader
    @State private var copiedLink = false
    @State private var showForward = false
    /// 评论抽屉 → 「转发」时切到预填评论的 ForwardDialog（.sheet(item:) 换 item
    /// 自带「先收后弹」，不必手工调度两次 present）
    @State private var noteFlow: NoteFlow?
    /// 本次 sheet 生命周期里保存过的 note；nil = 还没动过，沿用 envelope 的值。
    /// item 是列表的值拷贝，保存后它不会自己变新。
    @State private var editedNote: String?

    private enum NoteFlow: Identifiable {
        case editor
        case forward(String)

        var id: String {
            switch self {
            case .editor: "editor"
            case .forward: "forward"
            }
        }
    }

    private var currentNote: String { editedNote ?? item.note ?? "" }

    private var originalURL: URL? {
        item.originalURL(telegramUsername: item.telegram.flatMap { reader.channelUsername(for: $0) })
    }

    var body: some View {
        Button(action: onToggleSaved) {
            Label(item.isSaved ? "已收藏" : "收藏", systemImage: item.isSaved ? "star.fill" : "star")
                .actionIconLabel()
        }
        .buttonStyle(.bordered)
        .tint(item.isSaved ? .orange : nil)
        .help(item.isSaved ? "已收藏" : "收藏")

        Button {
            noteFlow = .editor
        } label: {
            Label("评论", systemImage: currentNote.isEmpty ? "text.bubble" : "text.bubble.fill")
                .actionIconLabel()
        }
        .buttonStyle(.bordered)
        .tint(currentNote.isEmpty ? nil : .indigo)
        .help("评论")
        .sheet(item: $noteFlow) { flow in
            switch flow {
            case .editor:
                ItemNoteSheet(
                    itemKey: item.key,
                    initialNote: currentNote,
                    onSaved: { editedNote = $0 },
                    onForward: { noteFlow = .forward($0) })
            case .forward(let comment):
                ForwardDialog(
                    itemKey: item.key, isTelegram: item.source == "telegram",
                    initialComment: comment)
            }
        }

        Button {
            showForward = true
        } label: {
            Label("转发", systemImage: "arrowshape.turn.up.forward")
                .actionIconLabel()
        }
        .buttonStyle(.bordered)
        .help("转发")
        // sheet 挂在转发按钮本身。别把这几个按钮包进 Group 再往 Group 上挂——
        // Group 的修饰符会分发给每个子视图，每个按钮会各弹一个 sheet
        .sheet(isPresented: $showForward) {
            ForwardDialog(itemKey: item.key, isTelegram: item.source == "telegram")
        }

        if let url = originalURL {
            Button {
                UIPasteboard.general.string = url.absoluteString
                copiedLink = true
            } label: {
                Label(copiedLink ? "已复制" : "复制链接",
                      systemImage: copiedLink ? "checkmark" : "link")
                    .actionIconLabel()
            }
            .buttonStyle(.bordered)
            .tint(copiedLink ? .green : nil)
            .help(copiedLink ? "已复制" : "复制链接")
            .sensoryFeedback(.success, trigger: copiedLink) { _, new in new }
            .task(id: copiedLink) {
                guard copiedLink else { return }
                try? await Task.sleep(for: .seconds(1.5))
                copiedLink = false
            }
        }
    }
}

/// 两行动作区：上行等分展示带字的信源专有动作，下行等分展示通用动作与分享图片。
/// 没有专有动作时省去上行及其间距。
struct ItemActionBar<Links: View>: View {
    let item: TimelineItem
    let shareCard: ShareCard?
    var onToggleSaved: () -> Void
    @ViewBuilder var links: Links

    var body: some View {
        VStack(spacing: 8) {
            Group(subviews: links) { subviews in
                if !subviews.isEmpty {
                    HStack(spacing: 8) {
                        ForEach(subviews) { $0 }
                    }
                }
            }
            HStack(spacing: 8) {
                ItemActionButtons(item: item, onToggleSaved: onToggleSaved)
                ShareImageButton(card: shareCard)
            }
        }
    }
}
