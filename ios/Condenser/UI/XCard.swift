import SwiftUI
import CondenserKit

/// X 的方形标记（前景色底 + 反色字），列表/详情的信源图标位；
/// For You 没有作者头像可用，用它顶上。
struct XGlyph: View {
    var size: CGFloat = 36

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.22)
            .fill(Color.primary)
            .frame(width: size, height: size)
            .overlay {
                Text("𝕏")
                    .font(.system(size: size * 0.6))
                    .foregroundStyle(Color(.systemBackground))
            }
    }
}

/// 推文作者头像：后端 unavatar 代理（bird 输出里没有头像 URL），
/// 404 回退按 handle 稳定取色的字母头像——For You 一屏 ~46 个不同作者，
/// 头像是最强的定位线索，全字母的话几乎无效。
struct XAvatarView: View {
    let handle: String?
    let name: String?
    var size: CGFloat = 36

    @Environment(ReaderSession.self) private var reader
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                fallbackColor
                Text(initial)
                    .font(.system(size: size * 0.45, weight: .semibold))
                    .foregroundStyle(.white)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .task(id: handle) {
            guard let handle, !handle.isEmpty else { return }
            image = try? await ImageLoader.shared.load(
                reader.api.authedRequest(reader.api.xAvatarURL(handle: handle)))
        }
    }

    private var initial: String {
        (name ?? handle).flatMap { $0.first.map(String.init) }?.uppercased() ?? "#"
    }

    private var fallbackColor: Color {
        let seed = (handle ?? name ?? "?").unicodeScalars.reduce(0) { $0 + Int($1.value) }
        let palette: [Color] = [.blue, .green, .orange, .pink, .purple, .teal, .indigo, .red]
        return palette[abs(seed) % palette.count]
    }
}

/// 一条推文的卡片：作者身份作主体（For You 一页混着几十个作者，「是谁」才是
/// 定位线索），正文（转推的 RT 前缀改由标题行承载，长文的 text 就是标题不重复打印），
/// 媒体、内嵌引用推，底栏 = 左边机器的判定、右边你自己的拇指。
/// 已读/收藏态在外层 TimelineItem envelope 上。
struct XCard: View {
    let item: TimelineItem
    let tweet: XTweet
    /// 收藏列表不展示未读点
    var showsUnread = true
    var onToggleSaved: () -> Void
    var onFeedback: (ItemFeedback) -> Void
    var onReason: (ItemFeedbackReason) -> Void
    /// 点击第 i 张图片（timeline 直接全屏查看，不经详情 sheet）
    var onOpenPhoto: ((Int) -> Void)? = nil

    @Environment(ReaderSession.self) private var reader

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            if let handle = tweet.rtOfHandle {
                Label("Retweeted @\(handle)", systemImage: "arrow.2.squarepath")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            if let body = tweet.bodyText {
                TruncatableText(text: body, urlEntities: tweet.urls)
            }
            if let article = tweet.article, article.title != nil {
                XArticleCard(article: article)
            }
            XMediaView(media: tweet.displayedMedia, onOpenPhoto: onOpenPhoto)
            if let quote = tweet.quote {
                XQuoteCard(quote: quote)
            }
            footer
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .contentShape(Rectangle())
    }

