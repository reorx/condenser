import SwiftUI
import CondenserKit

/// Timeline 主屏（tab 1）：MessageListView + 新消息胶囊 + 未读过滤（默认只看未读）
/// + 信源切换（顶部左侧 Menu，选项 = All + 已添加的信源，来自 GET /api/sources）；
/// 负责 poller 生命周期与 scenePhase 时的已读冲刷。设置入口在底部 tab 栏。
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
            .task(id: ObjectIdentifier(reader.timeline)) {
                reader.poller.start()
            }
            .task { await reader.loadSources() }
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
