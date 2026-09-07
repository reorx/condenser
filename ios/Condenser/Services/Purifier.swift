import Foundation
import CondenserKit

/// Purifier 阅读代理开关 + 票据预热（plan 2026-09-07 §5.1）。
///
/// 单例而不是给 `openExternalURL` 加参数：加参数就是让 8 个调用现场各自长逻辑。
/// 开关直读 `UserDefaults`（`@AppStorage` 只能用于 View，设置页用同一个 key 绑定）。
///
/// 票据是"锦上添花"：`rewrittenURL(for:)` 永远同步、永远用当下缓存的票（可能为 nil）；
/// cookie 已种下后 `_pt` 缺失不影响。三个预热时机：登录成功（`configure`）、开关打开、
/// 回到前台；每次改写后再踢一次 `shouldRefresh` 检查。失败静默——弱网下换票失败，
/// 链接照样打开，最坏是 Safari 里看到一张 401 小页。
@MainActor
final class Purifier {
    static let shared = Purifier()
    static let storageKey = "condenser.purifier"

    private var api: APIClient?
    private var baseURL: URL?
    private var tickets = PurifierTickets()
    private var refreshing = false

    var isEnabled: Bool { UserDefaults.standard.bool(forKey: Self.storageKey) }

    func configure(api: APIClient, baseURL: URL) {
        self.api = api
        self.baseURL = baseURL
        tickets.clear()
        prefetchIfNeeded()
    }

    /// 登出：票据与服务器一起作废；开关留着（是设备偏好，不是会话状态）
    func reset() {
        api = nil
        baseURL = nil
        tickets.clear()
    }

    /// 开关开着且链接该改写 → 代理地址；否则 nil，调用方用原 URL
    func rewrittenURL(for url: URL) -> URL? {
        guard isEnabled, let baseURL else { return nil }
        let rewritten = purifiedURL(url, base: baseURL, ticket: tickets.cached())
        if rewritten != nil { prefetchIfNeeded() }
        return rewritten
    }

    /// 开关开着且票快过期/没票时后台换一张；并发调用只跑一次
    func prefetchIfNeeded() {
        guard isEnabled, let api, tickets.shouldRefresh(), !refreshing else { return }
        refreshing = true
        Task {
            defer { refreshing = false }
            guard let fresh = try? await api.purifierTicket() else { return }
            tickets.store(ticket: fresh.ticket, ttl: TimeInterval(fresh.ttl))
        }
    }
}
