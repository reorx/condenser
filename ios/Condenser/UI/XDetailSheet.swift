import SwiftUI
import CondenserKit

/// 推文详情 bottom sheet：作者 + 全文（可选择）+ 媒体 + 引用推 + 互动数 +
/// 判定证据 + 反馈 + 打开原推/主页。
/// 判定这一段是「先打标不隐藏」的配套：说得出「因为它像你标过的这几条」，
/// 误判才纠错得了——纠错的那一下点击又回流成训练样本。
///
/// 长文推（2026-09-16）的正文区换成文章：标题 + 服务端渲染好的全文块（文本可高亮、
/// 图片撑满列、点开全屏），与 `RssDetailSheet` 同一套三态——列表载荷只带
/// `has_content`，打开时 `GET /api/x/tweets/{id}` 取一次，到手前停在标题 + 预览上。
struct XDetailSheet: View {
    let item: TimelineItem
    let tweet: XTweet
    var onToggleSaved: () -> Void
    var onFeedback: (ItemFeedback) -> Void
    var onReason: (ItemFeedbackReason) -> Void

    @Environment(ReaderSession.self) private var reader
    @State private var safariItem: SafariItem?
    @State private var viewerItem: ImageViewerItem?
    @State private var annotations = ItemAnnotationsModel()
    /// 长文正文解析出的块序列：`loadArticle` 里算一次存进 state，不放进 body
    /// （一整篇的正则，2026-08-23 RSS 卡顿的教训）。nil = 还没到手，或这条就没有正文
    @State private var articleBlocks: [ArticleBlock]?
    /// 取正文这件事走完了没有。与 `articleBlocks != nil` 不是一回事：服务端还没抓到
    /// 正文时取回来是 null，那是成功，不是还在转圈
    @State private var articleLoaded = false
    @State private var articleFailed = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                if isArticle {
                    // 长文推的 text 就是标题，bodyText 实际总为 nil；万一上游改了、带出一句
                    // 推文自身的话，照样显示但不接标注——标注的定位底本是文章块
                    if let body = tweet.bodyText {
                        SelectableTextView(text: body, urlEntities: tweet.urls)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    articleSection
                } else if let body = tweet.bodyText {
                    // 引用推卡（XQuoteCard）刻意不接标注——那是别人的条目
                    AnnotatedTextView(text: body, urlEntities: tweet.urls, model: annotations)
                }
                XMediaView(media: tweet.displayedMedia)
                if let quote = tweet.quote {
                    XQuoteCard(quote: quote)
                }
                metaLine
                AnnotationFooterView(model: annotations)
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
        .task(id: tweet.id) {
            if isArticle {
                await loadArticle()
            } else {
                // 标注锚在 t.co 替换后的屏幕字符串上（xDisplayedText 与 linkifiedNS
                // 共享同一条替换规则）
                annotations.configure(
                    item: item, api: reader.api,
                    blocks: tweet.bodyText.map { [xDisplayedText($0, urlEntities: tweet.urls)] })
            }
        }
        .detailSheetPresentation()
        .externalLinks(safari: $safariItem)
        .sheet(item: $safariItem) { item in
            SafariView(url: item.url)
                .ignoresSafeArea()
        }
        .fullScreenCover(item: $viewerItem) { item in
            ImageViewerScreen(item: item)
        }
    }

    private var isArticle: Bool { tweet.article?.title != nil }

