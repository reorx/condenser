import Foundation

/// feed 自带正文（任意 HTML）→ 纯文本。`hnPlainText` 的同类，但**不是**它的推广：
/// HN 的 `text` 是一个小到能穷举的子集（<p> <a> <i> <pre>，五个实体），而 RSS 收到的
/// 是整个开放网络的 HTML——列表、标题、表格、内联 style、乃至 <script>。所以两者的
/// 规则在三处刻意相反：
///
/// 1. **链接保留锚文本**，不换成 href。HN 会把长链接的显示文本截断成 `https:/…`，
///    href 才是完整信息；feed 的锚文本是作者写在句子里的词，换成 URL 会把句子拆散。
/// 2. **<script> / <style> 连内容一起丢掉**。只剥标签的话，JS 源码会当成正文印在卡片上。
/// 3. **源码换行按空白处理**，只有块级标签才产生断行——feed 的 HTML 常常是格式化过的，
///    句子在源码里换行，照搬就会在句子中间硬折。唯一例外是 `<pre>`：那里的换行与缩进
///    是内容本身，所以整块先被摘出去，等其余部分处理完再放回来。
public func rssPlainText(fromHTML html: String) -> String {
    var text = drop(tags: ["script", "style"], in: html)
    let lifted = liftPreBlocks(text)
    text = lifted.text
    // HTML 里连续空白（含换行）渲染成一个空格；断行只由标签决定
    text = text.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
    text = text.replacingOccurrences(
        of: "<br\\s*/?>", with: "\n", options: [.regularExpression, .caseInsensitive])
    // 清单项前置圆点：几行清单不这样标就会糊成一段
    text = text.replacingOccurrences(
        of: "<li(\\s[^>]*)?>", with: "\n• ", options: [.regularExpression, .caseInsensitive])
    text = text.replacingOccurrences(
        of: "</?(\(blockTags))(\\s[^>]*)?/?>", with: "\n\n",
        options: [.regularExpression, .caseInsensitive])
    // 其余标签剥掉、内容保留（a / em / strong / code / span…）；
    // <img> 没有内容，于是整个消失——纯文本里本来也没有它的位置
    text = text.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
    text = decodeEntities(text)
    // 折叠必须在放回 <pre> 之前：它逐行去空白，而代码块的缩进正是要留住的东西
    text = collapse(text)
    return restorePreBlocks(text, from: lifted.blocks)
        .trimmingCharacters(in: .whitespacesAndNewlines)
}

/// 块级元素：开合标签都当断行点（结束标签也算，`<div>a</div><div>b</div>` 才不会连成一行）
private let blockTags = [
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "tr", "td",
    "blockquote", "section", "article", "header", "footer", "aside", "figure",
    "figcaption", "hr", "dl", "dt", "dd", "pre",
].joined(separator: "|")

/// 标签连同内容一起删除
private func drop(tags: [String], in html: String) -> String {
    var text = html
    for tag in tags {
        text = text.replacingOccurrences(
            of: "<\(tag)\\b[^>]*>[\\s\\S]*?</\(tag)\\s*>", with: "",
            options: [.regularExpression, .caseInsensitive])
        // 没有闭合的孤儿标签也不能留在正文里
        text = text.replacingOccurrences(
            of: "<\(tag)\\b[^>]*>", with: "", options: [.regularExpression, .caseInsensitive])
    }
    return text
}

/// 私用区字符做占位符：不会出现在真实正文里，也不含空白，能安然穿过空白折叠
private let preToken = "\u{E000}"

/// `<pre>` 块摘出去（内部标签剥掉、实体解码），原地留一个占位符。
/// 逆序替换是为了让前面的 range 不失效；下标按正序编号，恢复时才对得上。
private func liftPreBlocks(_ html: String) -> (text: String, blocks: [String]) {
    guard let regex = try? NSRegularExpression(
        pattern: "<pre\\b[^>]*>([\\s\\S]*?)</pre\\s*>", options: [.caseInsensitive])
    else { return (html, []) }
    var text = html
    let matches = regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
    guard !matches.isEmpty else { return (text, []) }
    var blocks = [String](repeating: "", count: matches.count)
    for (index, match) in matches.enumerated().reversed() {
        guard let whole = Range(match.range, in: text),
              let inner = Range(match.range(at: 1), in: text) else { continue }
        blocks[index] = decodeEntities(
            String(text[inner])
                .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression))
        text.replaceSubrange(whole, with: "\n\n\(preToken)\(index)\(preToken)\n\n")
    }
    return (text, blocks)
}

private func restorePreBlocks(_ text: String, from blocks: [String]) -> String {
    var out = text
    for (index, body) in blocks.enumerated() {
        out = out.replacingOccurrences(
            of: "\(preToken)\(index)\(preToken)",
            with: body.trimmingCharacters(in: .newlines))
    }
    return out
}

/// 命名 / 十进制 / 十六进制实体。`&amp;` 必须最后解码，
/// 否则 `&amp;lt;` 会被二次解码成 `<`（`hnPlainText` 的同一条约束）。
private func decodeEntities(_ input: String) -> String {
    var text = decodeNumericEntities(input)
    let named = [
        ("&lt;", "<"), ("&gt;", ">"), ("&quot;", "\""), ("&apos;", "'"),
        ("&nbsp;", " "), ("&hellip;", "…"), ("&mdash;", "—"), ("&ndash;", "–"),
        ("&lsquo;", "‘"), ("&rsquo;", "’"), ("&ldquo;", "“"), ("&rdquo;", "”"),
        ("&middot;", "·"), ("&bull;", "•"), ("&laquo;", "«"), ("&raquo;", "»"),
        ("&amp;", "&"),
    ]
    for (entity, char) in named {
        text = text.replacingOccurrences(of: entity, with: char)
    }
    return text
}

private func decodeNumericEntities(_ input: String) -> String {
    guard let regex = try? NSRegularExpression(
        pattern: "&#(x?)([0-9a-fA-F]+);", options: [.caseInsensitive])
    else { return input }
    var text = input
    let matches = regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
    for match in matches.reversed() {
        guard let whole = Range(match.range, in: text),
              let prefix = Range(match.range(at: 1), in: text),
              let digits = Range(match.range(at: 2), in: text) else { continue }
        let radix = text[prefix].isEmpty ? 10 : 16
        guard let code = UInt32(text[digits], radix: radix),
              let scalar = Unicode.Scalar(code) else { continue }
        text.replaceSubrange(whole, with: String(Character(scalar)))
    }
    return text
}

/// 逐行：横向空白折叠成一个空格（`&nbsp;` 解码后才现身，赶不上前面那趟）、
/// 首尾修剪；然后连续空行折叠成一个，整体修剪。
private func collapse(_ text: String) -> String {
    var out: [String] = []
    for raw in text.components(separatedBy: "\n") {
        let line = raw
            .replacingOccurrences(of: "[ \\t]+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
        if line.isEmpty, out.last?.isEmpty ?? true { continue }
        out.append(line)
    }
    return out.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
}
