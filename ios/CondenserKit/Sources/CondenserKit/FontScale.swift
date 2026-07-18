import Foundation

/// 阅读字号预设档位（设置页滑块选择，非自由调整）。
/// rawValue 用于持久化（AppStorage）；具体到字体的映射（DynamicTypeSize）在 app 层。
public enum FontScale: String, CaseIterable, Sendable, Equatable {
    case small
    case normal
    case large
    case xLarge

    public static let `default`: FontScale = .normal

    /// 存储值解析：未知/损坏的值回退默认档
    public init(storedValue: String) {
        self = FontScale(rawValue: storedValue) ?? .default
    }

    /// slider index 解析：越界钳制到边界档位
    public init(sliderIndex: Int) {
        let all = FontScale.allCases
        let clamped = min(max(sliderIndex, 0), all.count - 1)
        self = all[clamped]
    }

    public var sliderIndex: Int {
        FontScale.allCases.firstIndex(of: self)!
    }

    public var displayName: String {
        switch self {
        case .small: "小"
        case .normal: "正常"
        case .large: "略大"
        case .xLarge: "大"
        }
    }
}