    /// 长文正文区。正文到手：标题 + 全文块；没到手：标题 + 预览卡（卡片同款），
    /// 服务端说有正文（`hasContent`）时才挂「正在加载全文…」/「正文加载失败」——
    /// 没正文的长文也会去问一次（probe 这轮没读到的，下一轮会再读），但不对着一篇
    /// 大概率没有正文的文章转圈。问完仍没有，就明说「未获取到 article 正文」（web 同款）：
    /// 那是 probe 没拿到，和请求本身失败是两回事。
    @ViewBuilder
    private var articleSection: some View {
        if let blocks = articleBlocks, !blocks.isEmpty {
            if let title = tweet.article?.title {
                Text(title)
                    .readingFont(.title3, weight: .semibold)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            ArticleBlocksView(blocks: blocks, annotations: annotations, viewerItem: $viewerItem)
        } else if let article = tweet.article {
            XArticleCard(article: article)
            let promised = article.hasContent == true
            if !articleLoaded {
                if promised {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text("正在加载全文…")
                    }
                    .readingFont(.caption)
                    .foregroundStyle(.secondary)
                }
            } else if articleFailed, promised {
                // 不弹错：退回的标题 + 预览本来就在屏幕上，是这条推文的真实样子
                Text("正文加载失败")
                    .readingFont(.caption)
                    .foregroundStyle(.secondary)
            } else {
                // 列表本就说没有正文时，请求失败也改变不了这个事实，同一句
                Text("未获取到 article 正文")
                    .readingFont(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    /// 收藏快照里已经带正文的直接解析，不必再问一次网络。X 的图片 URL 全是绝对的
    /// pbs.twimg.com，所以 baseURL 给 nil（显示时统一过 /api/preview/image 代理）。
    private func loadArticle() async {
        // blocks 先给 nil：正文到手前高亮入口保持禁用（预览不是定位底本）
        annotations.configure(item: item, api: reader.api, blocks: nil, usesBlocks: true)
        if let html = tweet.article?.contentHTML {
            applyArticle(html)
            articleLoaded = true
            return
        }
        do {
            if let html = try await reader.api.xTweet(id: tweet.id).x?.article?.contentHTML {
                applyArticle(html)
            }
        } catch {
            articleFailed = true
        }
        articleLoaded = true
    }

    private func applyArticle(_ html: String) {
        articleBlocks = CondenserKit.articleBlocks(fromHTML: html, baseURL: nil)
        annotations.setBlocks(ArticleBlocksView.textBlocks(articleBlocks))
    }

    /// sheet 自己的按钮不走 openURL 环境（那是给子树用的，读到的是外层列表的
    /// 那份，Safari 会从这张 sheet 背后弹出来），所以直接调统一出口。
    /// 两个按钮都是「去 X」：不经 Purifier——阅读开关开着时推文链接会进代理，而读者此刻
    /// 就在读这条推文，点这里要的是 X app（点赞、回复），不是它的讨论页
    private func open(_ url: URL) {
        openExternalURL(url, purify: false) { safariItem = SafariItem(url: $0) }
    }

    private var header: some View {
        HStack(spacing: 10) {
            XAvatarView(handle: tweet.authorHandle, name: tweet.authorName, size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(tweet.displayName)
                    .readingFont(.headline)
                    .lineLimit(1)
                if let handle = tweet.authorHandle {
                    Text("@\(handle)")
                        .readingFont(.caption)
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
                .readingFont(.caption)
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
            .readingFont(.caption)
            .foregroundStyle(.secondary)
        }
    }

    /// 理由只在这里回显：卡片上不画（每条都挂个 chip 太吵），
    /// 但过一阵回头想知道「当初那个踩到底嫌的是什么」时，答案得找得到。
    private var feedbackRow: some View {
        HStack {
            Text("反馈")
                .readingFont(.subheadline, weight: .medium)
            Spacer()
            if let reason = item.feedbackReason {
                Text(reason.label)
                    .readingFont(.caption)
                    .foregroundStyle(.secondary)
            }
            XFeedbackButtons(feedback: item.feedback, onFeedback: onFeedback, onReason: onReason)
                .readingFont(.body)
        }
    }

    /// 判定与它的证据。neutral 也在这里显示——卡片上不画是因为它不是结论，
    /// 但你专门点进来问「它怎么看这条」时，「没表态」本身就是答案。
    private func verdictSection(_ verdict: XVerdict) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("判定")
                    .readingFont(.subheadline, weight: .medium)
                Spacer()
                Text(verdictLabel(verdict))
                    .readingFont(.subheadline)
                    .foregroundStyle(verdictTone(verdict))
            }
            if let score = tweet.verdictMeta?.score {
                Text("打分 \(score, specifier: "%.2f")")
                    .readingFont(.caption)
                    .foregroundStyle(.secondary)
            }
            if let reason = tweet.verdictMeta?.reason {
                Text(reasonLabel(reason))
                    .readingFont(.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(tweet.verdictMeta?.neighbors ?? [], id: \.tweetID) { neighbor in
                XVerdictNeighborRow(neighbor: neighbor)
            }
            // ensemble（判定 v2 步骤 4）：每个开口的通道一行，各自的投票 + 各自的证据。
            // 旧判定没有 channels 块，这一段整体不出现。
            if let channels = tweet.verdictMeta?.channels, !channels.isEmpty {
                Text("各通道投票")
                    .readingFont(.caption)
                    .foregroundStyle(.secondary)
                ForEach(channels.sorted(by: { $0.key < $1.key }), id: \.key) { key, channel in
                    XVerdictChannelRow(key: key, channel: channel)
                }
            }
            if let model = tweet.verdictMeta?.model {
                Text(model)
                    .readingFont(.caption2)
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
        .readingFont(.caption)
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
            // 装了 X app 就直接进 app（那里才点得了赞、回得了复），没装才回落 Safari
            Button {
                open(tweet.tweetURL)
            } label: {
                Label("在 X 上打开", systemImage: "arrow.up.forward.app")
                    .readingFont(.footnote)
            }
            .buttonStyle(.bordered)
            if let profile = tweet.profileURL {
                Button {
                    open(profile)
                } label: {
                    Label("作者主页", systemImage: "person")
                        .readingFont(.footnote)
                }
                .buttonStyle(.bordered)
            }
            ShareImageButton(card: shareCard)
        }
    }

    /// 长文推的分享图用这张 sheet 取回来的正文（RSS 同理）：没走完取正文时给 nil，
    /// 按钮画出来但按不动——按下去拿到一张只有预览的图比多等一秒糟；没有正文或取失败
    /// 则退回标题 + 预览的链接卡。普通推文不等任何东西。
    private var shareCard: ShareCard? {
        if isArticle, !articleLoaded { return nil }
        return ShareCard.build(item: item, articleBlocks: articleBlocks)
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

/// ensemble 的一行通道投票：通道名（reader 的语言）+ 投票 + 分数，
/// 证据（A 的账号记录 / C 的属性 / D 的词）作小字第二行——B 的证据就是上面的近邻列表，
/// 不重复画。
struct XVerdictChannelRow: View {
    let key: String
    let channel: XVerdictChannel

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(name)
                if let verdict = channel.verdict {
                    Text(voteLabel(verdict))
                        .foregroundStyle(tone(verdict))
                }
                if channel.shadow == true {
                    Text("影子（不参与投票）")
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                Text(String(format: "%.2f", channel.score))
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }
            if let record = channel.record {
                Text(record)
                    .readingFont(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            } else if !channel.evidence.isEmpty {
                Text(channel.evidence.map { "\($0.name) \(String(format: "%+.2f", $0.weight))" }
                    .joined(separator: " · "))
                    .readingFont(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .readingFont(.caption)
    }

    private var name: String {
        switch key {
        case "a": "作者记录"
        case "b": "话题相似"
        case "c": "内容属性"
        case "d": "词面特征"
        default: key
        }
    }

    private func voteLabel(_ verdict: XVerdict) -> String {
        switch verdict {
        case .positive: "判正"
        case .negative: "判负"
        case .neutral: "中性"
        case .other: "未知"
        }
    }

    private func tone(_ verdict: XVerdict) -> Color {
        switch verdict {
        case .positive: .green
        case .negative: .pink
        default: .secondary
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
        .readingFont(.caption)
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
