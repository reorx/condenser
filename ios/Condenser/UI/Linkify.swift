import CondenserKit
import SwiftUI
import UIKit

/// NSDataDetector 构造成本高（毫秒级），全局建一次复用；matching 线程安全
private let linkDetector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)

/// NSDataDetector 标注 URL → AttributedString 链接（点击由 openURL 环境接管）。
/// timeline 卡片与详情 sheet 共用。`urlEntities`（仅 X，schema v13）把匹配到的
/// t.co 升级成原始链接：锚文本 display_url、href expanded_url——X 官方 UI 的行为；
/// 元数据不认识的 t.co 原样保留（老数据 / probe 未升级的降级路径），逐条生效。
/// 按 t.co 字符串精确匹配，不用 indices（剥掉 RT 前缀 / 长文标题之后就错位了）。
func linkified(_ text: String, urlEntities: [XUrlEntity]? = nil) -> AttributedString {
    var attr = AttributedString(text)
    guard let detector = linkDetector else { return attr }
    let ns = text as NSString
    for match in detector.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
        guard let url = match.url,
              let range = Range(match.range, in: text),
              let attrRange = attr.range(of: String(text[range]))
        else { continue }
        attr[attrRange].link = url
        attr[attrRange].foregroundColor = .accentColor
    }
    for entity in urlEntities ?? [] {
        guard let expanded = entity.expandedURL, let href = URL(string: expanded) else { continue }
        while let range = attr.range(of: entity.url) {
            var replacement = AttributedString(entity.displayURL ?? expanded)
            replacement.link = href
            replacement.foregroundColor = .accentColor
            attr.replaceSubrange(range, with: replacement)
        }
    }
    return attr
}

/// UITextView（详情 sheet 可选择正文）用的同款链接标注，输出 NSAttributedString
func linkifiedNS(_ text: String, font: UIFont, urlEntities: [XUrlEntity]? = nil) -> NSAttributedString {
    let attr = NSMutableAttributedString(string: text, attributes: [
        .font: font,
        .foregroundColor: UIColor.label,
    ])
    guard let detector = linkDetector else { return attr }
    let ns = text as NSString
    for match in detector.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
        guard let url = match.url else { continue }
        attr.addAttribute(.link, value: url, range: match.range)
    }
    for entity in urlEntities ?? [] {
        guard let expanded = entity.expandedURL, let href = URL(string: expanded) else { continue }
        while true {
            let range = (attr.string as NSString).range(of: entity.url)
            if range.location == NSNotFound { break }
            attr.replaceCharacters(in: range, with: entity.displayURL ?? expanded)
            let newLength = ((entity.displayURL ?? expanded) as NSString).length
            attr.addAttribute(.link, value: href, range: NSRange(location: range.location, length: newLength))
        }
    }
    return attr
}
