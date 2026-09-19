import Foundation

/// 详情抽屉「从左边缘右滑关闭」的判定规则（手势本身在 app 侧的 `EdgeSwipeDismiss`）。
/// 抽成纯函数是因为它挂在每一个详情抽屉上：门槛改松一点，竖着滚长文就会误关。
public enum EdgeSwipe {
    /// 手势响应带的宽度，参照系统返回手势的响应区
    public static let bandWidth: Double = 24
    /// 手势起算的最小位移
    public static let minimumDistance: Double = 20
    /// 横向位移超过这个值才算「明确向右」
    public static let dismissDistance: Double = 60

    /// 松手时的位移算不算一次关闭：明确向右、且横向压过纵向——竖着滚到边缘不该关抽屉
    public static func shouldDismiss(dx: Double, dy: Double) -> Bool {
        dx > dismissDistance && dx > abs(dy)
    }
}
