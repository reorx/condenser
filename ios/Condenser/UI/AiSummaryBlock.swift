import SwiftUI

/// AI 摘要的引用块：浅色底 + 左侧一条更深的同色竖条（Markdown 渲染 blockquote 的形状），
/// 「AI 摘要」标注在块内顶部——眼睛先撞上「这是机器转述」，再读到内容，
/// 而且标注和内容装在同一个块里，归属不会看岔。
/// 列表卡片与详情 sheet 共用；两处的正文视图不同（截断文本 / 可选中文本），
/// 所以内容作 closure 传入。色相用靛蓝：琥珀是 RSS 信源、橙是 HN 与收藏、
/// 天蓝是未读点，摘要要一个还没被占用的颜色。
struct AiSummaryBlock<Content: View>: View {
    @ViewBuilder var content: Content

    private let tint = Color.indigo

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label("AI 摘要", systemImage: "sparkles")
                .font(.caption.weight(.semibold))
                .foregroundStyle(tint)
            content
        }
        .padding(.vertical, 8)
        .padding(.leading, 13)
        .padding(.trailing, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(tint.opacity(0.07))
        .overlay(alignment: .leading) {
            Rectangle()
                .fill(tint.opacity(0.55))
                .frame(width: 3)
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
