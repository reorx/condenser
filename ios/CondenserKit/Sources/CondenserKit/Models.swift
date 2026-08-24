import Foundation

// 后端 JSON 契约的 Swift 镜像。字段事实来源：frontend/src/lib/types.ts
// （snake_case → CodingKeys；日期 UTC，tz-aware 与 naive 两种形式都能解析）。
// 多信源契约（Phase 4）：timeline/records 条目是 TimelineItem envelope，
// read/save 以 item key（"tg:{cid}:{mid}" / "hn:{sid}"）为出入参。

/// 后端日期字符串 → Date：支持 "Z" / "+00:00" / 小数秒 / naive（按 UTC 补 Z）。
public func parseAPIDate(_ raw: String) -> Date? {
    guard !raw.isEmpty else { return nil }
    let text = raw.contains("Z") || raw.contains("+") ? raw : raw + "Z"
    let withFraction = ISO8601DateFormatter()
    withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let d = withFraction.date(from: text) { return d }
    let plain = ISO8601DateFormatter()
    plain.formatOptions = [.withInternetDateTime]
    return plain.date(from: text)
}

public extension JSONDecoder {
    /// condenser API 专用 decoder：自定义日期策略。
    static var condenserAPI: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { d in
            let container = try d.singleValueContainer()
            let raw = try container.decode(String.self)
            guard let date = parseAPIDate(raw) else {
                throw DecodingError.dataCorruptedError(
                    in: container, debugDescription: "Unparseable date: \(raw)")
            }
            return date
        }
        return decoder
    }
}

public extension JSONEncoder {
    static var condenserAPI: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }
}

// MARK: - 信源

/// 信源枚举值（envelope 的 source 字段用原始字符串承载，未知信源不炸解码）
public enum SourceID {
    public static let telegram = "telegram"
    public static let hn = "hn"
    public static let x = "x"
    public static let rss = "rss"

    /// 信源展示名（切换菜单 / 订阅分组标题）
    public static func label(_ source: String) -> String {
        switch source {
        case telegram: "Telegram"
        case hn: "Hacker News"
        case x: "X"
        case rss: "RSS"
        default: source
        }
    }
}

/// X 的算法流 feed key；关注人 feed 的 key 就是 handle。
/// For You 不进聚合 timeline（计划决策「隔离 + 降频」），只能从它自己的入口进。
public enum XFeed {
    public static let foryou = "foryou"

    /// feed 展示名：For You 固定文案，关注人回落 @handle
    public static func label(_ feed: String, name: String?) -> String {
        if feed == foryou { return name ?? "For You" }
        return name ?? "@\(feed)"
    }
}

// MARK: - Telegram payload

public struct MediaItem: Codable, Equatable, Sendable {
    public let messageID: Int
    public let mediaType: String?
    public let hasMedia: Bool
    /// 像素尺寸，历史行可能为 nil（用于预留缩略图纵横比）
    public let width: Int?
    public let height: Int?

    enum CodingKeys: String, CodingKey {
        case messageID = "message_id"
        case mediaType = "media_type"
        case hasMedia = "has_media"
        case width, height
    }
}

public struct ForwardInfo: Codable, Equatable, Sendable {
    public let fromChannelID: Int?
    public let fromChannelName: String?
    public let fromUserID: Int?
    public let fromUserName: String?
    public let fromMessageID: Int?
    public let originalDate: Date?
    public let postAuthor: String?

    enum CodingKeys: String, CodingKey {
        case fromChannelID = "from_channel_id"
        case fromChannelName = "from_channel_name"
        case fromUserID = "from_user_id"
        case fromUserName = "from_user_name"
        case fromMessageID = "from_message_id"
        case originalDate = "original_date"
        case postAuthor = "post_author"
    }
}

public struct ChannelRef: Codable, Equatable, Sendable {
    public let id: Int
    public let title: String?
    public let username: String?
}

/// Telegram 自带的网页预览卡片
public struct WebPagePreview: Codable, Equatable, Sendable {
    public let url: String?
    public let displayURL: String?
    public let type: String?
    public let siteName: String?
    public let title: String?
    public let description: String?
    public let author: String?
    /// true 时预览图可通过该消息 id 走媒体代理获取
    public let hasPhoto: Bool

    enum CodingKeys: String, CodingKey {
        case url
        case displayURL = "display_url"
        case type
        case siteName = "site_name"
        case title, description, author
        case hasPhoto = "has_photo"
    }
}

