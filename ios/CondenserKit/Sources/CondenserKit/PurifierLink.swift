import Foundation

/// 外链 → 服务端阅读代理地址（plan 2026-09-07 §5）。
///
/// `https://host:port/path?query#frag` → `<base>/p/host[:port]/path?query[&_pt=ticket]#frag`。
/// 返回 nil 表示"不改写、用原链接"：X（深链进 X app）、t.me、非 http(s)、以及指向
/// condenser 自身的链接。
///
/// 路径与 query 走 `percentEncodedPath` / `percentEncodedQuery` 原样透传：`.path` 是
/// 解码过的（`%2F` 会变成分隔符），`URLQueryItem` 重建会二次编码原站参数。票据是
/// 字符串拼接，itsdangerous 的签名只含 URL 安全字符。
public func purifiedURL(_ url: URL, base: URL, ticket: String?) -> URL? {
    guard let comps = URLComponents(url: url, resolvingAgainstBaseURL: false),
          let scheme = comps.scheme?.lowercased(), scheme == "http" || scheme == "https",
          let rawHost = comps.host, !rawHost.isEmpty
    else { return nil }
    let host = rawHost.lowercased()
    if isPurifierExcludedHost(host) { return nil }
    if host == base.host?.lowercased() { return nil }

    var hostSegment = host
    if let port = comps.port, port != (scheme == "https" ? 443 : 80) {
        hostSegment += ":\(port)"
    }
    var query = comps.percentEncodedQuery ?? ""
    if let ticket, !ticket.isEmpty {
        query += (query.isEmpty ? "" : "&") + "_pt=" + ticket
    }

    guard var out = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
    let basePath = out.percentEncodedPath.hasSuffix("/")
        ? String(out.percentEncodedPath.dropLast()) : out.percentEncodedPath
    out.percentEncodedPath = basePath + "/p/" + hostSegment + comps.percentEncodedPath
    out.percentEncodedQuery = query.isEmpty ? nil : query
    out.percentEncodedFragment = comps.percentEncodedFragment
    return out.url
}

/// 页内和 app 内都保持原链接的三个域名（与后端 `EXCLUDED_REWRITE_HOSTS` 一致），
/// 含 `www.` / `mobile.` / `m.` 变体。
public func isPurifierExcludedHost(_ host: String) -> Bool {
    var bare = host.lowercased()
    for prefix in ["www.", "mobile.", "m."] where bare.hasPrefix(prefix) {
        bare = String(bare.dropFirst(prefix.count))
        break
    }
    return bare == "x.com" || bare == "twitter.com" || bare == "t.me"
}
