import Foundation

public extension TimelineItem {
    /// 条目的原站链接，不经过转发 embed 域名或阅读代理改写。
    /// Telegram 时间线的频道用户名由订阅提供，收藏记录可用自身快照。
    func originalURL(telegramUsername: String? = nil) -> URL? {
        switch source {
        case SourceID.telegram:
            guard let telegram else { return nil }
            let username = telegramUsername ?? telegram.channel?.username
            if let username, !username.isEmpty {
                return URL(string: "https://t.me/\(username)/\(telegram.id)")
            }
            return URL(string: "https://t.me/c/\(telegram.channelID)/\(telegram.id)")
        case SourceID.x:
            return x?.tweetURL
        case SourceID.hn:
            return hn?.primaryURL
        case SourceID.rss:
            return rss?.articleURL
        default:
            return nil
        }
    }
}