/// 一个 Telegram 展示单元（相册已合并）。telememo DisplayMessage；
/// 已读/收藏标记在外层 TimelineItem envelope 上。
public struct DisplayMessage: Codable, Equatable, Sendable {
    public let id: Int
    public let channelID: Int
    public let date: Date
    public let isEdited: Bool
    public let editDate: Date?
    public let senderID: Int?
    public let senderName: String?
    public let text: String?
    public let isAlbum: Bool
    public let groupedID: Int?
    public let mediaItems: [MediaItem]
    public let webpage: WebPagePreview?
    public let isForwarded: Bool
    public let forwardInfo: ForwardInfo?
    public let views: Int?
    public let forwardsCount: Int?
    public let repliesCount: Int?
    public let rawMessageIDs: [Int]
    /// records payload 自包含的频道快照（timeline 不带）
    public let channel: ChannelRef?

    enum CodingKeys: String, CodingKey {
        case id
        case channelID = "channel_id"
        case date
        case isEdited = "is_edited"
        case editDate = "edit_date"
        case senderID = "sender_id"
        case senderName = "sender_name"
        case text
        case isAlbum = "is_album"
        case groupedID = "grouped_id"
        case mediaItems = "media_items"
        case webpage
        case isForwarded = "is_forwarded"
        case forwardInfo = "forward_info"
        case views
        case forwardsCount = "forwards_count"
        case repliesCount = "replies_count"
        case rawMessageIDs = "raw_message_ids"
        case channel
    }

    /// 转发消息的展示主体；nil = 非转发，或来源被隐藏（卡片按普通转发降级）
    public var forwardSource: ForwardSource? {
        guard isForwarded, let info = forwardInfo else { return nil }
        if let name = info.fromChannelName {
            return ForwardSource(peerID: info.fromChannelID, name: name)
        }
        if let name = info.fromUserName {
            return ForwardSource(peerID: info.fromUserID, name: name)
        }
        if let name = info.postAuthor {
            return ForwardSource(peerID: nil, name: name)
        }
        return nil
    }
}

/// 转发来源主体：peerID 可喂给 /api/channels/{id}/avatar 取头像
/// （未订阅频道后端可能 404，UI 回退首字母），nil 表示只有名字没有可用头像。
public struct ForwardSource: Equatable, Sendable {
    public let peerID: Int?
    public let name: String
}

// MARK: - Hacker News payload

/// 统一 link preview（HN story 在 ingest 时预取的 URL 元数据）
public struct LinkPreview: Codable, Equatable, Sendable {
    public let url: String
    public let title: String?
    public let description: String?
    public let image: String?
    public let siteName: String?
    /// 'fetched' | 'telegram'
    public let source: String
    public let tgImageMessageID: Int?
    public let error: String?

    enum CodingKeys: String, CodingKey {
        case url, title, description, image
        case siteName = "site_name"
        case source
        case tgImageMessageID = "tg_image_message_id"
        case error
    }
}

/// 一条归档的 Hacker News story（TimelineItem 的 hn payload）
public struct HnStory: Codable, Equatable, Sendable {
    public let id: Int
    public let title: String?
    /// nil = self-post（Ask HN 等，text 为 HTML 正文）
    public let url: String?
    public let domain: String?
    public let author: String?
    /// story / job（首页会出现 YC job，UI 弱化）
    public let type: String?
    public let text: String?
    public let submittedAt: Date?
    public let firstSeenAt: Date?
    public let score: Int
    public let commentsCount: Int
    /// query-time 当日分数排名；saved records 里为 nil
    public let dayRank: Int?
    public let peakRank: Int?
    public let backfilled: Bool
    /// ingest 预取的 url 元数据；未取到/self-post 为 nil
    public let preview: LinkPreview?

    enum CodingKeys: String, CodingKey {
        case id, title, url, domain, author, type, text
        case submittedAt = "submitted_at"
        case firstSeenAt = "first_seen_at"
        case score
        case commentsCount = "comments_count"
        case dayRank = "day_rank"
        case peakRank = "peak_rank"
        case backfilled, preview
    }

    /// HN 评论页（客户端自拼）
    public var commentsURL: URL {
        URL(string: "https://news.ycombinator.com/item?id=\(id)")!
    }

    /// 原文链接；nil = self-post
    public var externalURL: URL? {
        url.flatMap(URL.init(string:))
    }

    /// 标题点击目标：原文，self-post 回落评论页
    public var primaryURL: URL {
        externalURL ?? commentsURL
    }

    public var isJob: Bool { type == "job" }
}

// MARK: - X payload

/// 推文的一个媒体附件——bird 的形态由后端原样透传（键是 camelCase，与其它
/// payload 的 snake_case 不同，这里不加 CodingKeys 就是对的）。
/// 实测 photo/video 都带宽高，前端得以预留占位。
public struct XMediaItem: Codable, Equatable, Sendable {
    public let type: String
    public let url: String?
    public let previewUrl: String?
    public let videoUrl: String?
    public let width: Int?
    public let height: Int?
    public let durationMs: Int?

    public init(
        type: String, url: String?, previewUrl: String?, videoUrl: String?,
        width: Int?, height: Int?, durationMs: Int?
    ) {
        self.type = type
        self.url = url
        self.previewUrl = previewUrl
        self.videoUrl = videoUrl
        self.width = width
        self.height = height
        self.durationMs = durationMs
    }

