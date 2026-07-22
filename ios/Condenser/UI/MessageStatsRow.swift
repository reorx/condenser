import SwiftUI
import CondenserKit

/// 详情页 header 下的实时 stats 行：views / forwards / reaction chips。
/// 纯展示组件——数据由 MessageDetailSheet 打开时实时拉取（GET .../stats，不入库），
/// 拉不到或全空时由调用方直接不渲染本行。
struct MessageStatsRow: View {
    let stats: MessageStats

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                if let views = stats.views {
                    statItem(icon: "eye", count: views)
                }
                if let forwards = stats.forwards {
                    statItem(icon: "arrow.2.squarepath", count: forwards)
                }
                ForEach(Array(stats.reactions.enumerated()), id: \.offset) { _, reaction in
                    ReactionChipView(reaction: reaction)
                }
            }
        }
    }

    private func statItem(icon: String, count: Int) -> some View {
        HStack(spacing: 4) {
            Image(systemName: icon)
            Text(count, format: .number.notation(.compactName))
        }
        .font(.footnote)
        .foregroundStyle(.secondary)
    }
}

/// 一个 reaction 圆片：emoji 直接展示，custom/other 降级为通用图标；chosen 高亮
private struct ReactionChipView: View {
    let reaction: ReactionCount

    var body: some View {
        HStack(spacing: 4) {
            if reaction.kind == .emoji, let emoji = reaction.emoji {
                Text(emoji)
            } else {
                Image(systemName: "face.smiling")
            }
            Text(reaction.count, format: .number.notation(.compactName))
        }
        .font(.footnote)
        .foregroundStyle(reaction.chosen ? Color.accentColor : .secondary)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(
            Capsule().fill(reaction.chosen ? Color.accentColor.opacity(0.12) : Color(.systemGray6)))
        .overlay {
            if reaction.chosen {
                Capsule().strokeBorder(Color.accentColor.opacity(0.4))
            }
        }
    }
}
