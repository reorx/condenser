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
    // 实体解码与 RSS 共用一份（含数字实体）。HN 的转义集确实很小，但 **href 本身
    // 也是转义的**：斜杠写作 `&#x2F;`，而上面那条规则刚把链接换成了 href——
    // 只认几个命名实体的话，正文里印出来的就是一串 `&#x2F;`（2026-08-23 从分享图上
    // 看见的，抽屉里一直是这样）
    return decodeEntities(text).trimmingCharacters(in: .whitespacesAndNewlines)
}