    public var isVideo: Bool { videoUrl != nil || type == "video" || type == "animated_gif" }

    /// 列表缩略图：优先 previewUrl（:small 变体），回落原图
    public var thumbnailURL: String? { previewUrl ?? url }

    public var aspectRatio: Double? {
        guard let width, let height, width > 0, height > 0 else { return nil }
        return Double(width) / Double(height)
    }
}

public struct XMetrics: Codable, Equatable, Sendable {
    public let replyCount: Int
    public let retweetCount: Int
    public let likeCount: Int

    enum CodingKeys: String, CodingKey {
        case replyCount = "reply_count"
        case retweetCount = "retweet_count"
        case likeCount = "like_count"
    }
}

/// X 长文：bird 只给得到标题 + ~200 字符预览，正文拿不到
public struct XArticle: Codable, Equatable, Sendable {
    public let title: String?
    public let previewText: String?

    public init(title: String?, previewText: String?) {
        self.title = title
        self.previewText = previewText
    }
}

/// 一条 t.co 的展开元数据（schema v13）：X 把正文里的链接全改写成 t.co，原始链接
/// 只活在这份元数据里——X 官方 UI 就是拿它做替换渲染的。替换按 t.co 字符串精确匹配，
/// 永远不用 indices：那是 X 原始 text 的码位偏移，剥掉 RT 前缀 / 长文标题之后就错位了。
public struct XUrlEntity: Codable, Equatable, Sendable {
    public let url: String
    public let expandedURL: String?
    public let displayURL: String?
    public let indices: [Int]?

    enum CodingKeys: String, CodingKey {
        case url
        case expandedURL = "expanded_url"
        case displayURL = "display_url"
        case indices
    }

    public init(url: String, expandedURL: String?, displayURL: String?, indices: [Int]? = nil) {
        self.url = url
        self.expandedURL = expandedURL
        self.displayURL = displayURL
        self.indices = indices
    }
}

/// 被引用的推文（depth=1 内嵌，不单独成条）
public struct XQuote: Codable, Equatable, Sendable {
    public let id: String
    public let authorHandle: String?
    public let authorName: String?
    public let text: String?
    public let createdAt: Date?
    public let media: [XMediaItem]?
    public let metrics: XMetrics?
    /// 元数据出现（2026-08-10）之前归档的行是 nil
    public let urls: [XUrlEntity]?

    enum CodingKeys: String, CodingKey {
        case id
        case authorHandle = "author_handle"
        case authorName = "author_name"
        case text
        case createdAt = "created_at"
        case media, metrics, urls
    }

    public var displayName: String {
        authorName ?? authorHandle.map { "@\($0)" } ?? "Unknown"
    }

    public var tweetURL: URL { xTweetURL(id: id, handle: authorHandle) }
}

/// 反馈判定（计划 Phase 4）。other = 后端先行升级出的新值，前向兼容降级：
/// 看不懂的判定不画徽标，而不是让整页解码失败。
public enum XVerdict: String, Codable, Sendable {
    case positive, neutral, negative, other

    public init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = XVerdict(rawValue: raw) ?? .other
    }

    /// 只有正/负是「表态」；neutral 是默认答案不是结论，不该出现在卡片上
    public var isFinding: Bool { self == .positive || self == .negative }
}

/// 给某条判定投过票的一个已标注推文——徽标背后的证据
public struct XVerdictNeighbor: Codable, Equatable, Sendable {
    public let tweetID: String
    /// cosine 距离：0 = 一样，1 = 无关
    public let distance: Double
    /// 'up' | 'down' | 'save'（未知值原样保留，UI 按未知处理）
    public let label: String
    /// 判定时顺手存下的作者 handle，证据才读得懂
    public let handle: String?

    enum CodingKeys: String, CodingKey {
        case tweetID = "tweet_id"
        case distance, label, handle
    }
}

/// JSON 里的 ["save this", -1.1] 异构数组：一个证据名字 + 它的权重。
public struct XVerdictEvidencePair: Codable, Equatable, Sendable {
    public let name: String
    public let weight: Double

    public init(from decoder: Decoder) throws {
        var container = try decoder.unkeyedContainer()
        name = try container.decode(String.self)
        weight = try container.decode(Double.self)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.unkeyedContainer()
        try container.encode(name)
        try container.encode(weight)
    }
}

