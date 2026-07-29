import Foundation

/// X 网页链接 → X app 深链。读者点「在 X 上打开」想要的是能点赞、能回复、
/// 已经登录好的原生界面；SFSafariViewController 里的 x.com 是个逼你登录的壳。
///
/// 用的是 X 一直注册着的老 scheme `twitter://`（app 早改名了，scheme 没改）。
/// 认不出对应界面就返回 nil，由调用方回落网页——把人送进 app 的错误界面比留在
/// Safari 更糟，所以这里只认两种确定的形态：单条推文与作者主页。

/// X 的用户名规则：字母数字下划线，1–15 位
private func isXHandle(_ handle: String) -> Bool {
    guard (1...15).contains(handle.count) else { return false }
    return handle.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "_") }
}

/// 一级路径里不是用户名的那些（`/i/…` 是 X 自己的内部前缀，其余是功能页）
private let xReservedPaths: Set<String> = [
    "i", "home", "explore", "search", "notifications", "messages", "settings",
    "compose", "intent", "share", "hashtag", "login", "logout", "signup", "about",
]

func xStatusAppURL(id: String) -> URL? {
    guard !id.isEmpty, id.allSatisfy({ $0.isASCII && $0.isNumber }) else { return nil }
    return URL(string: "twitter://status?id=\(id)")
}

func xProfileAppURL(handle: String) -> URL? {
    guard isXHandle(handle), !xReservedPaths.contains(handle.lowercased()) else { return nil }
    return URL(string: "twitter://user?screen_name=\(handle)")
}

/// 这条网页链接在 X app 里对应哪个界面；nil = 不知道，走网页
public func xAppURL(for url: URL) -> URL? {
    guard var host = url.host?.lowercased() else { return nil }
    for prefix in ["www.", "mobile.", "m."] where host.hasPrefix(prefix) {
        host = String(host.dropFirst(prefix.count))
    }
    guard host == "x.com" || host == "twitter.com" else { return nil }

    let segments = url.path.split(separator: "/").map(String.init)
    // /<handle>/status/<id>，也可能是 /i/web/status/<id>；后面还能挂 /photo/1 之类的尾巴
    if let marker = segments.firstIndex(of: "status"), marker + 1 < segments.count {
        return xStatusAppURL(id: segments[marker + 1])
    }
    if segments.count == 1 {
        return xProfileAppURL(handle: segments[0])
    }
    return nil
}
