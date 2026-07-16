import UIKit
import CondenserKit

/// 带 Authorization header 的图片加载器（决策：无 query token，统一走 header）。
/// URLCache 手动读写：媒体代理不一定带缓存头，显式 store 保证磁盘缓存生效。
final class ImageLoader {
    static let shared = ImageLoader()

    private let cache: URLCache
    private let session: URLSession

    private init() {
        cache = URLCache(
            memoryCapacity: 64 * 1024 * 1024,
            diskCapacity: 512 * 1024 * 1024,
            diskPath: "condenser-images")
        let config = URLSessionConfiguration.default
        config.urlCache = cache
        config.requestCachePolicy = .returnCacheDataElseLoad
        session = URLSession(configuration: config)
    }

    func load(_ request: URLRequest) async throws -> UIImage {
        if let cached = cache.cachedResponse(for: request),
           let image = UIImage(data: cached.data) {
            return image
        }
        let (data, response) = try await session.data(for: request)
        if let http = response as? HTTPURLResponse, http.statusCode == 401 {
            throw APIError.unauthorized
        }
        guard let image = UIImage(data: data) else {
            throw APIError.invalidResponse
        }
        cache.storeCachedResponse(CachedURLResponse(response: response, data: data), for: request)
        return image
    }
}
