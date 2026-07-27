import SwiftUI
import CondenserKit

/// 详情 sheet 动作行开头的两个按钮：收藏 + 转发。三个信源的 sheet 共用一份——
/// 「这条留着」和「这条发出去」跟它是推文还是 HN story 无关，入口摆在一起才好按。
///
/// 转发对 Telegram 条目是原生 forward / 引用发布，对其他信源是服务端渲染的标题 + 链接；
/// 差别只在 `ForwardDialog` 的文案里，调用方不必关心。
struct ItemActionButtons: View {
    let item: TimelineItem
    var onToggleSaved: () -> Void

    @State private var showForward = false

    var body: some View {
        Button(action: onToggleSaved) {
            Label(item.isSaved ? "已收藏" : "收藏", systemImage: item.isSaved ? "star.fill" : "star")
                .font(.footnote)
        }
        .buttonStyle(.bordered)
        .tint(item.isSaved ? .orange : nil)

        Button {
            showForward = true
        } label: {
            Label("转发", systemImage: "arrowshape.turn.up.forward")
                .font(.footnote)
        }
        .buttonStyle(.bordered)
        // sheet 挂在转发按钮本身。别把这两个按钮包进 Group 再往 Group 上挂——
        // Group 的修饰符会分发给每个子视图，两个按钮会各弹一个 sheet
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
