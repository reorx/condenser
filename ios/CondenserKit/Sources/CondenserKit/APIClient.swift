import Foundation

public enum APIError: Error, Equatable {
    /// 401：token 失效/被吊销，顶层应清 token 回登录页
    case unauthorized
    case http(status: Int, detail: String?)
    case invalidResponse
}

/// condenser JSON API 客户端：URLSession + Codable，Bearer token 认证。
/// 底层不处理错误（直接 throw APIError / URLError），由 Store/View 顶层收敛。
public final class APIClient: @unchecked Sendable {
    public let baseURL: URL
    private let token: String
    private let session: URLSession
    private let decoder = JSONDecoder.condenserAPI
    private let encoder = JSONEncoder.condenserAPI

    public init(
        baseURL: URL,
        token: String,
        configuration: URLSessionConfiguration = .default
    ) {
        self.baseURL = baseURL
        self.token = token
        session = URLSession(configuration: configuration)
    }

    // MARK: - Endpoints

    public func timeline(
        cursor: String? = nil,
        limit: Int? = nil,
        channelID: Int? = nil,
        date: String? = nil,
        unreadOnly: Bool = false,
        source: String? = nil,
        feed: String? = nil
    ) async throws -> TimelinePage {
        try await get("/api/timeline", query: [
            "cursor": cursor,
            "limit": limit.map(String.init),
            "channel_id": channelID.map(String.init),
            "date": date,
            "unread_only": unreadOnly ? "true" : nil,
            "source": source,
            "feed": feed,
        ])
    }

    public func timelineNew(
        after: String,
        channelID: Int? = nil,
        limit: Int = 100,
        unreadOnly: Bool = false,
        source: String? = nil,
        feed: String? = nil
    ) async throws -> TimelineNew {
        try await get("/api/timeline/new", query: [
            "after": after,
            "channel_id": channelID.map(String.init),
            "limit": String(limit),
            "unread_only": unreadOnly ? "true" : nil,
            "source": source,
            "feed": feed,
        ])
    }

    public func sources() async throws -> [SourceGroup] {
        try await get("/api/sources")
    }

    public func markRead(keys: [String]) async throws {
        struct Body: Encodable { let keys: [String] }
        try await send(request(path: "/api/read", method: "POST", body: Body(keys: keys)))
    }

    public func records() async throws -> [TimelineItem] {
        try await get("/api/records")
    }

    public func saveRecord(key: String) async throws {
        struct Body: Encodable { let key: String }
        try await send(request(path: "/api/records", method: "POST", body: Body(key: key)))
    }

    public func deleteRecord(key: String) async throws {
        try await send(request(path: "/api/records/\(key)", method: "DELETE"))
    }

    /// 一次请求说清整条标签：不带 reason 就是「没有理由」，会清掉服务端已存的那个，
    /// 所以把「踩+AI Slop」改成「赞」时旧理由不会跟着跑过去。
    public func setFeedback(
        key: String, verdict: ItemFeedback, reason: ItemFeedbackReason? = nil
    ) async throws {
        struct Body: Encodable {
            let key: String
            let verdict: String
            let reason: String?
        }
        try await send(request(
            path: "/api/feedback", method: "POST",
            body: Body(key: key, verdict: verdict.rawValue, reason: reason?.rawValue)))
    }

    public func clearFeedback(key: String) async throws {
        try await send(request(path: "/api/feedback/\(key)", method: "DELETE"))
    }

    public func fetchOlder(channelID: Int, count: Int = 200) async throws -> Int {
        struct Reply: Decodable { let fetched: Int }
        let data = try await send(request(
            path: "/api/tg/fetch-older/\(channelID)", method: "POST",
            query: ["count": String(count)]))
        return try decoder.decode(Reply.self, from: data).fetched
    }

    public func messageStats(channelID: Int, messageID: Int) async throws -> MessageStats {
        try await get("/api/messages/\(channelID)/\(messageID)/stats")
    }

    /// 空/纯空白评论 → body 不带 comment（后端走原生 forward）；有评论 → trim 后随 body
    public func forwardMessage(
        channelID: Int, messageID: Int, comment: String?
    ) async throws -> ForwardResult {
        struct Body: Encodable { let comment: String? }
        let trimmed = comment?.trimmingCharacters(in: .whitespacesAndNewlines)
        let data = try await send(request(
            path: "/api/messages/\(channelID)/\(messageID)/forward", method: "POST",
            body: Body(comment: (trimmed?.isEmpty ?? true) ? nil : trimmed)))
        return try decoder.decode(ForwardResult.self, from: data)
    }

    public func appMeta() async throws -> AppMeta {
        try await get("/api/app/meta")
    }

    /// 传 "" 清除（后端读回 null）
    public func setForwardChannel(_ value: String) async throws -> AppMeta {
        struct Body: Encodable {
            let forwardChannel: String
            enum CodingKeys: String, CodingKey { case forwardChannel = "forward_channel" }
        }
        let data = try await send(request(
            path: "/api/app/meta", method: "PATCH", body: Body(forwardChannel: value)))
        return try decoder.decode(AppMeta.self, from: data)
    }

    // MARK: - Authed resource URLs（AuthedAsyncImage 加载时仍需带 Bearer header）

    public func mediaURL(channelID: Int, messageID: Int, thumb: Bool = false) -> URL {
        url(path: "/api/media/\(channelID)/\(messageID)",
            query: thumb ? ["thumb": "1"] : [:])
    }

    public func avatarURL(channelID: Int) -> URL {
        url(path: "/api/channels/\(channelID)/avatar", query: [:])
    }

    /// 推文作者头像：后端 unavatar 代理（bird 不带头像 URL）；404 = 画字母头像
    public func xAvatarURL(handle: String) -> URL {
        url(path: "/api/x/avatar/\(handle)", query: [:])
    }

    /// 任意外站图片经服务端代理：读一条推文不会让 X 看到读者的 IP
    public func proxiedImageURL(_ raw: String) -> URL {
        url(path: "/api/preview/image", query: ["url": raw])
    }

    /// 图片等非 JSON 资源的认证请求（供 ImageLoader 用）
    public func authedRequest(_ url: URL) -> URLRequest {
        var req = URLRequest(url: url)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return req
    }

    // MARK: - Plumbing

    private func url(path: String, query: [String: String?]) -> URL {
        var comps = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        comps.path += path
        let items = query.compactMap { k, v in v.map { URLQueryItem(name: k, value: $0) } }
        if !items.isEmpty {
            comps.queryItems = items.sorted { $0.name < $1.name }
        }
        return comps.url!
    }

    private func request(
        path: String,
        method: String = "GET",
        query: [String: String?] = [:],
        body: (some Encodable)? = nil as String?
    ) -> URLRequest {
        var req = authedRequest(url(path: path, query: query))
        req.httpMethod = method
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? encoder.encode(body)
        }
        return req
    }

    private func get<T: Decodable>(_ path: String, query: [String: String?] = [:]) async throws -> T {
        try await decode(send(request(path: path, query: query)))
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        try decoder.decode(T.self, from: data)
    }

    @discardableResult
    private func send(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            if http.statusCode == 401 {
                throw APIError.unauthorized
            }
            struct Detail: Decodable { let detail: String? }
            let detail = (try? decoder.decode(Detail.self, from: data))?.detail
            throw APIError.http(status: http.statusCode, detail: detail)
        }
        return data
    }
}
