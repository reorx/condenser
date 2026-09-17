import Foundation

/// 外链 → 服务端阅读代理地址（plan 2026-09-07 §5）。
///
/// `https://host:port/path?query#frag` → `<base>/p/host[:port]/path?query[&_pt=ticket]#frag`。
/// 返回 nil 表示"不改写、用原链接"：X 除推文以外的链接（深链进 X app）、t.me、非 http(s)、
/// 以及指向 condenser 自身的链接。X 推文进代理，由服务端的 X handler 渲染成讨论页
/// （plan 2026-09-17）。
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
    if isPurifierExcluded(host: host, path: comps.percentEncodedPath) { return nil }
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

/// 页内和 app 内都保持原链接的那些（与后端 `rewrite_url` 同一条规则）：t.me 整个域名；
/// x.com / twitter.com 除推文以外的路径——主页、Spaces、搜索今天是好用的深链，吸进代理只会
/// 变成错误页。host 含 `www.` / `mobile.` / `m.` 变体。
public func isPurifierExcluded(host: String, path: String) -> Bool {
    var bare = host.lowercased()
    for prefix in ["www.", "mobile.", "m."] where bare.hasPrefix(prefix) {
        bare = String(bare.dropFirst(prefix.count))
        break
    }
    switch bare {
    case "t.me": return true
    case "x.com", "twitter.com": return !isXStatusPath(path)
    default: return false
    }
}

/// `/<handle>/status/<id>`、`/i/status/<id>`、`/i/web/status/<id>`（及旧的 `/statuses/`），
/// 容忍 `/photo/N` `/video/N` `/analytics` 尾巴——与后端 `purifier_x.parse_status_url` 同一个形状。
/// 比 `xAppURL` 的「路径里有 status」更严：这里判错的代价是把人送进一张错误页。
func isXStatusPath(_ path: String) -> Bool {
    let shape = #/(?:i/web|[A-Za-z0-9_]{1,15})/status(?:es)?/[0-9]{1,20}(?:/(?:photo|video)/[0-9]{1,2}|/analytics)?/?/#
    return path.hasPrefix("/") && (try? shape.wholeMatch(in: path.dropFirst())) != nil
}
