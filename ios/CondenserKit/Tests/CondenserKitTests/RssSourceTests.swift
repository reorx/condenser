import Foundation
import Testing
@testable import CondenserKit

// RSS 信息源（计划 Phase 4）的 Kit 行为：envelope 解码（fixture 为真实后端 JSON，
// tmp/make_ios_rss_fixtures.py 从 dev DB 生成）、卡片要用的展示逻辑，以及这个源
// 独有的风险面——feed 自带的任意 HTML 转纯文本。
// 契约事实来源 frontend/src/lib/types.ts + condenser/items.py:rss_payload。

private func loadRssFixture(_ name: String) throws -> Data {
    let url = try #require(Bundle.module.url(forResource: "Fixtures/\(name)", withExtension: "json"))
    return try Data(contentsOf: url)
}

private func rssShapes() throws -> [String: TimelineItem] {
    try JSONDecoder.condenserAPI.decode([String: TimelineItem].self, from: loadRssFixture("rss_shapes"))
}

@Suite("RSS 模型解码")
struct RssModelsDecodingTests {
    private let decoder = JSONDecoder.condenserAPI

    @Test("timeline_page_rss.json：整页 RSS envelope，key 前缀 rss:，payload 与 source 对应")
    func page() throws {
        let page = try decoder.decode(TimelinePage.self, from: loadRssFixture("timeline_page_rss"))
        #expect(!page.items.isEmpty)
        for item in page.items {
            #expect(item.source == SourceID.rss)
            #expect(item.key.hasPrefix("rss:"))
            #expect(item.rss != nil)
            #expect(item.telegram == nil && item.hn == nil && item.x == nil)
        }
    }

    @Test("item key 就是 rss:{条目 id}")
    func keyMatchesID() throws {
        let page = try decoder.decode(TimelinePage.self, from: loadRssFixture("timeline_page_rss"))
        for item in page.items {
            let entry = try #require(item.rss)
            #expect(item.key == "rss:\(entry.id)")
        }
    }

    @Test("sort_at 随 envelope 走，且等于 datetime——快照脱离源表也知道自己排在哪")
    func sortAtTravelsWithEnvelope() throws {
        let page = try decoder.decode(TimelinePage.self, from: loadRssFixture("timeline_page_rss"))
        for item in page.items {
            let entry = try #require(item.rss)
            #expect(entry.sortAt == item.datetime)
        }
    }

    @Test("feed 声明未来时间：published_at 原样保留，排序位置是被钳过的 datetime")
    func futurePublishedIsNotTheSortPosition() throws {
        let item = try #require(try rssShapes()["future_published"])
        let entry = try #require(item.rss)
        let published = try #require(entry.publishedAt)
        #expect(published > item.datetime, "声明的时间没有被后端改写")
        #expect(entry.sortAt == item.datetime, "时间线用的是钳制后的值")
    }

    @Test("author 可空——多数 feed 不给，给了就是个人名")
    func author() throws {
        let shapes = try rssShapes()
        let authored = try #require(shapes["authored"]?.rss)
        let anonymous = try #require(shapes["plain"]?.rss)
        #expect(authored.author?.isEmpty == false)
        #expect(anonymous.author == nil)
    }

    @Test("中文 feed 的标题与正文原样解码，不乱码")
    func cjk() throws {
        let entry = try #require(try rssShapes()["cjk"]?.rss)
        let title = try #require(entry.title)
        #expect(title.contains(where: { $0.unicodeScalars.first.map { $0.value > 0x2E80 } ?? false }))
        #expect(entry.content?.isEmpty == false)
    }

    @Test("sources_rss.json：RSS 订阅的 channel_id 是 feed URL（字符串键）")
    func sourcesGroup() throws {
        let groups = try decoder.decode([SourceGroup].self, from: loadRssFixture("sources_rss"))
        let rss = try #require(groups.first { $0.source == SourceID.rss })
        #expect(!rss.subscriptions.isEmpty)
        for sub in rss.subscriptions {
            #expect(sub.channelID.intValue == nil, "URL 键不是 int")
            #expect(sub.channelID.description.contains("://"))
        }
    }

