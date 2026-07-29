import Foundation
import Testing
@testable import CondenserKit

// X 网页链接 → X app 深链的映射（「在 X 上打开」按钮的纯逻辑部分）。
// 判断标准只有一个：能确定这条链接在 X app 里对应哪个界面才给深链，
// 拿不准就返回 nil 让调用方回落网页——把人送进 app 的错误界面比留在 Safari 更糟。

@Suite("X app 深链")
struct XAppLinkTests {
    @Test("推文链接 → twitter://status")
    func statusLink() throws {
        let url = try #require(URL(string: "https://x.com/jonnygravity/status/2080466972039622848"))
        #expect(xAppURL(for: url)?.absoluteString == "twitter://status?id=2080466972039622848")
    }

    @Test("推文链接的各种形态：twitter.com / www. / /i/ 占位 / 查询串 / 尾巴")
    func statusVariants() throws {
        let cases = [
            "https://twitter.com/jonnygravity/status/42",
            "https://www.x.com/jonnygravity/status/42",
            "https://mobile.twitter.com/jonnygravity/status/42",
            // handle 缺失时 xTweetURL 生成的占位形态
            "https://x.com/i/status/42",
            "https://x.com/i/web/status/42",
            "https://x.com/jonnygravity/status/42?s=20&t=abc",
            "https://x.com/jonnygravity/status/42/photo/1",
        ]
        for raw in cases {
            let url = try #require(URL(string: raw))
            #expect(xAppURL(for: url)?.absoluteString == "twitter://status?id=42", "\(raw)")
        }
    }

    @Test("xTweetURL 生成的链接一定映射得到深链")
    func roundTrip() {
        #expect(xAppURL(for: xTweetURL(id: "42", handle: "jonnygravity"))?.absoluteString
            == "twitter://status?id=42")
        #expect(xAppURL(for: xTweetURL(id: "42", handle: nil))?.absoluteString
            == "twitter://status?id=42")
    }

    @Test("主页链接 → twitter://user")
    func profileLink() throws {
        let url = try #require(URL(string: "https://x.com/jonnygravity"))
        #expect(xAppURL(for: url)?.absoluteString == "twitter://user?screen_name=jonnygravity")
        let trailing = try #require(URL(string: "https://twitter.com/jonnygravity/"))
        #expect(xAppURL(for: trailing)?.absoluteString == "twitter://user?screen_name=jonnygravity")
    }

    @Test("不是 X 的域名一律不深链（含把 x.com 塞进路径的仿冒形态）")
    func foreignHosts() throws {
        for raw in ["https://example.com/jonnygravity/status/42",
                    "https://example.com/x.com/status/42",
                    "https://fixupx.com/jonnygravity/status/42",
                    "https://notx.com/foo"] {
            let url = try #require(URL(string: raw))
            #expect(xAppURL(for: url) == nil, "\(raw)")
        }
    }

    @Test("认不出对应界面的 X 链接回落网页")
    func unmappedPaths() throws {
        for raw in ["https://x.com",
                    "https://x.com/",
                    "https://x.com/search?q=swift",
                    "https://x.com/i/lists/123",
                    "https://x.com/home",
                    "https://x.com/messages",
                    // 一级路径当 handle 用之前要过 X 的用户名规则
                    "https://x.com/way_too_long_a_handle",
                    "https://x.com/bad-handle",
                    // status 后面不是数字 id
                    "https://x.com/jonnygravity/status/abc"] {
            let url = try #require(URL(string: raw))
            #expect(xAppURL(for: url) == nil, "\(raw)")
        }
    }
}
