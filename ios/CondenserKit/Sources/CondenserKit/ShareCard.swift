import Foundation

// 「生成图片并分享」的卡片内容模型：一条 item 到底有哪些东西要画进那张长图。
//
// 为什么是一个源无关的模型，而不是四个 source 各画各的：四张卡片的骨架是同一个
// （头像/标记 + 名称 + 副标题 + 可选标题 + 元信息 + 正文块 + 落款），差别只在
// 「有哪些块、什么顺序」。把这一步做成纯数据，取舍就有测试盯着（X 的判定与反馈不进图、
// RSS 用全文而不是列表摘录），app 层也只剩一个渲染器，四个源的观感不会各自漂移。
//
// 这里没有 UIKit / SwiftUI：图片只以「后端怎么取」的形态出现（ShareImageSource），
// 由 app 层换算成带 Bearer 的 URL —— 客户端从不直连源站，这条规则在分享图里同样成立。

// MARK: - 图片

/// 卡片里一张图的来源。分享图是同步渲染的一帧，所以图必须先取好再注入，
/// 这个枚举就是「取哪张」的说明书（app 层 → APIClient 的对应 URL）。
public enum ShareImageSource: Equatable, Hashable, Sendable {
    /// Telegram 媒体代理。分享图按 1200px 宽出，正文图一律取原图而不是缩略图
    /// （缩略图约 320px，放大到 1200 是糊的）；预览卡的小图才用 thumb。
    case tgMedia(channelID: Int, messageID: Int, thumb: Bool)
    case channelAvatar(Int)
    case xAvatar(handle: String)
    /// 任意外站图片经服务端代理（推文媒体、RSS 正文图、链接预览图）
    case proxied(String)
}

/// 一张要预载的图 + 它的纵横比线索（取不到时按这个比例画占位块，布局不塌）
public struct ShareImageRef: Equatable, Hashable, Sendable {
    public let source: ShareImageSource
    public let width: Int?
    public let height: Int?

    public init(_ source: ShareImageSource, width: Int? = nil, height: Int? = nil) {
        self.source = source
        self.width = width
        self.height = height
    }

    public var aspectRatio: Double? {
        guard let width, let height, width > 0, height > 0 else { return nil }
        return Double(width) / Double(height)
    }
}

// MARK: - 卡片的零件

/// 头像位：能取到图就取图（取不到画字母），信源本身没有头像的画信源标记。
/// seed 与 initial 一起带过来，是为了字母头像的取色规则与 app 里那份一致。
public enum ShareAvatar: Equatable, Sendable {
    case remote(ShareImageRef, initial: String, seed: Int)
    case letter(initial: String, seed: Int)
    case glyph(ShareGlyph)
}

public enum ShareGlyph: String, Equatable, Sendable {
    case hn, x, rss
}

/// 元信息行的一项。存语义而不是 SF Symbol 名字：Kit 不认识图标，
/// 而「metrics 行在不在」这种断言要的正是语义。
public enum ShareMeta: Equatable, Sendable {
    case score(Int)
    case comments(Int)
    case likes(Int)
    case retweets(Int)
    case replies(Int)
    case text(String)
}

/// 正文块序列里的一块。四个源的正文差异全在这里，渲染器只认这几种。
public enum ShareBlock: Equatable, Sendable {
    case text(String)
    /// 元信息行。之所以是块而不是卡片上的一个字段：它在四个源里的位置不一样
    /// （HN 紧跟标题，X 在正文与引用推之后），而位置是抽屉里定好的观感
    case meta([ShareMeta])
    case image(ShareImageRef)
    /// 多图方格（X 的多媒体推文；TG 相册按抽屉的样子逐张全宽，不并成方格）
    case imageGrid([ShareImageRef])
    /// RSS 的 AI 摘要块——机器的转述必须标出来，图发出去更是如此
    case summary(String)
    case quote(ShareQuote)
    case linkCard(ShareLinkCard)
    /// 视频 / 文件这类画不出来的媒体，留一行说明而不是让它凭空消失
    case fileChip(String)
    /// 一行小字标记（隐藏来源的转发）
    case note(String)
}

/// 内嵌的被引推文
public struct ShareQuote: Equatable, Sendable {
    public let avatar: ShareAvatar
    public let name: String
    public let handle: String?
    public let text: String?
    public let image: ShareImageRef?

