import Foundation

/// RSS 全文的一个渲染块：详情界面把文字交给文本视图、图片交给图片视图，
/// 图片才能占到自己的位置（纯文本管线里 `<img>` 没有内容，整个消失）。
public enum RssBlock: Equatable, Sendable {
    case text(String)
    case image(RssImage)
}

/// 全文里的一张图。`<figcaption>` 不单独建模：它的文字自然落进下一个文本块，
/// 顺序对读者是对的，少一个概念。
public struct RssImage: Equatable, Sendable {
    /// 已解析成绝对 URL（相对路径按文章 link 解析），只会是 http/https——
    /// `data:` 一律丢弃，服务端代理 `_require_http_url` 也会拒它
    public let src: String
    /// `<img>` 的 width/height 属性；UI 用它预留纵横比，图片加载完不跳动。
    /// 非纯数字（`auto` / 百分比）时为 nil，不猜。
    public let width: Int?
    public let height: Int?

    public init(src: String, width: Int? = nil, height: Int? = nil) {
        self.src = src
        self.width = width
        self.height = height
    }
}

/// 全文 HTML → 块序列。**不是另一套 HTML 处理**：`rssPlainText` 里那些决定
/// （`<script>`/`<style>` 连内容丢、`<pre>` 摘出再放回、锚文本保留、源码换行按空白）
/// 是踩出来的，分叉一份必然漂移。做法是先把 `<img>` 换成私用区占位符、跑完既有
/// 管线，再按占位符切块——两条路径共享同一份规则。副产物是对的行为：藏在
/// `<script>` 里的 `<img>` 连占位符一起被丢掉，不会产生图片块。
public func rssBlocks(fromHTML html: String, baseURL: URL?) -> [RssBlock] {
    let lifted = liftImages(html, baseURL: baseURL)
    let text = rssPlainText(fromHTML: lifted.text)
    guard !lifted.images.isEmpty else {
        return text.isEmpty ? [] : [.text(text)]
    }
    return split(text, images: lifted.images)
}

/// 图片占位符的包围字符。`rssPlainText` 的 `<pre>` 用了 U+E000，这里取下一个码位：
/// 同样不会出现在真实正文里、不含空白，能安然穿过空白折叠与标签剥除。
private let imgToken = "\u{E001}"

/// `<img>` 换成带下标的占位符，属性解析成 `RssImage`。解析不出 src 的
/// （缺失且无 lazy-load 兜底、或全是 data URI）直接删掉——与纯文本管线里
/// 「img 整个消失」同一个结果，也因此不会占用下标。
private func liftImages(_ html: String, baseURL: URL?) -> (text: String, images: [RssImage]) {
    guard let regex = try? NSRegularExpression(
        pattern: "<img\\b[^>]*>", options: [.caseInsensitive])
    else { return (html, []) }
    var text = html
    let matches = regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
    guard !matches.isEmpty else { return (text, []) }
    var images: [RssImage] = []
    var replacements: [(range: Range<String.Index>, token: String)] = []
    for match in matches {
        guard let range = Range(match.range, in: text) else { continue }
        guard let image = parseImage(String(text[range]), baseURL: baseURL) else {
            replacements.append((range, ""))
            continue
        }
        replacements.append((range, "\n\n\(imgToken)\(images.count)\(imgToken)\n\n"))
        images.append(image)
    }
    // 逆序替换，前面的 range 才不失效（下标已按正序编号）
    for (range, token) in replacements.reversed() {
        text.replaceSubrange(range, with: token)
    }
    return (text, images)
}

/// 一个 `<img>` 标签 → RssImage。src 缺失或是 data: 占位图时回落
/// `data-src` / `data-original`——很多 WordPress lazy-load 插件就是这么发的。
private func parseImage(_ tag: String, baseURL: URL?) -> RssImage? {
    var raw: String?
    for name in ["src", "data-src", "data-original"] {
        guard let value = attribute(name, in: tag), !value.isEmpty,
              !value.lowercased().hasPrefix("data:") else { continue }
        raw = value
        break
    }
    guard let raw,
          let url = URL(string: decodeEntities(raw), relativeTo: baseURL),
          let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https"
    else { return nil }
    return RssImage(
        src: url.absoluteString,
        width: attribute("width", in: tag).flatMap { Int($0) },
        height: attribute("height", in: tag).flatMap { Int($0) })
}

/// 标签字符串里的一个属性值；双引号 / 单引号 / 无引号三种写法都认
private func attribute(_ name: String, in tag: String) -> String? {
    guard let regex = try? NSRegularExpression(
        pattern: "\\b\(name)\\s*=\\s*(?:\"([^\"]*)\"|'([^']*)'|([^\\s>]+))",
        options: [.caseInsensitive])
    else { return nil }
    guard let match = regex.firstMatch(in: tag, range: NSRange(tag.startIndex..., in: tag))
    else { return nil }
    for group in 1...3 {
        if let range = Range(match.range(at: group), in: tag) {
            return String(tag[range])
        }
    }
    return nil
}

/// 处理完的纯文本按占位符切块。空文本块丢弃；相邻文本块合并（正常流程里
/// 不会出现，留作占位符损坏时的兜底，宁可多两个换行也不吐占位字符）。
private func split(_ text: String, images: [RssImage]) -> [RssBlock] {
    guard let regex = try? NSRegularExpression(pattern: "\(imgToken)(\\d+)\(imgToken)")
    else { return text.isEmpty ? [] : [.text(text)] }
    var blocks: [RssBlock] = []
    func appendText(_ segment: Substring) {
        let trimmed = segment.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if case let .text(previous) = blocks.last {
            blocks[blocks.count - 1] = .text(previous + "\n\n" + trimmed)
        } else {
            blocks.append(.text(trimmed))
        }
    }
    var cursor = text.startIndex
    for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
        guard let whole = Range(match.range, in: text),
              let digits = Range(match.range(at: 1), in: text),
              let index = Int(text[digits]), index < images.count else { continue }
        appendText(text[cursor..<whole.lowerBound])
        blocks.append(.image(images[index]))
        cursor = whole.upperBound
    }
    appendText(text[cursor...])
    return blocks
}
