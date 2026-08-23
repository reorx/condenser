import Testing
@testable import CondenserKit

// HN self-post HTML → 纯文本：段落/换行、链接还原 href、实体解码、标签剥离。

@Suite("hnPlainText")
struct HnTextTests {
    @Test("<p> 分隔符转段落空行")
    func paragraphs() {
        let html = "first line<p>second line<p>third"
        #expect(hnPlainText(fromHTML: html) == "first line\n\nsecond line\n\nthird")
    }

    @Test("链接还原为完整 href（HN 显示文本可能被截断）")
    func links() {
        let html = #"see <a href="https://example.com/very/long/path" rel="nofollow">https:&#x2F;&#x2F;example.com&#x2F;very&#x2F;lo...</a> now"#
        #expect(hnPlainText(fromHTML: html) == "see https://example.com/very/long/path now")
    }

    @Test("href 本身也是实体编码的——数字实体不解，正文里印的就是 &#x2F;")
    func escapedHref() {
        // 真实的 HN self-post（story 49402189）就是这个形状：href 里的斜杠是 &#x2F;，
        // 换成 href 之后如果不解数字实体，读者看到的是一串编码
        let html = #"<a href="https:&#x2F;&#x2F;xcancel.com&#x2F;moxie&#x2F;status&#x2F;209" rel="nofollow">https:&#x2F;&#x2F;xcancel.com&#x2F;mo...</a>"#
        #expect(hnPlainText(fromHTML: html) == "https://xcancel.com/moxie/status/209")
    }

    @Test("实体解码；&amp; 不被二次解码")
    func entities() {
        #expect(hnPlainText(fromHTML: "a &amp;&amp; b &lt;c&gt; &quot;d&quot; it&#x27;s") == #"a && b <c> "d" it's"#)
        #expect(hnPlainText(fromHTML: "&amp;lt;not a tag&amp;gt;") == "&lt;not a tag&gt;")
    }

    @Test("斜体/代码等标签剥离，内容保留")
    func stripTags() {
        let html = "normal <i>italic</i> and <pre><code>let x = 1</code></pre> tail"
        #expect(hnPlainText(fromHTML: html) == "normal italic and let x = 1 tail")
    }

    @Test("首尾空白与换行修剪")
    func trims() {
        #expect(hnPlainText(fromHTML: "<p>hello<p>") == "hello")
    }
}
