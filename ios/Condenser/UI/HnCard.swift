import SwiftUI
import CondenserKit

/// HN 的 "Y" 徽标（橙底白字），列表/详情的头像位。
struct HnGlyph: View {
    var size: CGFloat = 36

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.22)
            .fill(Color(red: 1.0, green: 0.4, blue: 0.0))
            .frame(width: size, height: size)
            .overlay {
                Text("Y")
                    .font(.system(size: size * 0.55, weight: .bold))
                    .foregroundStyle(.white)
            }
    }
}

/// Hacker News story 卡片：标题为主体（点击 → 原文，self-post → 评论页）、
/// score / 评论数（点击 → HN 评论页）/ domain / 当日排名，job 弱化。
/// 已读/收藏态在外层 TimelineItem envelope 上。整卡 tap（列表层）→ 详情 sheet。
struct HnCard: View {
    let item: TimelineItem
    let story: HnStory
    /// 收藏列表不展示未读点
    var showsUnread = true
    var onToggleSaved: () -> Void

    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            title
            metaLine
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .contentShape(Rectangle())
        .opacity(story.isJob ? 0.55 : 1)
    }

    private var header: some View {
        HStack(spacing: 10) {
            HnGlyph()
            VStack(alignment: .leading, spacing: 1) {
                Text("Hacker News")
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                HStack(spacing: 4) {
                    ReadStateDot(item: item, showsUnread: showsUnread)
                    Text(captionText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            AnnotationBadge(item: item)
            Button(action: onToggleSaved) {
                Image(systemName: item.isSaved ? "star.fill" : "star")
                    .foregroundStyle(item.isSaved ? .orange : .secondary)
            }
            .buttonStyle(.plain)
        }
    }

    /// 标题：点击打开原文（self-post 回落评论页），走列表层 openURL → in-app Safari
    private var title: some View {
        Button {
            openURL(story.primaryURL)
        } label: {
            Text(story.title ?? "(untitled)")
                .font(.subheadline.weight(.medium))
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain)
    }

    private var metaLine: some View {
        HStack(spacing: 10) {
            Label("\(story.score)", systemImage: "arrowtriangle.up")
                .labelStyle(CompactMetaLabelStyle())
            Button {
                openURL(story.commentsURL)
            } label: {
                Label("\(story.commentsCount)", systemImage: "bubble.right")
                    .labelStyle(CompactMetaLabelStyle())
            }
            .buttonStyle(.plain)
            if let domain = story.domain {
                Text(domain)
                    .lineLimit(1)
            }
            if let rank = story.dayRank {
                Text("当日 #\(rank)")
                    .foregroundStyle(.orange)
            }
            if story.isJob {
                Text("JOB")
                    .font(.caption2.weight(.semibold))
                    .padding(.horizontal, 5)
                    .padding(.vertical, 1)
                    .background(Color(.secondarySystemBackground), in: Capsule())
            }
            Spacer(minLength: 0)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    /// 上榜相对时间（timeline 排序键）；卡片同时透出提交时间会太挤，详情里再展示
    private var captionText: String {
        switch MessageTimestamp.style(for: item.datetime) {
        case .relative:
            item.datetime.formatted(.relative(presentation: .named))
        case .absolute:
            item.datetime.formatted(date: .abbreviated, time: .shortened)
        }
    }
}

/// icon + 数字的紧凑并排（Label 默认间距太大）
struct CompactMetaLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 3) {
            configuration.icon
            configuration.title
        }
    }
}