/// ensemble（判定 v2 步骤 4）里一个通道的投票：各自阈值下的判定、各自尺度上的分数、
/// 通道特有的证据。通道 B 的证据（近邻）仍在 meta 顶层——已发布客户端解码的就是那个位置。
public struct XVerdictChannel: Codable, Equatable, Sendable {
    public let verdict: XVerdict?
    public let score: Double
    /// 步骤 5b：该通道只打分归档、不投票（为了在不打扰读者的前提下拿到前瞻证据）。
    /// 弃权的通道压根不在 channels 块里——这就是两者的区别。
    public let shadow: Bool?
    /// 通道 C：拍板的那个属性
    public let driver: String?
    public let flags: [XVerdictEvidencePair]?
    /// 通道 D：最强证据 token 及其对数几率
    public let tokens: [XVerdictEvidencePair]?
    /// 通道 A：这个账号，以及你对它的记录——不需要任何度量就能读懂的证据
    public let handle: String?
    public let up: Double?
    public let down: Double?

    /// 渲染用证据：D 给词、C 给属性；B 在这里没有第二份近邻
    public var evidence: [XVerdictEvidencePair] { tokens ?? flags ?? [] }

    /// 通道 A 的证据是一句话，不是权重对，所以单独给一行
    public var record: String? {
        guard let handle else { return nil }
        return "@\(handle) · 你踩过 \(Int(down ?? 0)) 次，赞过 \(Int(up ?? 0)) 次"
    }
}

/// 判定为什么是这个结果。reason 标记两种「没判」：离所有标注都太远、没有可判的文本
/// ——两者说的都是话题通道，顶层字段描述的就是它。
public struct XVerdictMeta: Codable, Equatable, Sendable {
    public let score: Double?
    public let neighbors: [XVerdictNeighbor]?
    public let reason: String?
    /// 多于通道 B 投票时才有（algo 'vote-v1'）：通道字母 -> 该通道的投票，弃权即缺席。
    public let channels: [String: XVerdictChannel]?
    /// 分数可比较的嵌入身份，如 'text-embedding-v4@256'
    public let model: String?
    public let algo: String?

    enum CodingKeys: String, CodingKey {
        case score, neighbors, reason, channels, model, algo
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        score = try container.decodeIfPresent(Double.self, forKey: .score)
        neighbors = try container.decodeIfPresent([XVerdictNeighbor].self, forKey: .neighbors)
        reason = try container.decodeIfPresent(String.self, forKey: .reason)
        // 多通道证据是增强信息：形状看不懂就整块丢掉，判定与顶层证据不陪葬
        channels = try? container.decodeIfPresent([String: XVerdictChannel].self, forKey: .channels)
        model = try container.decodeIfPresent(String.self, forKey: .model)
        algo = try container.decodeIfPresent(String.self, forKey: .algo)
    }
}

/// TimelineItem 的 x payload：一条归档推文在某个 feed 里的那次出现。
public struct XTweet: Codable, Equatable, Sendable {
    /// snowflake id 以字符串承载（int64 超出 JS 安全整数范围，后端统一转字符串）
    public let id: String
    public let authorID: String?
    public let authorHandle: String?
    public let authorName: String?
    public let text: String?
    /// 推文自身发布时间；bird 的时间戳解析失败时为 nil
    public let createdAt: Date?
    /// probe 首次推送时刻——For You 的排序键
    public let firstSeenAt: Date?
    public let media: [XMediaItem]?
    public let metrics: XMetrics?
    public let quote: XQuote?
    /// bird 把转推压平成 'RT @handle:' 前缀，只剩 handle 能救回来
    public let rtOfHandle: String?
    public let replyToID: String?
    public let article: XArticle?
    /// t.co 展开元数据；元数据出现（2026-08-10）之前归档的行是 nil
    public let urls: [XUrlEntity]?
    /// 这次出现属于哪个订阅：'foryou' 或关注人的 handle
    public let feed: String
    /// 'home'（For You）| 'user'（关注人）
    public let feedKind: String
    /// nil = 未判定（还没有标注，或不在 For You）；neutral = 判过但刻意不表态
    public let verdict: XVerdict?
    public let verdictMeta: XVerdictMeta?

    enum CodingKeys: String, CodingKey {
        case id
        case authorID = "author_id"
        case authorHandle = "author_handle"
        case authorName = "author_name"
        case text
        case createdAt = "created_at"
        case firstSeenAt = "first_seen_at"
        case media, metrics, quote
        case rtOfHandle = "rt_of_handle"
        case replyToID = "reply_to_id"
        case article, urls, feed
        case feedKind = "feed_kind"
        case verdict
        case verdictMeta = "verdict_meta"
    }

    public init(
        id: String, authorID: String?, authorHandle: String?, authorName: String?,
        text: String?, createdAt: Date?, firstSeenAt: Date?, media: [XMediaItem]?,
        metrics: XMetrics?, quote: XQuote?, rtOfHandle: String?, replyToID: String?,
        article: XArticle?, urls: [XUrlEntity]? = nil, feed: String, feedKind: String,
        verdict: XVerdict?, verdictMeta: XVerdictMeta?
    ) {
        self.id = id
        self.authorID = authorID
        self.authorHandle = authorHandle
        self.authorName = authorName
        self.text = text
        self.createdAt = createdAt
        self.firstSeenAt = firstSeenAt
        self.media = media
        self.metrics = metrics
        self.quote = quote
        self.rtOfHandle = rtOfHandle
        self.replyToID = replyToID
        self.article = article
        self.urls = urls
        self.feed = feed
        self.feedKind = feedKind
        self.verdict = verdict
        self.verdictMeta = verdictMeta
    }

