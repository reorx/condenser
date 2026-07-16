import Foundation
import Observation
import CondenserKit

/// 全局认证会话：持有 server + token，登录/登出/401 时驱动根视图切换。
/// spec: kb/plans/2026-07-16-ios-reader-app.md（首启与认证）
@MainActor
@Observable
final class AuthSession {
    private let store: TokenStore

    private(set) var serverURL: URL?
    private(set) var token: String?
    /// 登录页展示的一次性提示（如会话失效），进入登录流程时清除
    var notice: String?

    var isAuthenticated: Bool { serverURL != nil && token != nil }

    init(store: TokenStore = TokenStore()) {
        self.store = store
        serverURL = store.serverURL
        token = store.token
        #if DEBUG
        // 开发直连：simctl launch 传 SIMCTL_CHILD_CONDENSER_DEBUG_SERVER/TOKEN，
        // 仅内存态、不落 Keychain，跳过交互式授权以便模拟器验证
        let env = ProcessInfo.processInfo.environment
        if let debugServer = env["CONDENSER_DEBUG_SERVER"].flatMap(URL.init(string:)),
           let debugToken = env["CONDENSER_DEBUG_TOKEN"] {
            serverURL = debugServer
            token = debugToken
        }
        #endif
    }

    func completeLogin(server: URL, token: String) {
        store.serverURL = server
        store.token = token
        serverURL = server
        self.token = token
        notice = nil
    }

    /// 登出：清 Keychain token，保留服务器地址便于重新登录（服务端吊销走 web 设置页）
    func signOut() {
        store.clearToken()
        token = nil
    }

    /// 任意 API 请求 401 时调用：清 token 回登录页并提示（phase 3 由 APIClient 接线）
    func handleUnauthorized() {
        signOut()
        notice = "会话已失效，请重新登录"
    }
}
