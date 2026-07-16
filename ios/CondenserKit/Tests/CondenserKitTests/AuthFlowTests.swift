import Foundation
import Testing
@testable import CondenserKit

// AuthFlow 行为：服务器地址归一化、/authorize URL 组装、condenser://auth 回调解析
// spec: kb/plans/2026-07-16-ios-reader-app.md（首启与认证）

@Suite("normalizeServerAddress")
struct NormalizeServerAddressTests {
    @Test("裸域名补 https")
    func bareDomain() {
        #expect(AuthFlow.normalizeServerAddress("condenser.reorx.com")?.absoluteString
            == "https://condenser.reorx.com")
    }

    @Test("保留显式 http（本地开发）")
    func explicitHTTP() {
        #expect(AuthFlow.normalizeServerAddress("http://localhost:8792")?.absoluteString
            == "http://localhost:8792")
    }

    @Test("去掉尾部斜杠与首尾空白")
    func trailingSlashAndWhitespace() {
        #expect(AuthFlow.normalizeServerAddress("  https://condenser.reorx.com/  ")?.absoluteString
            == "https://condenser.reorx.com")
    }

    @Test("空串与纯空白返回 nil")
    func emptyInput() {
        #expect(AuthFlow.normalizeServerAddress("") == nil)
        #expect(AuthFlow.normalizeServerAddress("   ") == nil)
    }

    @Test("非 http(s) scheme 返回 nil")
    func badScheme() {
        #expect(AuthFlow.normalizeServerAddress("ftp://example.com") == nil)
        #expect(AuthFlow.normalizeServerAddress("condenser://auth") == nil)
    }
}

@Suite("authorizeURL")
struct AuthorizeURLTests {
    @Test("拼出 /authorize?device_name= 且空格被编码")
    func buildsURL() throws {
        let server = try #require(URL(string: "https://condenser.reorx.com"))
        let url = AuthFlow.authorizeURL(server: server, deviceName: "Reorx's iPhone")
        let comps = try #require(URLComponents(url: url, resolvingAgainstBaseURL: false))
        #expect(comps.scheme == "https")
        #expect(comps.host == "condenser.reorx.com")
        #expect(comps.path == "/authorize")
        #expect(comps.queryItems?.first(where: { $0.name == "device_name" })?.value
            == "Reorx's iPhone")
        #expect(!url.absoluteString.contains(" "))
    }
}

@Suite("parseCallback")
struct ParseCallbackTests {
    @Test("token 回调解析出 token 与设备名")
    func tokenWithName() throws {
        let url = try #require(URL(string: "condenser://auth?token=abc123&name=Reorx's%20iPhone"))
        #expect(AuthFlow.parseCallback(url) == .authorized(token: "abc123", name: "Reorx's iPhone"))
    }

    @Test("无 name 参数也能解析")
    func tokenWithoutName() throws {
        let url = try #require(URL(string: "condenser://auth?token=abc123"))
        #expect(AuthFlow.parseCallback(url) == .authorized(token: "abc123", name: nil))
    }

    @Test("error=denied 解析为 denied")
    func denied() throws {
        let url = try #require(URL(string: "condenser://auth?error=denied"))
        #expect(AuthFlow.parseCallback(url) == .denied)
    }

    @Test("畸形输入返回 nil：错 scheme / 错 host / 缺参数 / 空 token")
    func malformed() throws {
        for s in [
            "https://auth?token=abc123",
            "condenser://other?token=abc123",
            "condenser://auth",
            "condenser://auth?token=",
        ] {
            let url = try #require(URL(string: s))
            #expect(AuthFlow.parseCallback(url) == nil, "should reject: \(s)")
        }
    }
}
