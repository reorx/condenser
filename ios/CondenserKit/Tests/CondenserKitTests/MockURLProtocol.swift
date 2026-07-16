import Foundation

/// URLProtocol mock：按最近一次注册的 handler 处理请求。
/// 使用方注意：依赖静态 handler，相关测试套件需 @Suite(.serialized)。
final class MockURLProtocol: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    static func makeSessionConfiguration() -> URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        return config
    }

    /// 便捷注册：固定状态码 + JSON body，返回捕获到的请求（供断言）。
    static func respond(status: Int, json: String) -> CapturedRequest {
        let captured = CapturedRequest()
        handler = { request in
            captured.request = request
            captured.bodyData = request.bodyBytes
            let response = HTTPURLResponse(
                url: request.url!, statusCode: status,
                httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            return (response, Data(json.utf8))
        }
        return captured
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

/// handler 捕获到的请求细节（URLSession 会把 httpBody 转成 stream，这里统一读出）。
final class CapturedRequest: @unchecked Sendable {
    var request: URLRequest?
    var bodyData: Data?

    var url: URL? { request?.url }
    var method: String? { request?.httpMethod }
    var authorization: String? { request?.value(forHTTPHeaderField: "Authorization") }

    var bodyJSON: [String: Any]? {
        bodyData.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
    }
}

private extension URLRequest {
    /// httpBody 在 URLProtocol 层通常以 stream 形式出现
    var bodyBytes: Data? {
        if let body = httpBody { return body }
        guard let stream = httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var data = Data()
        let bufferSize = 4096
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: bufferSize)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let read = stream.read(buffer, maxLength: bufferSize)
            if read <= 0 { break }
            data.append(buffer, count: read)
        }
        return data
    }
}
