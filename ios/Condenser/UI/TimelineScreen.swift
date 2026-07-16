import SwiftUI
import CondenserKit

/// Timeline 主屏（tab 1）：MessageListView + 新消息胶囊 + 未读过滤 + 设置入口；
/// 负责 poller 生命周期与 scenePhase 时的已读冲刷。
struct TimelineScreen: View {
    @Environment(ReaderSession.self) private var reader
    @Environment(\.scenePhase) private var scenePhase

    @State private var showSettings = false

    var body: some View {
        MessageListView(
            store: reader.timeline,
            poller: reader.poller,
            emptyLabel: reader.unreadOnly ? "没有未读消息" : "暂无内容")
            .navigationTitle(reader.unreadOnly ? "未读" : "Timeline")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarContent }
            .sheet(isPresented: $showSettings) {
                SettingsScreen()
            }
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
        ToolbarItem(placement: .topBarLeading) {
            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape")
            }
        }
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                reader.setUnreadOnly(!reader.unreadOnly)
            } label: {
                Image(systemName: reader.unreadOnly ? "envelope.badge.fill" : "envelope.badge")
            }
        }
    }
}