    public init(
        avatar: ShareAvatar, name: String, handle: String?, text: String?, image: ShareImageRef?
    ) {
        self.avatar = avatar
        self.name = name
        self.handle = handle
        self.text = text
        self.image = image
    }
}

/// 链接预览卡（TG 自带的网页预览 / HN ingest 时预取的元数据 / X 长文）
public struct ShareLinkCard: Equatable, Sendable {
    public let site: String?
    public let title: String?
    public let description: String?
    public let image: ShareImageRef?

    public init(site: String?, title: String?, description: String?, image: ShareImageRef?) {
        self.site = site
        self.title = title
        self.description = description
        self.image = image
    }
}

// MARK: - 卡片

public struct ShareCard: Equatable, Sendable {
    /// 条目 key：文件名用它，接收端看到的就不是 IMG_0001
    public let key: String
    public let source: String
    public let avatar: ShareAvatar
    /// 头部主体名（频道 / Hacker News / 推文作者 / feed 名）
    public let title: String
    /// 头部第二行（转发来源 + 时间 / 提交信息 / @handle + 时间 / 作者 + 发布时间）
    public let subtitle: String?
    /// 标题行（HN story 与 RSS 条目的主角；TG / X 没有标题这回事）
    public let headline: String?
    public let blocks: [ShareBlock]
    /// 落款右侧的一小行
    public let footnote: String?

    public init(
        key: String, source: String, avatar: ShareAvatar, title: String, subtitle: String?,
        headline: String? = nil, blocks: [ShareBlock] = [], footnote: String? = nil
    ) {
        self.key = key
        self.source = source
        self.avatar = avatar
        self.title = title
        self.subtitle = subtitle
        self.headline = headline
        self.blocks = blocks
        self.footnote = footnote
    }
}

public extension ShareCard {
    /// 预载图片的上限。高度不封顶是刻意的（忠实渲染全文），但图片数不能不封顶：
    /// 一篇几十张图的长文会把「点一下按钮」变成一分钟的等待。超出的图渲染成占位块，
    /// 版面仍然是对的。
    static let maxImages = 24

    /// 要预载的图片，按出现顺序去重后截到上限。头像也在里面——它是这张卡的身份。
    var imageRefs: [ShareImageRef] {
        var seen = Set<ShareImageRef>()
        var refs: [ShareImageRef] = []
        func add(_ ref: ShareImageRef?) {
            guard let ref, !seen.contains(ref), refs.count < Self.maxImages else { return }
            seen.insert(ref)
            refs.append(ref)
        }
        add(avatar.imageRef)
        for block in blocks {
            switch block {
            case let .image(ref):
                add(ref)
            case let .imageGrid(refs):
                refs.forEach(add)
            case let .quote(quote):
                add(quote.avatar.imageRef)
                add(quote.image)
            case let .linkCard(card):
                add(card.image)
            case .text, .meta, .summary, .fileChip, .note:
                continue
            }
        }
        return refs
    }

    /// 分享出去的文件名（不含扩展名——格式由编码那一步定）：
    /// 接收端的聊天窗口里显示的就是这个，不该是 IMG_0001
    var fileBaseName: String {
        "condenser-\(key.replacingOccurrences(of: ":", with: "-"))"
    }
}

public extension ShareAvatar {
    var imageRef: ShareImageRef? {
        if case let .remote(ref, _, _) = self { return ref }
        return nil
    }
}

// MARK: - 构建

public extension ShareCard {
    /// item → 卡片内容；nil = 这条 envelope 没有可渲染的 payload（未知信源）。
    ///
    /// - Parameters:
    ///   - channelTitle: TG 的频道名（订阅表 join 出来的，Kit 自己不知道）
    ///   - articleBlocks: RSS 详情取回的全文块。**RSS 必须用它**：列表载荷只有约
    ///     500 字的摘录，拿摘录出图等于把一篇文章截在半句话上。没有时才退回摘录
    ///     ——取全文失败的条目仍然分享得出去，只是短。
    static func build(
        item: TimelineItem,
        channelTitle: String? = nil,
        articleBlocks: [RssBlock]? = nil
    ) -> ShareCard? {
        if let message = item.telegram {
            return telegram(item: item, message: message, channelTitle: channelTitle)
        }
        if let story = item.hn {
            return hn(item: item, story: story)
        }
        if let tweet = item.x {
            return x(item: item, tweet: tweet)
        }
        if let entry = item.rss {
            return rss(item: item, entry: entry, articleBlocks: articleBlocks)
        }
        return nil
    }

