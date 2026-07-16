import SwiftUI
import CondenserKit

/// Timeline 主屏：无限滚动 + 下拉刷新 + 滚动即已读 + 新消息胶囊 + 未读过滤。
struct TimelineScreen: View {
    @Environment(ReaderSession.self) private var reader
    @Environment(AuthSession.self) private var auth
    @Environment(\.scenePhase) private var scenePhase

    @State private var selectedMessage: DisplayMessage?

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                Color.clear.frame(height: 1).id("timeline-top")
                timelineBody
            }
            .refreshable { await refresh() }
            .overlay(alignment: .top) {
                if reader.poller.count > 0 {
                    newContentCapsule(proxy: proxy)
                }
            }
        }
        .navigationTitle(reader.unreadOnly ? "未读" : "Timeline")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { toolbarContent }
        .sheet(item: $selectedMessage) { message in
            MessageDetailSheet(
                message: currentVersion(of: message),
                onToggleSaved: { toggleSaved(message) })
        }
        .task(id: ObjectIdentifier(reader.timeline)) {
            await reader.timeline.loadInitial()
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

    private var timelineBody: some View {
        LazyVStack(spacing: 0, pinnedViews: []) {
            if reader.timeline.isLoading && reader.timeline.items.isEmpty {
                skeleton
            } else if reader.timeline.items.isEmpty {
                emptyState
            }
            ForEach(Array(reader.timeline.items.enumerated()), id: \.element.unitKey) { index, message in
                VStack(spacing: 0) {
                    MessageCard(message: message, onToggleSaved: { toggleSaved(message) })
                        .onTapGesture { selectedMessage = message }
                    Divider().padding(.leading, 16)
                }
                .onGeometryChange(for: Bool.self) { geo in
                    geo.frame(in: .scrollView).maxY < 0
                } action: { passedTop in
                    if passedTop, message.isRead != true {
                        reader.readReporter.enqueue(message.ref)
                    }
                }
                .onAppear {
                    if index >= reader.timeline.items.count - 5 {
                        Task { await reader.timeline.loadMore() }
                    }
                }
            }
            if reader.timeline.isLoadingMore {
                ProgressView().padding(.vertical, 16)
            }
            if let error = reader.timeline.error {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding(.vertical, 12)
            }
        }
    }

    private var skeleton: some View {
        ForEach(0..<6, id: \.self) { _ in
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    Circle().fill(Color(.secondarySystemBackground)).frame(width: 36, height: 36)
                    RoundedRectangle(cornerRadius: 4)
                        .fill(Color(.secondarySystemBackground))
                        .frame(width: 120, height: 12)
                }
                RoundedRectangle(cornerRadius: 4)
                    .fill(Color(.secondarySystemBackground))
                    .frame(maxWidth: .infinity)
                    .frame(height: 60)
            }
            .padding(16)
        }
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "tray")
                .font(.largeTitle)
                .foregroundStyle(.tertiary)
            Text(reader.unreadOnly ? "没有未读消息" : "暂无内容")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 120)
    }

    private func newContentCapsule(proxy: ScrollViewProxy) -> some View {
        Button {
            Task {
                await refresh()
                withAnimation { proxy.scrollTo("timeline-top", anchor: .top) }
            }
        } label: {
            Label("\(reader.poller.count) 条新消息", systemImage: "arrow.up")
                .font(.footnote.weight(.medium))
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(.tint, in: Capsule())
                .foregroundStyle(.white)
                .shadow(radius: 4, y: 2)
        }
        .padding(.top, 8)
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Menu {
                Button("登出", role: .destructive) {
                    Task { await reader.readReporter.flushNow() }
                    auth.signOut()
                }
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

    private func refresh() async {
        await reader.timeline.refresh()
        reader.poller.reset()
    }

    /// sheet 打开期间收藏态变化要跟随 store（乐观更新可见）
    private func currentVersion(of message: DisplayMessage) -> DisplayMessage {
        reader.timeline.items.first { $0.unitKey == message.unitKey } ?? message
    }

    private func toggleSaved(_ message: DisplayMessage) {
        Task { await reader.timeline.toggleSaved(message) }
    }
}
