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

    /// 信源展示名（切换菜单 / 订阅分组标题）
    public static func label(_ source: String) -> String {
        switch source {
        case telegram: "Telegram"
        case hn: "Hacker News"
        default: source
        }
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

// MARK: - Envelope

/// 多信源条目 envelope：telegram / hn 恰有其一。
/// key 是全局唯一 item id，也是 read/save API 的出入参。
public struct TimelineItem: Codable, Equatable, Sendable, Identifiable {
    /// "telegram" | "hn"（未知新信源按原样携带，UI 侧忽略）
    public let source: String
    public let key: String
    /// 排序时间：TG=消息时间，HN=首次上榜时间
    public let datetime: Date
    public var isRead: Bool
    public var isSaved: Bool
    public var telegram: DisplayMessage?
    public var hn: HnStory?

    enum CodingKeys: String, CodingKey {
        case source, key, datetime
        case isRead = "is_read"
        case isSaved = "is_saved"
        case telegram, hn
    }

    public var id: String { key }

    public init(
        source: String, key: String, datetime: Date, isRead: Bool, isSaved: Bool,
        telegram: DisplayMessage? = nil, hn: HnStory? = nil
    ) {
        self.source = source
        self.key = key
        self.datetime = datetime
        self.isRead = isRead
        self.isSaved = isSaved
        self.telegram = telegram
        self.hn = hn
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

/// 订阅在其信源内的 id：TG 为 int 频道 id，HN 为 feed key 字符串（v1 仅 'front'）
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
