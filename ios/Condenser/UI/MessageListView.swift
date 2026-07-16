import SwiftUI
import CondenserKit

/// TimelineStore 驱动的消息列表核心：无限滚动 + 下拉刷新 + 滚动即已读 + 详情 sheet。
/// 主 timeline 传 poller 时渲染新消息胶囊（点击刷新 + 滚回顶）；
/// 频道 timeline 不传 poller，纯列表复用。
struct MessageListView: View {
    let store: TimelineStore
    var poller: NewContentPoller?
    var emptyLabel = "暂无内容"

    @Environment(ReaderSession.self) private var reader
    @State private var selectedMessage: DisplayMessage?

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                Color.clear.frame(height: 1).id("timeline-top")
                listBody
            }
            .refreshable { await refresh() }
            .overlay(alignment: .top) {
                if let poller, poller.count > 0 {
                    newContentCapsule(count: poller.count, proxy: proxy)
                }
            }
        }
        .sheet(item: $selectedMessage) { message in
            MessageDetailSheet(
                message: currentVersion(of: message),
                onToggleSaved: { toggleSaved(message) })
        }
        .task(id: ObjectIdentifier(store)) {
            await store.loadInitial()
        }
    }

    private var listBody: some View {
        LazyVStack(spacing: 0, pinnedViews: []) {
            if store.isLoading && store.items.isEmpty {
                skeleton
            } else if store.items.isEmpty {
                emptyState
            }
            ForEach(Array(store.items.enumerated()), id: \.element.unitKey) { index, message in
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
                    if index >= store.items.count - 5 {
                        Task { await store.loadMore() }
                    }
                }
            }
            if store.isLoadingMore {
                ProgressView().padding(.vertical, 16)
            }
            if let error = store.error {
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
            Text(emptyLabel)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 120)
    }

    private func newContentCapsule(count: Int, proxy: ScrollViewProxy) -> some View {
        Button {
            Task {
                await refresh()
                withAnimation { proxy.scrollTo("timeline-top", anchor: .top) }
            }
        } label: {
            Label("\(count) 条新消息", systemImage: "arrow.up")
                .font(.footnote.weight(.medium))
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(.tint, in: Capsule())
                .foregroundStyle(.white)
                .shadow(radius: 4, y: 2)
        }
        .padding(.top, 8)
    }

    private func refresh() async {
        await store.refresh()
        poller?.reset()
    }

    /// sheet 打开期间收藏态变化要跟随 store（乐观更新可见）
    private func currentVersion(of message: DisplayMessage) -> DisplayMessage {
        store.items.first { $0.unitKey == message.unitKey } ?? message
    }

    private func toggleSaved(_ message: DisplayMessage) {
        Task { await store.toggleSaved(message) }
    }
}
