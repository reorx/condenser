import Foundation

// 后端 JSON 契约的 Swift 镜像。字段事实来源：frontend/src/lib/types.ts
// （snake_case → CodingKeys；日期 UTC，tz-aware 与 naive 两种形式都能解析）。

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

/// 一个展示单元（相册已合并）。telememo DisplayMessage + condenser 标记。
public struct DisplayMessage: Codable, Equatable, Sendable, Identifiable {
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
    // condenser 附加标记（timeline/records 带上；records 另带 channel）
    public var isRead: Bool?
    public var isSaved: Bool?
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
        case isRead = "is_read"
        case isSaved = "is_saved"
        case channel
    }

    /// 消息 id 只在频道内唯一；跨频道列表的稳定 key
    public var unitKey: String { "\(channelID)/\(id)" }

    public var ref: MsgRef { MsgRef(channelID: channelID, messageID: id) }

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

public struct Subscription: Codable, Equatable, Hashable, Sendable, Identifiable {
    public let channelID: Int
    public let enabled: Bool
    public let backfillDone: Bool
    public let title: String?
    public let username: String?
    public let unread: Int

    enum CodingKeys: String, CodingKey {
        case channelID = "channel_id"
        case enabled
        case backfillDone = "backfill_done"
        case title, username, unread
    }

    public var id: Int { channelID }
}

public struct TimelinePage: Codable, Equatable, Sendable {
    public let items: [DisplayMessage]
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
}

public struct TimelineNew: Codable, Equatable, Sendable {
    public let count: Int
    public let items: [DisplayMessage]
}

/// (channel_id, message_id) 对：已读上报与收藏都用它
public struct MsgRef: Codable, Equatable, Hashable, Sendable {
    public let channelID: Int
    public let messageID: Int

    enum CodingKeys: String, CodingKey {
        case channelID = "channel_id"
        case messageID = "message_id"
    }

    public init(channelID: Int, messageID: Int) {
        self.channelID = channelID
        self.messageID = messageID
    }
}