    // MARK: Telegram

    /// 抽屉里有而这里没有的：`MessageStatsRow`（实时拉的浏览/转发/表情，是「此刻」
    /// 的数字，印进一张会传播的图里只会过期）与动作按钮行。
    private static func telegram(
        item: TimelineItem, message: DisplayMessage, channelTitle: String?
    ) -> ShareCard {
        let name = channelTitle ?? message.channel?.title ?? "频道 \(message.channelID)"
        let source = message.forwardSource
        let displayName = source?.name ?? name
        let stamp = timestamp(message.date)
        var blocks: [ShareBlock] = []
        // 有来源主体的转发已经在头部说清楚了，只剩隐藏来源时才补这行降级标记
        if message.isForwarded, source == nil {
            blocks.append(.note("转发"))
        }
        if let text = message.text, !text.isEmpty {
            blocks.append(.text(text))
        }
        for photo in message.mediaItems where photo.mediaType == "photo" && photo.hasMedia {
            blocks.append(.image(ShareImageRef(
                .tgMedia(channelID: message.channelID, messageID: photo.messageID, thumb: false),
                width: photo.width, height: photo.height)))
        }
        for other in message.mediaItems
        where other.hasMedia && other.mediaType != "photo" && other.mediaType != "webpage" {
            blocks.append(.fileChip(other.mediaType == "document" ? "视频 / 文件" : (other.mediaType ?? "附件")))
        }
        if let webpage = message.webpage {
            blocks.append(.linkCard(ShareLinkCard(
                site: webpage.siteName, title: webpage.title, description: webpage.description,
                image: webpage.hasPhoto
                    ? ShareImageRef(.tgMedia(
                        channelID: message.channelID, messageID: message.id, thumb: true))
                    : nil)))
        }
        return ShareCard(
            key: item.key, source: item.source,
            avatar: channelAvatar(id: source != nil ? source?.peerID : message.channelID,
                                  name: displayName),
            title: displayName,
            subtitle: source != nil ? "Forwarded by \(name) · \(stamp)" : stamp,
            blocks: blocks,
            footnote: stamp)
    }

    // MARK: Hacker News

    private static func hn(item: TimelineItem, story: HnStory) -> ShareCard {
        var meta: [ShareMeta] = [.score(story.score), .comments(story.commentsCount)]
        if let domain = story.domain {
            meta.append(.text(domain))
        }
        // 与抽屉同序：标题 → 元信息 → 自文正文 → 预览卡
        var blocks: [ShareBlock] = [.meta(meta)]
        if let text = story.text, !text.isEmpty {
            blocks.append(.text(hnPlainText(fromHTML: text)))
        }
        if let preview = story.preview, preview.error == nil,
           preview.title != nil || preview.description != nil {
            blocks.append(.linkCard(ShareLinkCard(
                site: preview.siteName, title: preview.title,
                description: nonEmpty(preview.description),
                image: preview.image.map { ShareImageRef(.proxied($0)) })))
        }
        let submitted = story.submittedAt.map(timestamp)
        return ShareCard(
            key: item.key, source: item.source,
            avatar: .glyph(.hn),
            title: "Hacker News",
            subtitle: submitted.map { "\(story.author.map { "\($0) · " } ?? "")提交于 \($0)" },
            headline: story.title ?? "(untitled)",
            blocks: blocks,
            // 头部已经印了提交时间，落款处域名才是新信息
            footnote: story.domain ?? submitted)
    }

    // MARK: X

