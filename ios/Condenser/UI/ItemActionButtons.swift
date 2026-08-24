import SwiftUI
import CondenserKit

/// 详情 sheet 动作行开头的三个按钮：收藏 + 评论 + 转发。四个信源的 sheet 共用一份——
/// 「这条留着」「对这条写点什么」「这条发出去」跟它是推文还是 HN story 无关，
/// 入口摆在一起才好按。
///
/// 转发对 Telegram 条目是原生 forward / 引用发布，对其他信源是服务端渲染的标题 + 链接；
/// 差别只在 `ForwardDialog` 的文案里，调用方不必关心。
struct ItemActionButtons: View {
    let item: TimelineItem
    var onToggleSaved: () -> Void

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

    var body: some View {
        Button(action: onToggleSaved) {
            Label(item.isSaved ? "已收藏" : "收藏", systemImage: item.isSaved ? "star.fill" : "star")
                .font(.footnote)
        }
        .buttonStyle(.bordered)
        .tint(item.isSaved ? .orange : nil)

        Button {
            noteFlow = .editor
        } label: {
            Label("评论", systemImage: currentNote.isEmpty ? "text.bubble" : "text.bubble.fill")
                .font(.footnote)
        }
        .buttonStyle(.bordered)
        .tint(currentNote.isEmpty ? nil : .indigo)
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
                .font(.footnote)
        }
        .buttonStyle(.bordered)
        // sheet 挂在转发按钮本身。别把这几个按钮包进 Group 再往 Group 上挂——
        // Group 的修饰符会分发给每个子视图，每个按钮会各弹一个 sheet
        .sheet(isPresented: $showForward) {
            ForwardDialog(itemKey: item.key, isTelegram: item.source == "telegram")
        }
    }
}

/// 动作按钮排成一行，放不下就横向滚动——四个中文按钮在窄屏上会溢出，
/// 而砍字数会把「在 Telegram 打开」这类说明性标签压成谜语。
struct ItemActionRow<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                content
            }
        }
        .scrollBounceBehavior(.basedOnSize, axes: .horizontal)
    }
}
