import Foundation
import Testing
@testable import CondenserKit

// RSS 详情的分块解析（2026-08-23）：全文 HTML → 文本块 + 图片块，图片才能
// 在原生 UI 里占到自己的位置。规则与 `rssPlainText` 共享同一条管线（占位符
// 先行替换），所以纯文本部分的行为以那边的测试为准，这里只测「切块」本身。

@Suite("rssBlocks")
struct RssBlocksTests {
    /// rss:677（kawabangga）的真实形状：`<a><img/></a>` 包在 `<figure>` 里，
    /// 夹在段落之间，绝对 URL + width/height 属性
    @Test("figure/img 夹在段落之间：切成 文-图-文，width/height 带出来")
    func figureBetweenParagraphs() {
        let html = """
            <p class="wp-block-paragraph">时间过得真快，Rick and Morty 已经播出 13 年了。</p>
            <div class="wp-block-image">
            <figure class="aligncenter size-large is-resized"><a href="https://example.com/full.png"><img alt="" class="wp-image-7316" height="572" src="https://example.com/rick-1024x572.png" style="width: 373px; height: auto;" width="1024" /></a></figure>
            </div>
            <p class="wp-block-paragraph">但 13 年之后，我理解了 Rick……</p>
            """
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [
            .text("时间过得真快，Rick and Morty 已经播出 13 年了。"),
            .image(RssImage(src: "https://example.com/rick-1024x572.png", width: 1024, height: 572)),
            .text("但 13 年之后，我理解了 Rick……"),
        ])
    }

    @Test("两张图：块顺序与原文一致，图片各自成块")
    func twoImages() {
        let html = """
            <p>first</p>
            <figure><img src="https://a.test/1.png" width="100" height="50"/></figure>
            <p>middle</p>
            <figure><img src="https://a.test/2.jpeg" width="200" height="100"/></figure>
            <p>last</p>
            """
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [
            .text("first"),
            .image(RssImage(src: "https://a.test/1.png", width: 100, height: 50)),
            .text("middle"),
            .image(RssImage(src: "https://a.test/2.jpeg", width: 200, height: 100)),
            .text("last"),
        ])
    }

    @Test("相对 URL 按 baseURL（文章 link）解析成绝对——大量 feed 写相对路径")
    func relativeURL() {
        let html = "<p>a</p><img src=\"/images/pic.png\"><p>b</p>"
        let blocks = rssBlocks(
            fromHTML: html, baseURL: URL(string: "https://blog.test/posts/2026/hello"))
        #expect(blocks == [
            .text("a"),
            .image(RssImage(src: "https://blog.test/images/pic.png", width: nil, height: nil)),
            .text("b"),
        ])
    }

    @Test("lazy-load 兜底：src 是 data: 占位图时回落 data-src——WordPress 插件的常见发法")
    func lazyLoadDataSrc() {
        let html = """
            <img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" \
            data-src="https://a.test/real.png" width="10" height="20">
            """
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [.image(RssImage(src: "https://a.test/real.png", width: 10, height: 20))])
    }

    @Test("src 缺失时回落 data-original")
    func lazyLoadDataOriginal() {
        let html = "<p>t</p><img data-original=\"https://a.test/orig.jpg\">"
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [
            .text("t"),
            .image(RssImage(src: "https://a.test/orig.jpg", width: nil, height: nil)),
        ])
    }

    @Test("无图 HTML：单个文本块，内容等价 rssPlainText——调用方不必分辨两条路径")
    func noImagesEqualsPlainText() {
        let html = "<p>one</p><p>two <a href=\"https://x.test\">link</a></p>"
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [.text(rssPlainText(fromHTML: html))])
    }

    @Test("<pre> 的缩进与换行留在文本块里——共享管线，不是另一套规则")
    func preSurvivesInsideTextBlock() {
        let html = "<p>look:</p><pre>if x:\n    y()</pre><img src=\"https://a.test/p.png\">"
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [
            .text("look:\n\nif x:\n    y()"),
            .image(RssImage(src: "https://a.test/p.png", width: nil, height: nil)),
        ])
    }

    @Test("<script> 连内容丢弃，藏在里面的 <img> 不产生图片块")
    func scriptDroppedWithItsImage() {
        let html = "<p>a</p><script>var s = '<img src=\"https://evil.test/x.png\">';</script><p>b</p>"
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [.text("a\n\nb")])
    }

    @Test("有图但一张都解析不出（全是 data URI）：退化为单个文本块")
    func allDataURIsDegradeToText() {
        let html = "<p>only text</p><img src=\"data:image/png;base64,AAAA\">"
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [.text("only text")])
    }

    @Test("src 属性里的 &amp; 实体要解码——HTML 属性是实体编码的")
    func entityDecodedSrc() {
        let html = "<img src=\"https://a.test/i.png?w=1&amp;h=2\">"
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [
            .image(RssImage(src: "https://a.test/i.png?w=1&h=2", width: nil, height: nil)),
        ])
    }

    @Test("width/height 不是纯数字（auto / 百分比）时为 nil，不猜")
    func nonNumericDimensions() {
        let html = "<img src=\"https://a.test/i.png\" width=\"100%\" height=\"auto\">"
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [.image(RssImage(src: "https://a.test/i.png", width: nil, height: nil))])
    }

    @Test("单引号与无引号属性都认——真实 feed 两种都发")
    func quoteStyles() {
        let html = "<img src='https://a.test/sq.png' width=640 height=480>"
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [.image(RssImage(src: "https://a.test/sq.png", width: 640, height: 480))])
    }

    @Test("空输入：空块列表")
    func emptyHTML() {
        #expect(rssBlocks(fromHTML: "", baseURL: nil) == [])
    }

    @Test("figcaption 不单独建模：文字落进图片后面的文本块，顺序对读者是对的")
    func figcaptionFlowsIntoText() {
        let html = """
            <figure><img src="https://a.test/f.png"><figcaption>the caption</figcaption></figure>
            <p>after</p>
            """
        let blocks = rssBlocks(fromHTML: html, baseURL: nil)
        #expect(blocks == [
            .image(RssImage(src: "https://a.test/f.png", width: nil, height: nil)),
            .text("the caption\n\nafter"),
        ])
    }
}
