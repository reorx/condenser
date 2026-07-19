import SwiftUI
import CondenserKit

/// TimelineStore 驱动的消息列表核心：无限滚动 + 下拉刷新 + 滚动即已读 + 详情 sheet。
/// 主 timeline 传 poller 时渲染新消息胶囊（点击瞬时回顶 + 刷新）；
/// 频道 timeline 不传 poller，纯列表复用。
struct MessageListView: View {
    let store: TimelineStore
    var poller: NewContentPoller?
    var emptyLabel = "暂无内容"

    @Environment(ReaderSession.self) private var reader
    @State private var selectedMessage: DisplayMessage?
    @State private var safariItem: SafariItem?
    @State private var viewerItem: ImageViewerItem?
    @State private var pullOlderModel = PullToLoadOlderModel()
    @State private var isUserDragging = false

    /// 底部上拉触发 fetch-older 只对单频道视图开放（后端接口按频道拉取）
    private var supportsFetchOlder: Bool { store.channelID != nil }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                Color.clear.frame(height: 1).id("timeline-top")
                listBody
            }
            .readingFontScale()
            .autoHideBars()
            .onScrollPhaseChange { _, newPhase in
                isUserDragging = newPhase == .tracking || newPhase == .interacting
            }
            .onScrollGeometryChange(for: CGFloat.self) { geo in
                PullToLoadOlderModel.bottomOverscroll(
                    contentOffsetY: geo.contentOffset.y,
                    contentHeight: geo.contentSize.height,
                    containerHeight: geo.containerSize.height,
                    topInset: geo.contentInsets.top,
                    bottomInset: geo.contentInsets.bottom)
            } action: { _, overscroll in
                // 只做模型判定 + 发起网络加载，不改任何布局状态，
                // 不会踩 AutoHideBars 的 insets 自激振荡陷阱
                guard supportsFetchOlder, !store.hasMore, !store.olderExhausted,
                      !store.items.isEmpty else { return }
                if pullOlderModel.handleOverscroll(overscroll, isDragging: isUserDragging) {
                    Task { await store.fetchOlderFromServer() }
                }
            }
            .refreshable { await refresh() }
            .overlay(alignment: .top) {
                if let poller, poller.count > 0 {
                    newContentCapsule(count: poller.count, proxy: proxy)
                }
            }
        }
        // 卡片正文/预览卡里的链接点击 → in-app Safari
        .environment(\.openURL, OpenURLAction { url in
            safariItem = SafariItem(url: url)
            return .handled
        })
        .sheet(item: $selectedMessage) { message in
            MessageDetailSheet(
                message: currentVersion(of: message),
                onToggleSaved: { toggleSaved(message) })
        }
        .sheet(item: $safariItem) { item in
            SafariView(url: item.url)
                .ignoresSafeArea()
        }
        .fullScreenCover(item: $viewerItem) { item in
            ImageViewerScreen(item: item)
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
                    MessageCard(
                        message: message,
                        onToggleSaved: { toggleSaved(message) },
                        onOpenPhoto: { openViewer(for: message, at: $0) })
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
            if supportsFetchOlder, !store.hasMore, !store.items.isEmpty {
                fetchOlderFooter
            }
        }
    }

    /// 本地历史到底后的底部提示：可上拉获取 / 拉取中 / Telegram 上也没有更早的了
    private var fetchOlderFooter: some View {
        Group {
            if store.isFetchingOlder {
                HStack(spacing: 8) {
                    ProgressView()
                    Text("正在获取更早消息…")
                }
            } else if store.olderExhausted {
                Text("没有更早的消息了")
            } else {
                Label("继续上拉获取更早消息", systemImage: "arrow.up")
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 20)
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
            // 必须先瞬时回顶再刷新：refresh 替换 items 时若滚动位置还很深，
            // 新首屏的卡片会落在视口上方（maxY < 0）被 scroll-to-read 误判为已读
            proxy.scrollTo("timeline-top", anchor: .top)
            Task { await refresh() }
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
        // 先冲刷已读队列（debounce 可能还没发出去），未读视图重载才会真正剔除已读项
        await reader.readReporter.flushNow()
        await store.refresh()
        poller?.reset()
    }

    private func openViewer(for message: DisplayMessage, at index: Int) {
        let photos = message.mediaItems.filter { $0.mediaType == "photo" && $0.hasMedia }
        guard !photos.isEmpty else { return }
        viewerItem = ImageViewerItem(
            channelID: message.channelID, photos: photos,
            startIndex: min(index, photos.count - 1))
    }

    /// sheet 打开期间收藏态变化要跟随 store（乐观更新可见）
    private func currentVersion(of message: DisplayMessage) -> DisplayMessage {
        store.items.first { $0.unitKey == message.unitKey } ?? message
    }

    private func toggleSaved(_ message: DisplayMessage) {
        Task { await store.toggleSaved(message) }
    }
}
