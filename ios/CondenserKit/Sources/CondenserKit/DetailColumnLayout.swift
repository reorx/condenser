import Foundation

/// Mac 上详情不弹 sheet，而是在列表右侧展开一栏（2026-09-04）。这里只放宽度规则，
/// 布局本身在 app 层的 `DetailPresentation`。
///
/// 为什么不是 sheet：Catalyst 的 `.page` sheet 比窗口还宽时，macOS 会把整个窗口
/// 挪开来给它腾位置——窗口贴着屏幕左边时一开详情就被顶着往右跑。栏在窗口内展开，
/// 窗口原地不动。
public enum DetailColumnLayout {
    /// 窄于这个宽度读长文会变成一行十几个字
    public static let minWidth: Double = 360
    /// 宽过这个宽度一行太长，和 `ReadingColumn` 限宽同一取舍
    public static let maxWidth: Double = 520
    /// 列表至少留这么宽，否则卡片挤成一列碎字
    public static let minListWidth: Double = 320
    /// 窗口宽度的这个比例给详情
    public static let fraction: Double = 0.45

    /// 给定内容区宽度，详情栏该多宽。两栏并排放不下时返回整个宽度（盖满列表）。
    public static func columnWidth(containerWidth: Double) -> Double {
        let ideal = min(max((containerWidth * fraction).rounded(), minWidth), maxWidth)
        return containerWidth - ideal >= minListWidth ? ideal : containerWidth
    }
}
