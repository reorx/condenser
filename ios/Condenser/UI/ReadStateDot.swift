import SwiftUI
import CondenserKit

/// 卡片时间行前的三态阅读指示点：
/// 蓝 = 未读，绿 = 已判定该读、正在同步（还没拿到服务器确认），无点 = 已读。
///
/// 顺序要紧：入队那一刻 key 同时进 readKeys（乐观已读）和 unsyncedKeys，
/// 先查 unsyncedKeys 才看得见「同步中」；否则乐观已读直接把点熄了，
/// 同步失败在界面上完全不可见——而那正是最该看见的状态。
/// 收藏列表（showsUnread=false）不画任何点：records 不携带已读态。
struct ReadStateDot: View {
    let item: TimelineItem
    var showsUnread = true

    @Environment(ReaderSession.self) private var reader

    var body: some View {
        if showsUnread {
            if reader.readReporter.unsyncedKeys.contains(item.key) {
                dot(.green)
            } else if !item.isRead, !reader.readReporter.readKeys.contains(item.key) {
                dot(.tint)
            }
        }
    }

    private func dot(_ style: some ShapeStyle) -> some View {
        Circle().fill(style).frame(width: 6, height: 6)
    }
}
