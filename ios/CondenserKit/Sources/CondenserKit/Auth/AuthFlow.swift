import Foundation

/// web 跳转授权流程的纯逻辑部分：组装 /authorize URL、解析 condenser://auth 回调。
/// ASWebAuthenticationSession 的调用在 app target（系统胶水层）。
public enum AuthFlow {
    /// 回调 URL 的自定义 scheme（condenser://auth?...）
    public static let callbackScheme = "condenser"

    public enum Callback: Equatable {
        case authorized(token: String, name: String?)
        case denied
    }

    /// 用户输入的服务器地址 → 规范化 URL。
    /// 裸域名补 https、去首尾空白与尾部斜杠；非 http(s) 或无 host 返回 nil。
    public static func normalizeServerAddress(_ raw: String) -> URL? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.contains("://") {
            text = "https://" + text
        }
        guard var comps = URLComponents(string: text),
              let scheme = comps.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              let host = comps.host, !host.isEmpty
        else { return nil }
        while comps.path.hasSuffix("/") {
            comps.path.removeLast()
        }
        return comps.url
    }

    /// `<server>/authorize?device_name=<name>`（spec: device-token 授权流程 §2）
    public static func authorizeURL(server: URL, deviceName: String) -> URL {
        var comps = URLComponents(url: server, resolvingAgainstBaseURL: false)!
        comps.path += "/authorize"
        comps.queryItems = [URLQueryItem(name: "device_name", value: deviceName)]
        return comps.url!
    }

    /// 解析 `condenser://auth?token=...&name=...` 或 `condenser://auth?error=denied`。
    /// 畸形输入（scheme/host 不符、缺 token、空 token）返回 nil。
    public static func parseCallback(_ url: URL) -> Callback? {
        guard url.scheme == callbackScheme, url.host == "auth",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems
        else { return nil }
        func value(_ name: String) -> String? {
            items.first(where: { $0.name == name })?.value
        }
        if value("error") == "denied" {
            return .denied
        }
        guard let token = value("token"), !token.isEmpty else { return nil }
        return .authorized(token: token, name: value("name"))
    }
}
