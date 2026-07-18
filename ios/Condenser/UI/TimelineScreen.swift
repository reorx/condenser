import SwiftUI
import CondenserKit

/// Timeline 主屏（tab 1）：MessageListView + 新消息胶囊 + 未读过滤（默认只看未读）；
/// 负责 poller 生命周期与 scenePhase 时的已读冲刷。设置入口在底部 tab 栏。
struct TimelineScreen: View {
    @Environment(ReaderSession.self) private var reader
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        MessageListView(
            store: reader.timeline,
            poller: reader.poller,
            emptyLabel: reader.unreadOnly ? "没有未读消息" : "暂无内容")
            .navigationTitle(reader.unreadOnly ? "未读" : "Timeline")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarContent }
            .task(id: ObjectIdentifier(reader.timeline)) {
                reader.poller.start()
            }
            .task { await reader.loadSubscriptions() }
            .onChange(of: scenePhase) { _, phase in
                switch phase {
                case .active:
                    reader.poller.start()
                default:
                    reader.poller.stop()
                    Task { await reader.readReporter.flushNow() }
                }
            }
            .onDisappear { reader.poller.stop() }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        // eye.slash = 已读被隐藏（未读模式）；eye = 全部可见
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                reader.setUnreadOnly(!reader.unreadOnly)
            } label: {
                Image(systemName: reader.unreadOnly ? "eye.slash" : "eye")
            }
        }
    }
}
