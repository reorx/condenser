import SwiftUI
import CondenserKit

extension FontScale {
    /// AppStorage 持久化 key（设置页写、阅读界面读）
    static let storageKey = "condenser.fontScale"

    /// 档位 → 固定 DynamicTypeSize：整套字体等比缩放（正常 = 系统默认 .large）。
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

/// 读取设置档位并应用为固定字号；AppStorage 变化时自动刷新
private struct ReadingFontScaleModifier: ViewModifier {
    @AppStorage(FontScale.storageKey) private var raw = FontScale.default.rawValue

    func body(content: Content) -> some View {
        content.dynamicTypeSize(FontScale(storedValue: raw).dynamicTypeSize)
    }
}

extension View {
    /// 消息阅读界面（timeline / 频道 / 收藏列表、详情 sheet）应用设置页选择的字号档位
    func readingFontScale() -> some View {
        modifier(ReadingFontScaleModifier())
    }
}
