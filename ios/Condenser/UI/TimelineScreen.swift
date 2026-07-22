import SwiftUI
import CondenserKit

/// Timeline 主屏（tab 1）：MessageListView + 未读过滤（默认只看未读）
/// + 信源切换（顶部左侧 Menu，选项 = All + 已添加的信源，来自 GET /api/sources）；
/// poller 生命周期与新消息提示都在 MessageListView 内；这里只负责
/// scenePhase 离开前台时的已读冲刷。设置入口在底部 tab 栏。
struct TimelineScreen: View {
    @Environment(ReaderSession.self) private var reader
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        MessageListView(
            store: reader.timeline,
            poller: reader.poller,
            emptyLabel: reader.unreadOnly ? "没有未读消息" : "暂无内容")
            .navigationTitle(navTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarContent }
            .task { await reader.loadSources() }
            .onChange(of: scenePhase) { _, phase in
                if phase != .active {
                    Task { await reader.readReporter.flushNow() }
                }
            }
    }

    private var navTitle: String {
        let base = reader.selectedSource.map { SourceID.label($0) } ?? "Timeline"
        return reader.unreadOnly ? "\(base) (unread)" : base
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        // 信源切换：All + 已添加的信源（不硬编码；未加载到 sources 前只有 All）
        ToolbarItem(placement: .topBarLeading) {
            Menu {
                Picker("信源", selection: sourceSelection) {
                    Text("All").tag(String?.none)
                    ForEach(reader.sources) { group in
                        Text(SourceID.label(group.source)).tag(String?.some(group.source))
                    }
                }
            } label: {
                Image(systemName: "line.3.horizontal.decrease.circle")
                    .symbolVariant(reader.selectedSource == nil ? .none : .fill)
            }
        }
        // eye.slash = 已读被隐藏（未读模式）；eye = 全部可见
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                reader.setUnreadOnly(!reader.unreadOnly)
            } label: {
                Image(systemName: reader.unreadOnly ? "eye.slash" : "eye")
            }
        }
    }

    private var sourceSelection: Binding<String?> {
        Binding(
            get: { reader.selectedSource },
            set: { reader.setSource($0) })
    }
}