    private var header: some View {
        HStack(spacing: 10) {
            XAvatarView(handle: tweet.authorHandle, name: tweet.authorName)
            VStack(alignment: .leading, spacing: 1) {
                Text(tweet.displayName)
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
            Button(action: onToggleSaved) {
                Image(systemName: item.isSaved ? "star.fill" : "star")
                    .foregroundStyle(item.isSaved ? .orange : .secondary)
            }
            .buttonStyle(.plain)
        }
    }

    /// 底栏：左边机器的判定，右边读者自己的拇指，中间是推文自己的数字。
    /// bird 没给 metrics 时底栏照常出现——反馈按钮必须永远可用。
    private var footer: some View {
        HStack(spacing: 14) {
            if let verdict = tweet.verdict, verdict.isFinding {
                XVerdictBadge(verdict: verdict)
            }
            if let metrics = tweet.metrics {
                Label("\(metrics.likeCount)", systemImage: "heart")
                    .labelStyle(CompactMetaLabelStyle())
                Label("\(metrics.retweetCount)", systemImage: "arrow.2.squarepath")
                    .labelStyle(CompactMetaLabelStyle())
                Label("\(metrics.replyCount)", systemImage: "bubble.right")
                    .labelStyle(CompactMetaLabelStyle())
            }
            Spacer(minLength: 0)
            XFeedbackButtons(feedback: item.feedback, onFeedback: onFeedback, onReason: onReason)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    /// 关注人 feed 展示推文时间；For You 的排序位是「抓到的时刻」，
    /// 所以额外标一下发布时间，免得几天前的老推排在最前显得莫名其妙
    private var captionText: String {
        let shown = tweet.createdAt ?? item.datetime
        let stamp = switch MessageTimestamp.style(for: shown) {
        case .relative: shown.formatted(.relative(presentation: .named))
        case .absolute: shown.formatted(date: .abbreviated, time: .shortened)
        }
        if let handle = tweet.authorHandle, tweet.authorName != nil {
            return "@\(handle) · \(stamp)"
        }
        return stamp
    }
}

/// 长文卡：bird 只给得到标题 + ~200 字符预览，正文拿不到（点进原推看）
struct XArticleCard: View {
    let article: XArticle

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let title = article.title {
                Text(title)
                    .font(.subheadline.weight(.medium))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let preview = article.previewText {
                Text(preview)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(4)
            }
        }
        .padding(10)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10))
    }
}

/// 内嵌的被引推：借用转发框的视觉语言（缩进的软背景卡），点击打开原推
struct XQuoteCard: View {
    let quote: XQuote

    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                XAvatarView(handle: quote.authorHandle, name: quote.authorName, size: 18)
                Text(quote.displayName)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                if let handle = quote.authorHandle, quote.authorName != nil {
                    Text("@\(handle)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            if let text = quote.text, !text.isEmpty {
                Text(linkified(text, urlEntities: quote.urls))
                    .font(.caption)
                    .lineLimit(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            // 引用推的媒体只给一条窄缩略图：主推才是阅读主体
            if let media = quote.media?.first, let thumb = media.thumbnailURL {
                XMediaThumb(url: thumb, isVideo: media.isVideo, ratio: media.aspectRatio ?? 16 / 9,
                            cornerRadius: 8)
                    .frame(maxHeight: 160)
            }
        }
        .padding(10)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10))
        .contentShape(RoundedRectangle(cornerRadius: 10))
        .onTapGesture { openURL(quote.tweetURL) }
    }
}

/// 推文媒体：单图按宽高预留（竖图收敛到 3:4），多图方形网格；
/// 视频只显示缩略图 + 播放角标（v1 不做内嵌播放，点击不开查看器）。
/// **传进来的就是要画的那些**（`XTweet.displayedMedia`）——onOpenPhoto 的下标
/// 与 `photoIndex(forDisplayed:)` 靠这一点对齐，这里不再二次过滤。
struct XMediaView: View {
    let media: [XMediaItem]
    var onOpenPhoto: ((Int) -> Void)? = nil

    var body: some View {
        if media.count == 1 {
            thumb(media[0], index: 0, ratio: previewRatio(media[0]), cornerRadius: 10)
        } else if media.count > 1 {
            let columns = Array(
                repeating: GridItem(.flexible(), spacing: 4),
                count: media.count == 2 || media.count == 4 ? 2 : 3)
            LazyVGrid(columns: columns, spacing: 4) {
                ForEach(Array(media.enumerated()), id: \.element.thumbnailURL) { index, item in
                    thumb(item, index: index, ratio: 1, cornerRadius: 6)
                }
            }
        }
    }

    private func thumb(
        _ item: XMediaItem, index: Int, ratio: CGFloat, cornerRadius: CGFloat
    ) -> some View {
        XMediaThumb(
            url: item.thumbnailURL ?? "", isVideo: item.isVideo,
            ratio: ratio, cornerRadius: cornerRadius)
            .onTapGesture { onOpenPhoto?(index) }
    }