    @Test("SourceID.label：rss 有展示名，真正未知的信源才原样展示")
    func label() {
        #expect(SourceID.label(SourceID.rss) == "RSS")
        #expect(SourceID.label("mastodon") == "mastodon")
    }
}

@Suite("RssEntry 展示逻辑")
struct RssEntryDisplayTests {
    @Test("feed 名：feed_title 优先，没有就用去掉 scheme 与尾斜杠的 URL")
    func feedLabel() throws {
        #expect(RssFeed.label("https://sive.rs/en.atom", name: "Derek Sivers") == "Derek Sivers")
        #expect(RssFeed.label("https://sive.rs/en.atom", name: nil) == "sive.rs/en.atom")
        #expect(RssFeed.label("http://antirez.com/rss/", name: nil) == "antirez.com/rss")
        #expect(RssFeed.label("https://halfrost.com/rss/", name: "") == "halfrost.com/rss",
                "空字符串按没学到标题处理，不画一个空标题")
    }

    @Test("条目的 feedLabel 用同一条规则")
    func entryFeedLabel() throws {
        let entry = try #require(try rssShapes()["plain"]?.rss)
        #expect(entry.feedLabel == RssFeed.label(entry.feedURL, name: entry.feedTitle))
        #expect(entry.feedLabel == "Derek Sivers")
    }

    @Test("标题回落：没有标题就用链接，两者都没有才是占位")
    func displayTitle() throws {
        let shapes = try rssShapes()
        let titled = try #require(shapes["plain"]?.rss)
        let linkless = try #require(shapes["linkless"]?.rss)
        #expect(titled.displayTitle == "tweet")
        #expect(linkless.title == nil && linkless.link == nil)
        #expect(linkless.displayTitle == "(untitled)")
    }

    @Test("articleURL：有链接才有原文入口")
    func articleURL() throws {
        let shapes = try rssShapes()
        let linked = try #require(shapes["plain"]?.rss)
        let linkless = try #require(shapes["linkless"]?.rss)
        #expect(linked.articleURL?.host() == "sive.rs")
        #expect(linkless.articleURL == nil)
    }

    @Test("displaySummary：非空摘要才算有；正文另走 contentText，摘要不替代它")
    func displaySummaryRule() throws {
        let shapes = try rssShapes()
        let summarized = try #require(shapes["summarized"]?.rss)
        #expect(summarized.displaySummary == summarized.summary)
        #expect(summarized.contentText != nil, "有摘要的条目正文照给——卡片先画正文开头再画摘要块")

        let plain = try #require(shapes["html_body"]?.rss)
        #expect(plain.displaySummary == nil)
        let fallback = try #require(plain.contentText)
        #expect(!fallback.contains("<"), "HTML 已经转成纯文本")
        #expect(fallback == rssPlainText(fromHTML: plain.content ?? ""))

        #expect(makeEntry(content: "x", summary: "   ").displaySummary == nil,
                "全空白的摘要不算摘要")
    }

    @Test("contentText 与摘要无关——详情页要在摘要下面接着给全文")
    func contentTextIgnoresSummary() throws {
        let summarized = try #require(try rssShapes()["summarized"]?.rss)
        let text = try #require(summarized.contentText)
        #expect(summarized.summary?.isEmpty == false)
        #expect(text != summarized.summary)
        #expect(text == rssPlainText(fromHTML: summarized.content ?? ""))
    }

    @Test("正文两者皆空 → 卡片没有可画的正文（只画标题）")
    func emptyBody() {
        let empty = makeEntry(content: nil, summary: nil)
        #expect(empty.contentText == nil && empty.displaySummary == nil)
        #expect(makeEntry(content: "   <p> </p>  ", summary: nil).contentText == nil,
                "只有标签和空白的正文不算正文")
    }

    /// 只为体现「正文来源」这一个维度的最小条目
    private func makeEntry(content: String?, summary: String?) -> RssEntry {
        RssEntry(
            id: 1, guid: nil, feedURL: "https://example.com/feed", feedTitle: nil,
            title: "t", link: nil, author: nil, content: content, summary: summary,
            publishedAt: nil, firstSeenAt: Date(timeIntervalSince1970: 0), sortAt: nil)
    }
}

