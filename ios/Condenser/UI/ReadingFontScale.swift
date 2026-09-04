import SwiftUI
import CondenserKit

extension FontScale {
    /// AppStorage 持久化 key（设置页写、阅读界面读）
    static let storageKey = "condenser.fontScale"

    /// iPhone：档位 → 固定 DynamicTypeSize，整套字体由系统表等比缩放（正常 = 系统默认 .large）。
    /// 注意这会覆盖系统动态字号，只应用在消息阅读界面，不动全局 UI。
    var dynamicTypeSize: DynamicTypeSize {
        switch self {
        case .small: .small
        case .normal: .large
        case .large: .xLarge
        case .xLarge: .xxLarge
        }
    }
}

/// Mac：当前阅读档位走环境值而不是 DynamicTypeSize——Catalyst 的 Mac idiom 没有 Dynamic Type
/// （`.dynamicTypeSize` 是空操作，2026-09-04 实测），字号得由 `readingFont` 按档位自己算
/// （点值表在 Kit 的 `ReadingTextStyle`）。缺省「正常」，所以没挂 `readingFontScale()` 的
/// 子树（分享图）在 Mac 上也拿到 iOS 默认表的尺寸，两端出图一致。
private struct ReadingFontScaleKey: EnvironmentKey {
    static let defaultValue: FontScale = .normal
}

extension EnvironmentValues {
    var readingFontScale: FontScale {
        get { self[ReadingFontScaleKey.self] }
        set { self[ReadingFontScaleKey.self] = newValue }
    }
}

/// 读取设置档位并应用；AppStorage 变化时自动刷新
private struct ReadingFontScaleModifier: ViewModifier {
    @AppStorage(FontScale.storageKey) private var raw = FontScale.default.rawValue

    func body(content: Content) -> some View {
        content.readingFontScale(FontScale(storedValue: raw))
    }
}

/// 阅读界面的文字样式：iPhone 上就是 `.font(.subheadline)` 之类的 Dynamic Type 样式，
/// Mac 上按环境里的档位换成显式点值。阅读界面（卡片 / 详情 sheet / 分享图）一律用它
/// 而不是 `.font(.xxx)`，否则 Mac 上滑块对那处文字无效。
private struct ReadingFontModifier: ViewModifier {
    let style: ReadingTextStyle
    let weight: Font.Weight?
    @Environment(\.readingFontScale) private var scale

    func body(content: Content) -> some View {
        content.font(readingFont(style, weight: weight, scale: scale))
    }
}

/// `ReadingFontModifier` 的 Font 值版本，给需要 Font 本身的地方（AttributedString 等）
func readingFont(_ style: ReadingTextStyle, weight: Font.Weight? = nil, scale: FontScale) -> Font {
    if Platform.isMac {
        // headline 在 iOS 表里自带 semibold，显式尺寸要把这层默认补回来
        let defaultWeight: Font.Weight = style == .headline ? .semibold : .regular
        return .system(size: style.pointSize(for: scale), weight: weight ?? defaultWeight)
    }
    let font = Font.system(style.textStyle)
    return weight.map { font.weight($0) } ?? font
}

extension ReadingTextStyle {
    var textStyle: Font.TextStyle {
        switch self {
        case .largeTitle: .largeTitle
        case .title2: .title2
        case .title3: .title3
        case .headline: .headline
        case .body: .body
        case .subheadline: .subheadline
        case .footnote: .footnote
        case .caption: .caption
        case .caption2: .caption2
        }
    }
}

extension View {
    /// 消息阅读界面（timeline / 频道 / 收藏列表、详情 sheet）应用设置页选择的字号档位
    func readingFontScale() -> some View {
        modifier(ReadingFontScaleModifier())
    }

    /// 指定档位（设置页的预览卡用；AppStorage 版本也经由它）
    @ViewBuilder
    func readingFontScale(_ scale: FontScale) -> some View {
        if Platform.isMac {
            environment(\.readingFontScale, scale)
        } else {
            dynamicTypeSize(scale.dynamicTypeSize)
        }
    }

    func readingFont(_ style: ReadingTextStyle, weight: Font.Weight? = nil) -> some View {
        modifier(ReadingFontModifier(style: style, weight: weight))
    }
}
