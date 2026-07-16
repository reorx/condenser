import Foundation
import Testing
@testable import CondenserKit

// TokenStore 行为：token 走 SecureStore（生产为 Keychain，测试用内存 fake），
// 服务器地址走 UserDefaults；登出只清 token、保留服务器地址。

final class InMemorySecureStore: SecureStore {
    private var storage: [String: String] = [:]
    func read(key: String) -> String? { storage[key] }
    func write(key: String, value: String) { storage[key] = value }
    func remove(key: String) { storage[key] = nil }
}

@Suite("TokenStore")
struct TokenStoreTests {
    private func makeStore() -> (TokenStore, UserDefaults) {
        let defaults = UserDefaults(suiteName: "TokenStoreTests-\(UUID().uuidString)")!
        return (TokenStore(secureStore: InMemorySecureStore(), defaults: defaults), defaults)
    }

    @Test("token 写入后可读回，clearToken 后为 nil")
    func tokenRoundTrip() {
        let (store, _) = makeStore()
        #expect(store.token == nil)
        store.token = "tok_1"
        #expect(store.token == "tok_1")
        store.clearToken()
        #expect(store.token == nil)
    }

    @Test("serverURL 持久化在 UserDefaults")
    func serverURLPersists() {
        let (store, defaults) = makeStore()
        #expect(store.serverURL == nil)
        store.serverURL = URL(string: "https://condenser.reorx.com")
        #expect(store.serverURL?.absoluteString == "https://condenser.reorx.com")
        // 同一 defaults 重建实例仍能读到（token 在新的内存 fake 中自然丢失）
        let rebuilt = TokenStore(secureStore: InMemorySecureStore(), defaults: defaults)
        #expect(rebuilt.serverURL?.absoluteString == "https://condenser.reorx.com")
    }

    @Test("deviceName 持久化在 UserDefaults，clearToken 不清")
    func deviceNamePersists() {
        let (store, defaults) = makeStore()
        #expect(store.deviceName == nil)
        store.deviceName = "Reorx 的 iPhone"
        #expect(store.deviceName == "Reorx 的 iPhone")
        store.clearToken()
        #expect(store.deviceName == "Reorx 的 iPhone")
        let rebuilt = TokenStore(secureStore: InMemorySecureStore(), defaults: defaults)
        #expect(rebuilt.deviceName == "Reorx 的 iPhone")
    }

    @Test("clearToken 不清 serverURL（保留地址便于重新登录）")
    func clearKeepsServer() {
        let (store, _) = makeStore()
        store.serverURL = URL(string: "https://condenser.reorx.com")
        store.token = "tok_1"
        store.clearToken()
        #expect(store.token == nil)
        #expect(store.serverURL != nil)
    }
}