    public var isForYou: Bool { feedKind == "home" }

    public var displayName: String {
        authorName ?? authorHandle.map { "@\($0)" } ?? "Unknown"
    }

    public var tweetURL: URL { xTweetURL(id: id, handle: authorHandle) }

    public var profileURL: URL? { authorHandle.flatMap { URL(string: "https://x.com/\($0)") } }

    /// 卡片正文；nil = 没有可打印的文字。吞掉三个上游怪癖：转推只以
    /// 'RT @orig: …' 前缀存在（前缀改由标题行承载），长文的 text 就是文章标题
    /// （article 卡已经在显示它了），末尾那个 urls 元数据不认识的 t.co 指的是
    /// 下面正在显示的媒体（X 官方 UI 也隐藏它；urls 为 nil——老数据或本就没有
    /// 外链的推——按空集处理：media 旁的尾部 t.co 反正都是自链接）。
    public var bodyText: String? {
        guard let raw = text else { return nil }
        var body = raw
        if rtOfHandle != nil, let range = body.range(of: #"^RT @[A-Za-z0-9_]{1,15}:\s*"#,
                                                    options: .regularExpression) {
            body.removeSubrange(range)
        }
        if media?.isEmpty == false,
           let range = body.range(of: #"\s*https?://t\.co/[A-Za-z0-9]+\s*$"#,
                                  options: .regularExpression),
           !(urls ?? []).contains(where: { $0.url == body[range].trimmingCharacters(in: .whitespacesAndNewlines) }) {
            body.removeSubrange(range)
        }
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return nil }
        if let title = article?.title,
           title.trimmingCharacters(in: .whitespacesAndNewlines) == trimmed { return nil }
        return body
    }

    /// 卡片上真正画出来的媒体（有缩略图的那些）
    public var displayedMedia: [XMediaItem] {
        (media ?? []).filter { $0.thumbnailURL != nil }
    }

    /// 可进全屏查看器的图片（视频只留缩略图，v1 不做内嵌播放）
    public var photos: [XMediaItem] {
        displayedMedia.filter { !$0.isVideo }
    }

    /// 卡片上第 index 张（含视频）对应查看器里的第几张；nil = 点的是视频，不开查看器。
    /// 两套下标必须由一个地方对齐——视频排在图片前面时，直接拿 index 会错位。
    public func photoIndex(forDisplayed index: Int) -> Int? {
        let shown = displayedMedia
        guard index >= 0, index < shown.count, !shown[index].isVideo else { return nil }
        return shown[..<index].filter { !$0.isVideo }.count
    }
}

// MARK: - RSS payload

/// RSS 的 feed key 就是 feed URL——读者输入什么就用什么作键。
public enum RssFeed {
    /// feed 展示名：抓到标题前回落 URL（去掉 scheme 与尾斜杠）。
    /// 一屏几十个 feed 时，主机名就是区分它们的东西，`https://` 只是噪声。
    public static func label(_ url: String, name: String?) -> String {
        if let name, !name.isEmpty { return name }
        var text = url
        for scheme in ["https://", "http://"] where text.hasPrefix(scheme) {
            text.removeFirst(scheme.count)
        }
        while text.hasSuffix("/") { text.removeLast() }
        return text
    }
}

