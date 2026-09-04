import Foundation

/// 阅读界面用到的文字样式，以及它们在 **Mac** 上的点值。
///
/// iPhone 上字号档位走 Dynamic Type（`FontScale` → `DynamicTypeSize`，app 层映射），
/// 整套字体由系统表等比缩放。Mac Catalyst 的「Optimize for Mac」idiom 没有 Dynamic Type：
/// 2026-09-04 实测 `UIFont.preferredFont(forTextStyle:compatibleWith:)` 对任何 content size
/// category 都返回同一尺寸（body 13 / subheadline 11），SwiftUI 的 `.dynamicTypeSize` 也随之
/// 成了空操作。所以 Mac 上的档位要自己算：以 **iOS 默认（.large）表**为基准点值，乘上档位倍率。
/// 「正常」档因此与 iPhone 同一档看起来一样大——卡片正文 15pt 而不是 Mac 表的 11pt，后者是
/// 2026-09-04 用户反馈「字偏小」的直接原因。
public enum ReadingTextStyle: CaseIterable, Sendable, Equatable {
    case largeTitle, title2, title3, headline, body, subheadline, footnote, caption, caption2

    /// iOS Dynamic Type 默认档（.large）的点值，HIG 的标准表
    public var basePointSize: Double {
        switch self {
        case .largeTitle: 34
        case .title2: 22
        case .title3: 20
        case .headline: 17
        case .body: 17
        case .subheadline: 15
        case .footnote: 13
        case .caption: 12
        case .caption2: 11
        }
    }

    /// Mac 上该档位的点值
    public func pointSize(for scale: FontScale) -> Double {
        (basePointSize * scale.macMultiplier).rounded()
    }
}

extension FontScale {
    /// Mac 档位倍率。取值对着 iOS body 在 S / L / XL / XXL 四档的 15 / 17 / 19 / 21，
    /// 使同一档在两端的正文字号一致
    public var macMultiplier: Double {
        switch self {
        case .small: 15.0 / 17.0
        case .normal: 1.0
        case .large: 19.0 / 17.0
        case .xLarge: 21.0 / 17.0
        }
    }
}