    /// 抽屉里有而这里没有的：判定区、反馈区、info 区。三样都是**读者与机器之间**的
    /// 私事——判定是机器猜你的口味，反馈是你的态度，都不该跟着推文发给别人。
    private static func x(item: TimelineItem, tweet: XTweet) -> ShareCard {
        var blocks: [ShareBlock] = []
        if let handle = tweet.rtOfHandle {
            blocks.append(.note("转推自 @\(handle)"))
        }
        if let body = tweet.bodyText {
            blocks.append(.text(body))
        }
        if let article = tweet.article, article.title != nil {
            blocks.append(.linkCard(ShareLinkCard(
                site: nil, title: article.title, description: article.previewText, image: nil)))
        }
        let media = tweet.displayedMedia.map(mediaRef)
        if media.count == 1 {
            blocks.append(.image(media[0]))
        } else if media.count > 1 {
            blocks.append(.imageGrid(media))
        }
        if let quote = tweet.quote {
            blocks.append(.quote(ShareQuote(
                avatar: quote.authorHandle.map {
                    ShareAvatar.remote(ShareImageRef(.xAvatar(handle: $0)),
                                       initial: initial(quote.displayName), seed: seed($0))
                } ?? .letter(initial: initial(quote.displayName), seed: seed(quote.displayName)),
                name: quote.displayName,
                handle: quote.authorName != nil ? quote.authorHandle : nil,
                text: nonEmpty(quote.text),
                image: quote.media?.first.map(mediaRef))))
        }
        // 互动数排在最后，与抽屉同序：正文与引用推读完了，才轮到这条推的数字
        if let metrics = tweet.metrics {
            blocks.append(.meta([.likes(metrics.likeCount), .retweets(metrics.retweetCount),
                                 .replies(metrics.replyCount)]))
        }
        let stamp = timestamp(tweet.createdAt ?? item.datetime)
        return ShareCard(
            key: item.key, source: item.source,
            avatar: tweet.authorHandle.map {
                ShareAvatar.remote(ShareImageRef(.xAvatar(handle: $0)),
                                   initial: initial(tweet.displayName), seed: seed($0))
            } ?? .glyph(.x),
            title: tweet.displayName,
            subtitle: tweet.authorHandle.map { "@\($0) · \(stamp)" } ?? stamp,
            blocks: blocks,
            footnote: stamp)
    }

    /// 推文媒体：出图取原图（`url`），视频只有缩略图可用。
    /// 卡片上用的是 `:small` 变体，够画 375pt 宽的屏，但 1200px 的分享图会看出糊。
    private static func mediaRef(_ media: XMediaItem) -> ShareImageRef {
        let raw = media.isVideo ? (media.previewUrl ?? media.url) : (media.url ?? media.previewUrl)
        return ShareImageRef(.proxied(raw ?? ""), width: media.width, height: media.height)
    }

    // MARK: RSS

    private static func rss(
        item: TimelineItem, entry: RssEntry, articleBlocks: [RssBlock]?
    ) -> ShareCard {
        var blocks: [ShareBlock] = []
        if let summary = entry.displaySummary {
            blocks.append(.summary(summary))
        }
        if let article = articleBlocks, !article.isEmpty {
            for block in article {
                switch block {
                case let .text(text):
                    blocks.append(.text(text))
                case let .image(image):
                    blocks.append(.image(ShareImageRef(
                        .proxied(image.src), width: image.width, height: image.height)))
                }
            }
        } else if let text = entry.contentText {
            blocks.append(.text(text))
        }
        let published = entry.publishedAt.map(timestamp)
        return ShareCard(
            key: item.key, source: item.source,
            avatar: .glyph(.rss),
            title: entry.feedLabel,
            subtitle: published.map { "\(entry.author.map { "\($0) · " } ?? "")发布于 \($0)" },
            headline: entry.displayTitle,
            blocks: blocks,
            footnote: entry.articleURL?.host() ?? published ?? timestamp(item.datetime))
    }

    // MARK: 小工具

    private static func channelAvatar(id: Int?, name: String) -> ShareAvatar {
        guard let id else { return .letter(initial: initial(name), seed: seed(name)) }
        return .remote(ShareImageRef(.channelAvatar(id)), initial: initial(name), seed: id)
    }

    private static func timestamp(_ date: Date) -> String {
        date.formatted(date: .abbreviated, time: .shortened)
    }

    private static func initial(_ text: String) -> String {
        text.first.map(String.init)?.uppercased() ?? "#"
    }

    private static func seed(_ text: String) -> Int {
        text.unicodeScalars.reduce(0) { $0 + Int($1.value) }
    }

    private static func nonEmpty(_ text: String?) -> String? {
        guard let text, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return text
    }
}