/// TimelineItem 的 rss payload：一条归档的 feed 条目。
public struct RssEntry: Codable, Equatable, Sendable {
    public let id: Int
    /// feed 自己的去重键（guid / id / link / 哈希），客户端只读不用
    public let guid: String?
    /// feed URL——这个源的订阅键，也是它的 feed 作用域
    public let feedURL: String
    /// feed 标题；首次成功抓取回填前为 nil
    public let feedTitle: String?
    public let title: String?
    public let link: String?
    public let author: String?
    /// 正文开头的纯文本，约 500 字（后端 `text.EXCERPT_CHARS`）。列表载荷带的是它，
    /// 不是全文——feed 正文平均 13.9KB、最长一条 7.1MB，一页 30 条就是 30 篇文章
    /// （2026-08-23）。已经在服务端剥好标签，客户端不必再解析。
    public let contentExcerpt: String?
    /// 正文是否还有后续。iOS 暂时用不上（卡片按行数截、详情 sheet 一律取全文），
    /// 保留是因为它在协议里，web 的 more 按钮就挂在这个字段上。
    public let contentTruncated: Bool?
    /// feed 自带的 HTML 正文（content:encoded，回退 description）。
    /// **只有 `GET /api/rss/entries/{id}` 与旧的收藏快照带它**，列表载荷不带。
    public let content: String?
    /// LLM 摘要（计划 Phase 3）；nil = 短到不需要 / 还没写 / 已放弃
    public let summary: String?
    /// feed 声明的时间，未经钳制——feed 确实会发未来的时间戳
    public let publishedAt: Date?
    public let firstSeenAt: Date
    /// 时间线位置：`published_at` 被钳到首见时刻的结果，等于 envelope 的 datetime。
    /// 规则活在后端 SQL 里，所以结论随 envelope 传出来——收藏快照脱离源表回放时，
    /// 客户端不必（也不该）再实现一遍同一条规则。
    public let sortAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, guid
        case feedURL = "feed_url"
        case feedTitle = "feed_title"
        case title, link, author, content, summary
        case contentExcerpt = "content_excerpt"
        case contentTruncated = "content_truncated"
        case publishedAt = "published_at"
        case firstSeenAt = "first_seen_at"
        case sortAt = "sort_at"
    }

    public init(
        id: Int, guid: String?, feedURL: String, feedTitle: String?, title: String?,
        link: String?, author: String?, contentExcerpt: String? = nil,
        contentTruncated: Bool? = nil, content: String? = nil, summary: String?,
        publishedAt: Date?, firstSeenAt: Date, sortAt: Date?
    ) {
        self.id = id
        self.guid = guid
        self.feedURL = feedURL
        self.feedTitle = feedTitle
        self.title = title
        self.link = link
        self.author = author
        self.contentExcerpt = contentExcerpt
        self.contentTruncated = contentTruncated
        self.content = content
        self.summary = summary
        self.publishedAt = publishedAt
        self.firstSeenAt = firstSeenAt
        self.sortAt = sortAt
    }

    public var feedLabel: String { RssFeed.label(feedURL, name: feedTitle) }

    /// 标题栏文字；一个只发正文不给标题的 feed 用链接顶上
    public var displayTitle: String {
        if let title, !title.isEmpty { return title }
        if let link, !link.isEmpty { return link }
        return "(untitled)"
    }

    /// 原文入口；nil = 这条 feed 把全文发过来了，没有可指的地方
    public var articleURL: URL? {
        guard let link, !link.isEmpty else { return nil }
        return URL(string: link)
    }

    /// 卡片正文：列表载荷里的摘录，与有没有摘要无关——摘要是转述，正文开头才是文章本身。
    ///
    /// 服务端已经剥好标签，所以正常路径上这只是取个字符串：`rssPlainText` 不再每次
    /// 重渲染都跑一遍整篇 HTML（那正是 2026-08-23 排查 RSS 卡顿时找到的那一半）。
    /// 回落到解析 `content` 是给**改版前存下的收藏快照**用的——那些 payload 里只有全文。
    public var contentText: String? {
        if let contentExcerpt, !contentExcerpt.isEmpty { return contentExcerpt }
        return articleText
    }

    /// 全文的纯文本，只有拿到了 `content` 才有（详情 sheet 单独取一次
    /// `GET /api/rss/entries/{id}`）。解析整篇 HTML 的开销在这里，所以调用方要把它
    /// 算一次存进 state，别放在 SwiftUI 的 body 里。
    public var articleText: String? {
        guard let content else { return nil }
        let text = rssPlainText(fromHTML: content)
        return text.isEmpty ? nil : text
    }

    /// 摘要块的内容：去掉首尾空白后非空才算有。摘要**不替代正文**——卡片先画
    /// 正文开头几行作参照，摘要块跟在下面：只看得到机器转述的卡片没法让人
    /// 快速判断文章本身（2026-08-23 改，此前有摘要就不给正文）。
    public var displaySummary: String? {
        guard let summary else { return nil }
        let trimmed = summary.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

/// 原推链接；handle 缺失时 x.com 的 /i/status/<id> 形态照样能打开
/// （判定证据里的近邻只有 id + handle，没有完整推文，所以这个入口是公开的）
public func xTweetURL(id: String, handle: String?) -> URL {
    URL(string: "https://x.com/\(handle ?? "i")/status/\(id)")!
}

// MARK: - Envelope

/// 读者自己对条目打的标签（计划 Phase 3）——Phase 4 判定的训练信号。
/// 表是源通用的，但今天只有 X 的 envelope 暴露它。other 同 XVerdict 的前向兼容理由。
public enum ItemFeedback: String, Codable, Sendable {
    case up, down, other

    public init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = ItemFeedback(rawValue: raw) ?? .other
    }

    /// 点击语义：点已选中的那一侧 = 撤销（nil），点另一侧 = 改正
    public static func next(current: ItemFeedback?, tapped: ItemFeedback) -> ItemFeedback? {
        current == tapped ? nil : tapped
    }
}

