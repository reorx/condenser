import SwiftUI
import CondenserKit

/// RSS 的广播标记（琥珀底白图），列表/详情的信源图标位。
/// 另外三个源用字母或字标，RSS 用图形——这个源的身份本来就是这个形状。
///
/// 底色是琥珀（web 的 amber-500），不是系统 `.orange`：`HnGlyph` 已经是纯橙，
/// 两个方块在同一条时间线上前后相邻，颜色一样就等于没有信源标记。
struct RssGlyph: View {
    var size: CGFloat = 36

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.22)
            .fill(Color(red: 0.96, green: 0.62, blue: 0.04))
            .frame(width: size, height: size)
            .overlay {
                Image(systemName: "dot.radiowaves.up.forward")
                    .font(.system(size: size * 0.48, weight: .bold))
                    .foregroundStyle(.white)
            }
    }
}

/// 一条 feed 条目的卡片：feed 名作主体（一屏几十个 feed，「哪个博客」才是定位线索），
/// 标题是主角并链向原文，正文是 feed 正文的纯文本；有摘要时正文只截开头几行，
/// 摘要块（AiSummaryBlock）跟在下面——摘要是机器的转述，不标出来就是在悄悄撒谎，
/// 但它也不该顶掉原文开头，只看转述没法快速判断文章本身。
/// 已读/收藏态在外层 TimelineItem envelope 上。整卡 tap（列表层）→ 详情 sheet。
struct RssCard: View {
    let item: TimelineItem
    let entry: RssEntry
    /// 收藏列表不展示未读点
    var showsUnread = true
    var onToggleSaved: () -> Void

    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            title
            // 正文开头永远先给：只有机器转述、看不到原文开头的卡片，
            // 没法让人快速判断这篇文章本身。有摘要时正文只截几行作参照
            //（纯省略号，不给 more——细读的入口是摘要块和详情 sheet）。
            if let summary = entry.displaySummary {
                if let text = entry.contentText {
                    // 空白折叠成单个空格：快照只有 3 行配额，正文开头的段落空行
                    // 会白白吃掉一行
                    Text(text.split(whereSeparator: \.isWhitespace).joined(separator: " "))
                        .font(.subheadline)
                        .lineLimit(3)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                AiSummaryBlock {
                    TruncatableText(text: summary)
                }
            } else if let text = entry.contentText {
                TruncatableText(text: text)
            }
            if let author = entry.author {
                Text(author)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .contentShape(Rectangle())
    }

    private var header: some View {
        HStack(spacing: 10) {
            RssGlyph()
            VStack(alignment: .leading, spacing: 1) {
                Text(entry.feedLabel)
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

    /// 标题：点击打开原文；没有链接（feed 把全文发过来了）就只是一行字
    @ViewBuilder
    private var title: some View {
        if let url = entry.articleURL {
            Button {
                openURL(url)
            } label: {
                titleText
            }
            .buttonStyle(.plain)
        } else {
            titleText
        }
    }

    private var titleText: some View {
        Text(entry.displayTitle)
            .font(.subheadline.weight(.medium))
            .multilineTextAlignment(.leading)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// 显示的是 feed 声明的发布时间；被钳过的排序位置在详情里说明，
    /// 卡片上同时印两个时间只会让人以为出了错
    private var captionText: String {
        let shown = entry.publishedAt ?? item.datetime
        switch MessageTimestamp.style(for: shown) {
        case .relative:
            return shown.formatted(.relative(presentation: .named))
        case .absolute:
            return shown.formatted(date: .abbreviated, time: .shortened)
        }
    }
}