    /// 竖图收敛到最小 3:4，避免单图占满整屏（与 TG 卡片同款处理）
    private func previewRatio(_ item: XMediaItem) -> CGFloat {
        guard let ratio = item.aspectRatio else { return 4 / 3 }
        return max(CGFloat(ratio), 3 / 4)
    }
}

/// 一张推文缩略图：固定纵横比占位盒 + 代理加载；视频叠播放角标。
/// 图片走 /api/preview/image 代理，读一条推文不会让 X 看到读者的 IP。
struct XMediaThumb: View {
    let url: String
    var isVideo = false
    var ratio: CGFloat = 4 / 3
    var cornerRadius: CGFloat = 10

    @Environment(ReaderSession.self) private var reader

    var body: some View {
        Color.clear
            .aspectRatio(ratio, contentMode: .fit)
            .overlay {
                AuthedAsyncImage(
                    request: reader.api.authedRequest(reader.api.proxiedImageURL(url)))
            }
            .overlay(alignment: .center) {
                if isVideo {
                    Image(systemName: "play.fill")
                        .font(.title3)
                        .foregroundStyle(.white)
                        .padding(10)
                        .background(.black.opacity(0.45), in: Circle())
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius))
            .contentShape(RoundedRectangle(cornerRadius: cornerRadius))
    }
}

/// 机器对一条 For You 推文的看法（计划 Phase 4），停在底栏左侧与拇指对望。
/// neutral / nil 什么都不画：neutral 是默认答案不是结论，给它加徽标等于每张卡都挂一个。
/// 文案与 web 保持一致（英文），详情面板里才用中文展开证据。
struct XVerdictBadge: View {
    let verdict: XVerdict

    var body: some View {
        Label(label, systemImage: icon)
            .labelStyle(CompactMetaLabelStyle())
            .foregroundStyle(tone)
            .lineLimit(1)
    }

    private var label: String {
        verdict == .positive ? "Recommended" : "Likely not for you"
    }

    private var icon: String {
        verdict == .positive ? "sparkles" : "hand.thumbsdown"
    }

    private var tone: Color {
        verdict == .positive ? .green : .pink
    }
}

/// 底栏的拇指对：点已选中的那一侧 = 撤销，点另一侧 = 改正。
/// 所有 X 推文都可标注（关注人 feed 也算——扩大训练集），
/// 但打标本身不隐藏、不标已读、不改排序。
///
/// 「踩」之后追问一次理由：光一个踩标的是整条推文，可惹到你的通常只是其中一样
/// 属性（话题 / 广告腔 / AI 味 / 作者），而一条推文只有一个向量，四者被平均成
/// 同一个点。用 confirmationDialog 而不是内联 chip 行：手机上一行摆不下四个中文
/// 标签，而系统弹层本来就是「一次点击选一项、Cancel 即跳过」的形状——跳过是免费
/// 的，标签退化成原来的整条标注。
struct XFeedbackButtons: View {
    let feedback: ItemFeedback?
    var onFeedback: (ItemFeedback) -> Void
    /// 缺省实现让还没接理由的调用点（如果有）照常编译成「不追问」
    var onReason: ((ItemFeedbackReason) -> Void)?

    @State private var askingReason = false

    var body: some View {
        HStack(spacing: 12) {
            button(.up, systemImage: "hand.thumbsup", tint: .green)
            button(.down, systemImage: "hand.thumbsdown", tint: .pink)
        }
        .confirmationDialog("为什么不喜欢？", isPresented: $askingReason, titleVisibility: .visible) {
            ForEach(ItemFeedbackReason.offered, id: \.self) { reason in
                Button(reason.label) { onReason?(reason) }
            }
            Button("跳过", role: .cancel) {}
        }
    }

    private func button(_ side: ItemFeedback, systemImage: String, tint: Color) -> some View {
        let selected = feedback == side
        return Button {
            onFeedback(side)
            // 只有「这一下确实把它标成了踩」才追问：撤销和改成赞都不该弹
            askingReason = onReason != nil && ItemFeedback.next(current: feedback, tapped: side) == .down
        } label: {
            Image(systemName: selected ? "\(systemImage).fill" : systemImage)
                .foregroundStyle(selected ? tint : .secondary)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(side == .up ? "喜欢" : "不喜欢")
    }
}