/// 「踩」之后的一键理由（schema v9）：这条推文的**哪个属性**让你踩它。
/// 光一个踩标的是整条推文，可真正惹到你的往往只是其中一样——话题、广告腔、
/// 钓互动、AI 味、作者；而一条推文只有一个向量，它们被平均成同一个点，于是「讨厌
/// 这种说话方式」和「讨厌这个话题」在模型眼里没有区别。记下属性，将来多通道模型
/// 才能把标签分派到对的通道去。跳过是免费的：退化成原来的整条标签。
/// engagementFarming（2026-07-27）是 X 官方对「钓互动」的说法，故意不并进 promo：
/// 那个是卖东西，这个是骗互动，而且钓的话术是词汇级的，最便宜的通道就能学会。
/// 标签写「博眼球」而不是直译，读者按之前不用先在心里翻译一遍；值仍是那个超集。
/// other 同 ItemFeedback 的前向兼容理由。
public enum ItemFeedbackReason: String, Codable, Sendable, CaseIterable {
    case topic, promo
    case aiSlop = "ai_slop"
    case engagementFarming = "engagement_farming"
    case author
    case other

    public init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = ItemFeedbackReason(rawValue: raw) ?? .other
    }

    /// 提供给读者的 chip 全集（other 是解码兜底，不进 UI）
    public static let offered: [ItemFeedbackReason] = [.topic, .promo, .aiSlop, .engagementFarming, .author]

    public var label: String {
        switch self {
        case .topic: "不感兴趣"
        case .promo: "广告营销"
        case .aiSlop: "AI Slop"
        case .engagementFarming: "博眼球"
        case .author: "不喜欢作者"
        case .other: "其他"
        }
    }
}

/// 正文里的一条高亮标注（schema v18）。锚点是引文三元组（W3C TextQuoteSelector）：
/// `quote` 是真值，`prefix`/`suffix` 在多处命中时挑最像的那处；`block` 只是 RSS
/// 分块正文的搜索提示，失效就全文搜（重定位见 Annotations.swift）。
/// `id` 是条目内自增的，由服务端在写锁里分配。
public struct ItemAnnotation: Codable, Equatable, Sendable, Identifiable {
    public let id: Int
    public let quote: String
    public let prefix: String?
    public let suffix: String?
    public let block: Int?
    public var comment: String?
    public let createdAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, quote, prefix, suffix, block, comment
        case createdAt = "created_at"
    }

    public init(
        id: Int, quote: String, prefix: String? = nil, suffix: String? = nil,
        block: Int? = nil, comment: String? = nil, createdAt: Date? = nil
    ) {
        self.id = id
        self.quote = quote
        self.prefix = prefix
        self.suffix = suffix
        self.block = block
        self.comment = comment
        self.createdAt = createdAt
    }
}

/// 多信源条目 envelope：telegram / hn / x / rss 恰有其一。
/// key 是全局唯一 item id，也是 read/save API 的出入参。
public struct TimelineItem: Codable, Equatable, Sendable, Identifiable {
    /// "telegram" | "hn" | "x" | "rss"（未知新信源按原样携带，UI 侧忽略）
    public let source: String
    public let key: String
    /// 排序时间：TG=消息时间，HN=首次上榜时间，
    /// X=关注人 feed 用推文时间 / For You 用首次抓到的时间，
    /// RSS=feed 声明时间钳到首见时刻
    public let datetime: Date
    public var isRead: Bool
    public var isSaved: Bool
    /// 尚未长出反馈按钮的信源不带这个字段；nil = 未标注
    public var feedback: ItemFeedback?
    /// 标签的理由 chip；nil = 读者跳过了（合法且无损的标签）。
    /// 与 feedback 平级而不是嵌进去：老版本 App 把 feedback 当字符串解，
    /// 改成对象会让整页解码失败——而 App 是用户单独装的，未必跟服务端一起升。
    public var feedbackReason: ItemFeedbackReason?
    /// 条目级评论（schema v18）；nil = 没写过 / 旧服务器不带这个字段
    public var note: String?
    /// 正文高亮列表（schema v18）；nil = 没有 / 旧服务器不带这个字段
    public var annotations: [ItemAnnotation]?
    public var telegram: DisplayMessage?
    public var hn: HnStory?
    public var x: XTweet?
    public var rss: RssEntry?

    enum CodingKeys: String, CodingKey {
        case source, key, datetime
        case isRead = "is_read"
        case isSaved = "is_saved"
        case feedbackReason = "feedback_reason"
        case feedback, note, annotations, telegram, hn, x, rss
    }

    public var id: String { key }

    public init(
        source: String, key: String, datetime: Date, isRead: Bool, isSaved: Bool,
        feedback: ItemFeedback? = nil, feedbackReason: ItemFeedbackReason? = nil,
        note: String? = nil, annotations: [ItemAnnotation]? = nil,
        telegram: DisplayMessage? = nil, hn: HnStory? = nil, x: XTweet? = nil,
        rss: RssEntry? = nil
    ) {
        self.source = source
        self.key = key
        self.datetime = datetime
        self.isRead = isRead
        self.isSaved = isSaved
        self.feedback = feedback
        self.feedbackReason = feedbackReason
        self.note = note
        self.annotations = annotations
        self.telegram = telegram
        self.hn = hn
        self.x = x
        self.rss = rss
    }
}

