import SwiftUI
import CondenserKit

/// 推文详情 bottom sheet：作者 + 全文（可选择）+ 媒体 + 引用推 + 互动数 +
/// 判定证据 + 反馈 + 打开原推/主页。
/// 判定这一段是「先打标不隐藏」的配套：说得出「因为它像你标过的这几条」，
/// 误判才纠错得了——纠错的那一下点击又回流成训练样本。
struct XDetailSheet: View {
    let item: TimelineItem
    let tweet: XTweet
    var onToggleSaved: () -> Void
    var onFeedback: (ItemFeedback) -> Void
    var onReason: (ItemFeedbackReason) -> Void

    @State private var safariItem: SafariItem?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                if let body = tweet.bodyText {
                    SelectableTextView(text: body)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if let article = tweet.article, article.title != nil {
                    XArticleCard(article: article)
                }
                XMediaView(media: tweet.displayedMedia)
                if let quote = tweet.quote {
                    XQuoteCard(quote: quote)
                }
                metaLine
                Divider()
                feedbackRow
                if let verdict = tweet.verdict {
                    verdictSection(verdict)
                }
                infoSection
                Divider()
                actions
            }
            .padding(16)
        }
        .readingFontScale()
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .environment(\.openURL, OpenURLAction { url in
            safariItem = SafariItem(url: url)
            return .handled
        })
        .sheet(item: $safariItem) { item in
            SafariView(url: item.url)
                .ignoresSafeArea()
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            XAvatarView(handle: tweet.authorHandle, name: tweet.authorName, size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(tweet.displayName)
                    .font(.headline)
                    .lineLimit(1)
                if let handle = tweet.authorHandle {
                    Text("@\(handle)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
        }
    }

    @ViewBuilder
    private var metaLine: some View {
        if let handle = tweet.rtOfHandle {
            Label("转推自 @\(handle)", systemImage: "arrow.2.squarepath")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        if let metrics = tweet.metrics {
            HStack(spacing: 12) {
                Label("\(metrics.likeCount)", systemImage: "heart")
                    .labelStyle(CompactMetaLabelStyle())
                Label("\(metrics.retweetCount)", systemImage: "arrow.2.squarepath")
                    .labelStyle(CompactMetaLabelStyle())
                Label("\(metrics.replyCount)", systemImage: "bubble.right")
                    .labelStyle(CompactMetaLabelStyle())
                Spacer(minLength: 0)
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }

    /// 理由只在这里回显：卡片上不画（每条都挂个 chip 太吵），
    /// 但过一阵回头想知道「当初那个踩到底嫌的是什么」时，答案得找得到。
    private var feedbackRow: some View {
        HStack {
            Text("反馈")
                .font(.subheadline.weight(.medium))
            Spacer()
            if let reason = item.feedbackReason {
                Text(reason.label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            XFeedbackButtons(feedback: item.feedback, onFeedback: onFeedback, onReason: onReason)
                .font(.body)
        }
    }

    /// 判定与它的证据。neutral 也在这里显示——卡片上不画是因为它不是结论，
    /// 但你专门点进来问「它怎么看这条」时，「没表态」本身就是答案。
    private func verdictSection(_ verdict: XVerdict) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("判定")
                    .font(.subheadline.weight(.medium))
                Spacer()
                Text(verdictLabel(verdict))
                    .font(.subheadline)
                    .foregroundStyle(verdictTone(verdict))
            }
            if let score = tweet.verdictMeta?.score {
                Text("打分 \(score, specifier: "%.2f")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let reason = tweet.verdictMeta?.reason {
                Text(reasonLabel(reason))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(tweet.verdictMeta?.neighbors ?? [], id: \.tweetID) { neighbor in
                XVerdictNeighborRow(neighbor: neighbor)
            }
            if let model = tweet.verdictMeta?.model {
                Text(model)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10))
    }

    private var infoSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            infoRow("来自", XFeed.label(tweet.feed, name: nil))
            if let created = tweet.createdAt {
                infoRow("发布于", created.formatted(date: .abbreviated, time: .shortened))
            }
            // For You 按抓取时刻排序，两个时间都摆出来才解释得清位置
            if let seen = tweet.firstSeenAt {
                infoRow("抓取于", seen.formatted(date: .abbreviated, time: .shortened))
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func infoRow(_ label: String, _ value: String) -> some View {
        HStack(spacing: 8) {
            Text(label)
            Text(value).foregroundStyle(.primary)
            Spacer(minLength: 0)
        }
    }

    private var actions: some View {
        ItemActionRow {
            ItemActionButtons(item: item, onToggleSaved: onToggleSaved)
            Button {
                safariItem = SafariItem(url: tweet.tweetURL)
            } label: {
                Label("在 X 上打开", systemImage: "safari")
                    .font(.footnote)
            }
            .buttonStyle(.bordered)
            if let profile = tweet.profileURL {
                Button {
                    safariItem = SafariItem(url: profile)
                } label: {
                    Label("作者主页", systemImage: "person")
                        .font(.footnote)
                }
                .buttonStyle(.bordered)
            }
        }
    }

    private func verdictLabel(_ verdict: XVerdict) -> String {
        switch verdict {
        case .positive: "推荐"
        case .negative: "可能不适合你"
        case .neutral: "未表态"
        case .other: "未知"
        }
    }

    private func verdictTone(_ verdict: XVerdict) -> Color {
        switch verdict {
        case .positive: .green
        case .negative: .pink
        default: .secondary
        }
    }

    private func reasonLabel(_ reason: String) -> String {
        switch reason {
        case "out_of_domain": "离所有已标注的推文都太远，没有硬判"
        case "no_text": "没有可判定的文本"
        default: reason
        }
    }
}

/// 一条投过票的近邻：作者 + 标签 + 距离，点击去看原推。
/// 一串裸 tweet id 解释不了任何事，handle 是 ingest 时顺手存下的。
struct XVerdictNeighborRow: View {
    let neighbor: XVerdictNeighbor

    @Environment(\.openURL) private var openURL

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .foregroundStyle(tone)
            Text(neighbor.handle.map { "@\($0)" } ?? neighbor.tweetID)
                .lineLimit(1)
            Text("距离 \(neighbor.distance, specifier: "%.2f")")
                .foregroundStyle(.secondary)
            Spacer(minLength: 0)
        }
        .font(.caption)
        .contentShape(Rectangle())
        .onTapGesture {
            openURL(xTweetURL(id: neighbor.tweetID, handle: neighbor.handle))
        }
    }

    private var icon: String {
        switch neighbor.label {
        case "down": "hand.thumbsdown.fill"
        case "save": "star.fill"
        default: "hand.thumbsup.fill"
        }
    }

    private var tone: Color {
        switch neighbor.label {
        case "down": .pink
        case "save": .orange
        default: .green
        }
    }
}
