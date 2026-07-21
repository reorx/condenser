import Foundation

/// HN self-post 的 `text` 是 HN 风味的 HTML 片段（段落以 <p> 分隔、链接 <a>、
/// 斜体 <i>、代码 <pre><code>，实体转义）。iOS 只读展示用纯文本即可：
/// 标签转换为换行/原文，实体解码，交给 UI 层再做链接高亮。
public func hnPlainText(fromHTML html: String) -> String {
    var text = html
    // 段落/换行标签 → 换行（HN 的 <p> 是分隔符不是包裹符）；
    // 注意不能写成 <p[^>]*>，会误伤 <pre>
    text = text.replacingOccurrences(
        of: "<p(\\s[^>]*)?>", with: "\n\n", options: [.regularExpression, .caseInsensitive])
    text = text.replacingOccurrences(
        of: "<br\\s*/?>", with: "\n", options: [.regularExpression, .caseInsensitive])
    // 链接：展示 href（HN 会把长链接文本截断成 "…"，href 才是完整的）
    text = text.replacingOccurrences(
        of: "<a[^>]*href=\"([^\"]*)\"[^>]*>.*?</a>",
        with: "$1", options: [.regularExpression, .caseInsensitive])
    // 其余标签剥掉
    text = text.replacingOccurrences(
        of: "<[^>]+>", with: "", options: .regularExpression)
    // 常见实体（HN 转义集很小：& < > " '）。&amp; 必须最后解码，
    // 否则 "&amp;lt;" 会被二次解码成 "<"
    let entities = [
        ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", "\""), ("&#x27;", "'"), ("&#39;", "'"), ("&nbsp;", " "),
        ("&amp;", "&"),
    ]
    for (entity, char) in entities {
        text = text.replacingOccurrences(of: entity, with: char)
    }
    return text.trimmingCharacters(in: .whitespacesAndNewlines)
}
