import SwiftUI
import UIKit

/// NSDataDetector 构造成本高（毫秒级），全局建一次复用；matching 线程安全
private let linkDetector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)

/// NSDataDetector 标注 URL → AttributedString 链接（点击由 openURL 环境接管）。
/// timeline 卡片与详情 sheet 共用。
func linkified(_ text: String) -> AttributedString {
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
    return attr
}

/// UITextView（详情 sheet 可选择正文）用的同款链接标注，输出 NSAttributedString
func linkifiedNS(_ text: String, font: UIFont) -> NSAttributedString {
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
    return attr
}