@Suite("rssPlainText")
struct RssTextTests {
    @Test("块级标签转换行；<br> 也是")
    func blocks() {
        let html = "<p>first</p><p>second</p><div>third</div>a<br>b"
        #expect(rssPlainText(fromHTML: html) == "first\n\nsecond\n\nthird\n\na\nb")
    }

    @Test("列表项前面加圆点——纯文本里不这样做，几行清单会糊成一段")
    func listItems() {
        let html = "<ul><li>one</li><li>two</li></ul>"
        #expect(rssPlainText(fromHTML: html) == "• one\n• two")
    }

    @Test("script / style 连内容一起丢掉（只剥标签会把 JS 源码打印在卡片上）")
    func scriptsAreDropped() {
        let html = "<p>before</p><script>var x = 1 < 2;</script><style>.a{color:red}</style><p>after</p>"
        #expect(rssPlainText(fromHTML: html) == "before\n\nafter")
    }

    @Test("链接保留锚文本，不换成 href——feed 的锚文本是作者写的句子")
    func linksKeepTheirText() {
        let html = #"<p>as I <a href="https://example.com/x">wrote earlier</a>, it works</p>"#
        #expect(rssPlainText(fromHTML: html) == "as I wrote earlier, it works")
    }

    @Test("图片没有纯文本形态，整个丢掉")
    func imagesDropped() {
        let html = #"<p>look:</p><img src="https://example.com/a.png" alt="a"><p>done</p>"#
        #expect(rssPlainText(fromHTML: html) == "look:\n\ndone")
    }

    @Test("实体：命名 / 十进制 / 十六进制都解，&amp; 不被二次解码")
    func entities() {
        #expect(rssPlainText(fromHTML: "a &lt;b&gt; &quot;c&quot; &nbsp;d") == "a <b> \"c\" d")
        #expect(rssPlainText(fromHTML: "it&#8217;s &#x27;quoted&#x27; &#8212; yes") == "it’s 'quoted' — yes")
        #expect(rssPlainText(fromHTML: "&amp;lt;not a tag&amp;gt;") == "&lt;not a tag&gt;")
    }

    @Test("源码里的换行只是空白，不当成断行——否则句子会在中间硬折")
    func sourceNewlinesAreWhitespace() {
        let html = "<p>one sentence\n   wrapped in the source</p>"
        #expect(rssPlainText(fromHTML: html) == "one sentence wrapped in the source")
    }

    @Test("<pre> 里的换行与缩进保留——代码块是这个规则的唯一例外")
    func preKeepsItsShape() {
        let html = "<p>example:</p><pre><code>def f():\n    return 1</code></pre><p>done</p>"
        #expect(rssPlainText(fromHTML: html) == "example:\n\ndef f():\n    return 1\n\ndone")
    }

    @Test("连续空行折叠，首尾空白修剪")
    func collapses() {
        #expect(rssPlainText(fromHTML: "<div><p></p><p>only</p><p></p></div>") == "only")
    }

    @Test("中文正文原样通过")
    func cjk() {
        let html = "<p>下一个五年计划起航！</p><p>写在前面</p>"
        #expect(rssPlainText(fromHTML: html) == "下一个五年计划起航！\n\n写在前面")
    }

    @Test("真实 feed 正文：转出来没有标签残留，也没有三连空行")
    func realFeedBody() throws {
        // 裸的 "<" 不能当判据：讲代码的博客正文里 `a < b` 就是内容
        let tag = try NSRegularExpression(pattern: "</?(p|div|a|br|img|span|h[1-6]|li)\\b",
                                          options: [.caseInsensitive])
        for key in ["html_body", "cjk", "authored"] {
            let entry = try #require(try rssShapes()[key]?.rss)
            let text = rssPlainText(fromHTML: try #require(entry.content))
            let hits = tag.numberOfMatches(in: text, range: NSRange(text.startIndex..., in: text))
            #expect(hits == 0, "\(key): 标签残留")
            #expect(!text.contains("\n\n\n"), "\(key): 空行没折叠")
            #expect(!text.contains("&nbsp;"), "\(key): 实体没解")
            #expect(!text.isEmpty)
        }
    }
}
