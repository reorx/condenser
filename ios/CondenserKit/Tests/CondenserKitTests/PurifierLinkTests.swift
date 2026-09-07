import Foundation
import Testing
@testable import CondenserKit

// 外链 → 服务端阅读代理 `/p/<host>/<path>?<query>` 的改写（plan 2026-09-07 §5.2）。
// 只有一个函数、一个判断：能改写就给改写后的 URL，不该改写（X / t.me / 非 http(s) /
// 自身域名）就返回 nil，调用方用原 URL。路径与 query 按原始字节透传——用
// percentEncodedPath / percentEncodedQuery，绝不经过 .path / URLQueryItem 二次编码。

@Suite("Purifier 链接改写")
struct PurifierLinkTests {
    private let base = URL(string: "https://condenser.example")!

    private func rewrite(_ raw: String, ticket: String? = nil, base: URL? = nil) -> String? {
        purifiedURL(URL(string: raw)!, base: base ?? self.base, ticket: ticket)?.absoluteString
    }

    @Test("基础形态：host 进路径段，path 原样接在后面")
    func basic() {
        #expect(rewrite("https://news.ycombinator.com/item") == "https://condenser.example/p/news.ycombinator.com/item")
    }

    @Test("原站 query 原样保留")
    func keepsQuery() {
        #expect(rewrite("https://news.ycombinator.com/item?id=49537553&p=2")
            == "https://condenser.example/p/news.ycombinator.com/item?id=49537553&p=2")
    }

    @Test("票据与既有 query 并列，追加在最后")
    func ticketAppendedToQuery() {
        #expect(rewrite("https://a.example/x?id=1", ticket: "T.sig")
            == "https://condenser.example/p/a.example/x?id=1&_pt=T.sig")
    }

    @Test("没有原站 query 时票据单独成 query")
    func ticketAlone() {
        #expect(rewrite("https://a.example/x", ticket: "T.sig") == "https://condenser.example/p/a.example/x?_pt=T.sig")
    }

    @Test("票据为 nil 时没有 _pt")
    func noTicketNoParam() {
        #expect(rewrite("https://a.example/x", ticket: nil) == "https://condenser.example/p/a.example/x")
    }

    @Test("非默认端口按 host:port 拼进路径段")
    func portInHostSegment() {
        #expect(rewrite("https://a.example:8080/x") == "https://condenser.example/p/a.example:8080/x")
        #expect(rewrite("https://a.example:443/x") == "https://condenser.example/p/a.example/x")
        #expect(rewrite("http://a.example:80/x") == "https://condenser.example/p/a.example/x")
    }

    @Test("已编码的路径原样透传（%2F 不变成分隔符，%20 不二次编码）")
    func encodedPathVerbatim() {
        #expect(rewrite("https://a.example/a%2Fb/c%20d?q=x%2Fy")
            == "https://condenser.example/p/a.example/a%2Fb/c%20d?q=x%2Fy")
    }

    @Test("空 path 不补斜杠")
    func emptyPath() {
        #expect(rewrite("https://a.example") == "https://condenser.example/p/a.example")
        #expect(rewrite("https://a.example?x=1", ticket: "T") == "https://condenser.example/p/a.example?x=1&_pt=T")
    }

    @Test("fragment 透传到最末尾（票据在它前面）")
    func fragmentPassesThrough() {
        #expect(rewrite("https://a.example/x#sec-2", ticket: "T") == "https://condenser.example/p/a.example/x?_pt=T#sec-2")
        #expect(rewrite("https://a.example/x?y=1#sec") == "https://condenser.example/p/a.example/x?y=1#sec")
    }

    @Test("X 的域名不改写：x.com / twitter.com 及 www. / mobile. / m. 变体")
    func excludesX() {
        for raw in [
            "https://x.com/a/status/1", "https://twitter.com/a", "https://www.x.com/a",
            "https://mobile.twitter.com/a", "https://m.x.com/a",
        ] {
            #expect(rewrite(raw) == nil, Comment(rawValue: raw))
        }
    }

    @Test("t.me 不改写（进 Telegram）")
    func excludesTelegram() {
        #expect(rewrite("https://t.me/channel/12") == nil)
    }

    @Test("非 http(s) scheme 不改写：mailto / tel / 自定义 scheme")
    func excludesNonHTTP() {
        #expect(rewrite("mailto:a@b.c") == nil)
        #expect(rewrite("tel:+123") == nil)
        #expect(rewrite("condenser://open") == nil)
        #expect(rewrite("twitter://status?id=1") == nil)
    }

    @Test("指向 condenser 自身的链接不改写")
    func excludesOwnHost() {
        #expect(rewrite("https://condenser.example/p/a.example/x") == nil)
        #expect(rewrite("https://CONDENSER.example/api/x") == nil)
    }

    @Test("http 与 https 映射到同一个代理地址（scheme 由服务端决定）")
    func schemeAgnostic() {
        #expect(rewrite("http://a.example/x") == rewrite("https://a.example/x"))
    }

    @Test("host 大小写归一为小写（同一站点只有一份缓存）")
    func lowercasesHost() {
        #expect(rewrite("https://News.YCombinator.COM/item?id=1") == "https://condenser.example/p/news.ycombinator.com/item?id=1")
    }

    @Test("base 带端口（本地开发 http://localhost:8792）")
    func baseWithPort() {
        let dev = URL(string: "http://localhost:8792")!
        #expect(rewrite("https://a.example/x?y=1", ticket: "T", base: dev) == "http://localhost:8792/p/a.example/x?y=1&_pt=T")
    }

    @Test("base 带尾斜杠时不会出现双斜杠")
    func baseTrailingSlash() {
        let slashed = URL(string: "https://condenser.example/")!
        #expect(rewrite("https://a.example/x", base: slashed) == "https://condenser.example/p/a.example/x")
    }

    @Test("isPurifierExcludedHost：只认这三个域名及其变体")
    func excludedHostPredicate() {
        #expect(isPurifierExcludedHost("x.com"))
        #expect(isPurifierExcludedHost("www.twitter.com"))
        #expect(isPurifierExcludedHost("t.me"))
        #expect(!isPurifierExcludedHost("news.ycombinator.com"))
        #expect(!isPurifierExcludedHost("fixupx.com"))
        #expect(!isPurifierExcludedHost("xx.com"))
    }

    @Test("HN 用户页也走代理（无害，plan §0.4）")
    func hnUserPageIsRewritten() {
        #expect(rewrite("https://news.ycombinator.com/user?id=pg") == "https://condenser.example/p/news.ycombinator.com/user?id=pg")
    }
}
