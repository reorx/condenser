import Foundation
import Security

/// token 的安全存储抽象：生产为 Keychain，测试注入内存 fake。
public protocol SecureStore {
    func read(key: String) -> String?
    func write(key: String, value: String)
    func remove(key: String)
}

/// kSecClassGenericPassword 实现；service 固定、key 作 account。
public final class KeychainStore: SecureStore {
    private let service: String

    public init(service: String) {
        self.service = service
    }

    private func query(key: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
    }

    public func read(key: String) -> String? {
        var q = query(key: key)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data
        else { return nil }
        return String(data: data, encoding: .utf8)
    }

    public func write(key: String, value: String) {
        remove(key: key)
        var q = query(key: key)
        q[kSecValueData as String] = Data(value.utf8)
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(q as CFDictionary, nil)
    }

    public func remove(key: String) {
        SecItemDelete(query(key: key) as CFDictionary)
    }
}

/// device token（SecureStore/Keychain）+ 服务器地址（UserDefaults）的持久化门面。
/// 登出只清 token、保留服务器地址（便于重新登录预填）。
public final class TokenStore {
    private enum Keys {
        static let token = "device-token"
        static let serverURL = "condenser.server-url"
    }

    private let secureStore: SecureStore
    private let defaults: UserDefaults

    public init(
        secureStore: SecureStore = KeychainStore(service: "com.reorx.condenser"),
        defaults: UserDefaults = .standard
    ) {
        self.secureStore = secureStore
        self.defaults = defaults
    }

    public var token: String? {
        get { secureStore.read(key: Keys.token) }
        set {
            if let newValue {
                secureStore.write(key: Keys.token, value: newValue)
            } else {
                secureStore.remove(key: Keys.token)
            }
        }
    }

    public var serverURL: URL? {
        get { defaults.string(forKey: Keys.serverURL).flatMap(URL.init(string:)) }
        set { defaults.set(newValue?.absoluteString, forKey: Keys.serverURL) }
    }

    public func clearToken() {
        token = nil
    }
}
