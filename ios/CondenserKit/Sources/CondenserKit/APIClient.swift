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
        unreadOnly: Bool = false
    ) async throws -> TimelinePage {
        try await get("/api/timeline", query: [
            "cursor": cursor,
            "limit": limit.map(String.init),
            "channel_id": channelID.map(String.init),
            "date": date,
            "unread_only": unreadOnly ? "true" : nil,
        ])
    }

    public func timelineNew(
        after: String,
        channelID: Int? = nil,
        limit: Int = 100,
        unreadOnly: Bool = false
    ) async throws -> TimelineNew {
        try await get("/api/timeline/new", query: [
            "after": after,
            "channel_id": channelID.map(String.init),
            "limit": String(limit),
            "unread_only": unreadOnly ? "true" : nil,
        ])
    }

    public func subscriptions() async throws -> [Subscription] {
        try await get("/api/subscriptions")
    }

    public func markRead(_ items: [MsgRef]) async throws {
        struct Body: Encodable { let items: [MsgRef] }
        try await send(request(path: "/api/read", method: "POST", body: Body(items: items)))
    }

    public func records() async throws -> [DisplayMessage] {
        try await get("/api/records")
    }

    public func saveRecord(_ ref: MsgRef) async throws {
        try await send(request(path: "/api/records", method: "POST", body: ref))
    }

    public func deleteRecord(_ ref: MsgRef) async throws {
        try await send(request(
            path: "/api/records/\(ref.channelID)/\(ref.messageID)", method: "DELETE"))
    }

    // MARK: - Authed resource URLs（AuthedAsyncImage 加载时仍需带 Bearer header）

    public func mediaURL(channelID: Int, messageID: Int, thumb: Bool = false) -> URL {
        url(path: "/api/media/\(channelID)/\(messageID)",
            query: thumb ? ["thumb": "1"] : [:])
    }

    public func avatarURL(channelID: Int) -> URL {
        url(path: "/api/channels/\(channelID)/avatar", query: [:])
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
        body: (some Encodable)? = nil as MsgRef?
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