public struct TimelinePage: Codable, Equatable, Sendable {
    public let items: [TimelineItem]
    public let nextCursor: String?
    /// 本页最后一个单元的锚点：next_cursor 为 null（本地到底）时仍然存在，
    /// fetch-older 拉到更早历史后用它续接翻页
    public let endCursor: String?
    /// 本页最新单元的锚点，用于轮询 /timeline/new
    public let headCursor: String?

    enum CodingKeys: String, CodingKey {
        case items
        case nextCursor = "next_cursor"
        case endCursor = "end_cursor"
        case headCursor = "head_cursor"
    }

    public init(items: [TimelineItem], nextCursor: String?, endCursor: String?, headCursor: String?) {
        self.items = items
        self.nextCursor = nextCursor
        self.endCursor = endCursor
        self.headCursor = headCursor
    }
}

public struct TimelineNew: Codable, Equatable, Sendable {
    public let count: Int
    public let items: [TimelineItem]

    public init(count: Int, items: [TimelineItem]) {
        self.count = count
        self.items = items
    }
}

// MARK: - Sources（GET /api/sources）

/// 订阅在其信源内的 id：TG 为 int 频道 id，HN 为 feed key 字符串（v1 仅 'front'），
/// X 为 handle / 'foryou'，RSS 为整个 feed URL
public enum SubChannelID: Codable, Equatable, Hashable, Sendable {
    case int(Int)
    case string(String)

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let i = try? container.decode(Int.self) {
            self = .int(i)
        } else {
            self = .string(try container.decode(String.self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .int(let i): try container.encode(i)
        case .string(let s): try container.encode(s)
        }
    }

    public var intValue: Int? {
        if case .int(let i) = self { return i }
        return nil
    }

    public var description: String {
        switch self {
        case .int(let i): String(i)
        case .string(let s): s
        }
    }
}

/// 一条订阅（GET /api/sources 分组内的行）
public struct SourceSub: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let channelID: SubChannelID
    public let name: String?
    public let username: String?
    public let enabled: Bool
    public let unread: Int

    enum CodingKeys: String, CodingKey {
        case channelID = "channel_id"
        case name, username, enabled, unread
    }

    public var id: String { channelID.description }
}

/// GET /api/sources —— 只含有 ≥1 订阅的信源
public struct SourceGroup: Codable, Equatable, Sendable, Identifiable {
    public let source: String
    public let subscriptions: [SourceSub]

    public var id: String { source }
}

// MARK: - Message stats + 转发（GET .../stats、POST .../forward、/api/app/meta）

/// 一条消息上的一个 reaction 汇总桶（实时拉取，不入库）。kind 是判别字段：
/// emoji → unicode 字符；custom → document_id（不解析 glyph，UI 降级通用图标）；
/// other → 前向兼容兜底（未知 kind 字符串也解到这里，不炸解码）。
public struct ReactionCount: Codable, Equatable, Sendable {
    public enum Kind: String, Codable, Sendable {
        case emoji, custom, other

        public init(from decoder: Decoder) throws {
            let raw = try decoder.singleValueContainer().decode(String.self)
            self = Kind(rawValue: raw) ?? .other
        }
    }

    public let kind: Kind
    public let emoji: String?
    public let documentID: Int?
    public let count: Int
    /// 登录账号自己点过的 reaction（高亮）
    public let chosen: Bool

    enum CodingKeys: String, CodingKey {
        case kind, emoji, count, chosen
        case documentID = "document_id"
    }
}

/// GET /api/messages/{cid}/{mid}/stats —— nil = 频道不带该数据
public struct MessageStats: Codable, Equatable, Sendable {
    public let views: Int?
    public let forwards: Int?
    public let reactions: [ReactionCount]

    public var isEmpty: Bool { views == nil && forwards == nil && reactions.isEmpty }
}

/// POST /api/messages/{cid}/{mid}/forward —— mode 指示走了哪条路径：
/// quote = 评论 + t.me 链接的新消息，forward = 原生转发
public struct ForwardResult: Codable, Equatable, Sendable {
    public enum Mode: String, Codable, Sendable {
        case quote, forward
    }

    public let mode: Mode
    /// 目标频道里新落地消息的 t.me 链接
    public let link: String
}

/// GET/PATCH /api/app/meta —— 运行时应用设置
public struct AppMeta: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let backfillDays: Int
    /// 「转发至本频道」目标（@handle / t.me 链接）；nil = 未配置
    public let forwardChannel: String?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case backfillDays = "backfill_days"
        case forwardChannel = "forward_channel"
    }
}
