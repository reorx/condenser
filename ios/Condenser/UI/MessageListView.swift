import SwiftUI
import CondenserKit

/// TimelineStore 驱动的多信源列表核心：无限滚动 + 下拉刷新 + 滚动即已读 + 详情 sheet。
/// 按 item.source 分发卡片（MessageCard / HnCard / XCard / RssCard）。刷新只有两条路径：用户下拉，
/// 以及冷启动 / 长时间后台回前台的静默自动更新（传了 checker 的主 timeline 才有），
/// 后者用灰色不可点 toast 事后告知条数。前台阅读期间不做任何轮询、不弹可点提示。
/// 频道/feed timeline 不传 checker，纯列表复用。
struct MessageListView: View {
    let store: TimelineStore
    var checker: NewContentChecker?
    var emptyLabel = "暂无内容"

    @Environment(ReaderSession.self) private var reader
    @Environment(\.scenePhase) private var scenePhase
    @State private var selectedItem: TimelineItem?
    @State private var safariItem: SafariItem?
    @State private var viewerItem: ImageViewerItem?
    @State private var pullOlderModel = PullToLoadOlderModel()
    @State private var isUserDragging = false
    /// 滚过即已读的武装闸：用户在本视图滚动过才开始判读，刷新时解除
    @State private var scrollReadModel = ScrollReadModel()
    /// 灰 toast 的计数；nil = 不显示
    @State private var toastCount: Int?
    /// 冷启动 toast 只在 app 本次运行的首次加载弹（信源/未读切换重建 store 时不弹）
    @State private var didHandleLaunch = false
    @State private var foregroundPolicy = ForegroundRefreshPolicy()

    /// 底部上拉触发 fetch-older 只对单频道视图开放（后端接口按频道拉取，TG 专属）
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
                // 武装只认真实位移（interacting / 惯性减速）：手指刚按下（tracking）
                // 与程序化回顶（animating）都不算滚动，否则一次点击就把整个首屏判读了
                if newPhase == .interacting || newPhase == .decelerating {
                    scrollReadModel.noteUserScroll()
                }
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
                if let count = toastCount {
                    newContentToast(count: count)
                }
            }
            .onChange(of: scenePhase) { _, phase in
                guard checker != nil else { return }
                if phase == .active {
                    Task { await resumeFromBackground(proxy) }
                } else {
                    foregroundPolicy.noteBackground()
                }
            }
        }
        // 卡片正文/预览卡里的链接点击 → X 链接进 X app，其余 in-app Safari
        .externalLinks(safari: $safariItem)
        .sheet(item: $selectedItem) { item in
            detailSheet(currentVersion(of: item))
        }
        .sheet(item: $safariItem) { item in
            SafariView(url: item.url)
                .ignoresSafeArea()
        }
        .fullScreenCover(item: $viewerItem) { item in
            ImageViewerScreen(item: item)
        }
        .task(id: ObjectIdentifier(store)) {
            // 换 store（切信源 / 未读开关）也是整列表替换，同样要解除武装，
            // 否则上一个列表滚出来的 armed 会把新首屏瞬间判读
            scrollReadModel.reset()
            let newCount = await store.loadInitial()
            // 冷启动：快照先渲染、网络静默换新，有新内容只弹灰 toast 事后告知
            if checker != nil, !didHandleLaunch, newCount > 0 {
                toastCount = newCount
            }
            didHandleLaunch = true
        }
    }

    private var listBody: some View {
        LazyVStack(spacing: 0, pinnedViews: []) {
            if store.isLoading && store.items.isEmpty {
                skeleton
            } else if store.items.isEmpty {
                emptyState
            }
            ForEach(Array(store.items.enumerated()), id: \.element.key) { index, item in
                VStack(spacing: 0) {
                    card(item)
                        .onTapGesture { selectedItem = item }
                    Divider().padding(.leading, 16)
                }
                // 判读线是视口下边界：卡片下边界进到视口里就算看过。
                // armed 必须参与取值而不是只在 action 里判断——首屏卡片一渲染就满足
                // 判读线，Bool 一直是 true，onGeometryChange 便再也不会回调；
                // 把 armed 揉进取值，用户第一次滚动（滚动本身就在重算几何）时
                // false→true 才有这一跳，「首屏看过的、滚一下就算读过」才成立。
                .onGeometryChange(for: Bool.self) { geo in
                    scrollReadModel.armed && ScrollReadModel.hasPassedReadLine(
                        frameMaxY: geo.frame(in: .scrollView).maxY,
                        // 拿不到视口高度就退化成旧规则（移出视口上方），
                        // 绝不能用 .infinity —— 那会把整屏瞬间判成已读
                        viewportHeight: geo.bounds(of: .scrollView)?.height ?? 0)
                } action: { passedReadLine in
                    if passedReadLine, !item.isRead {
                        reader.readReporter.enqueue(item.key)
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

    /// 按 source 分发卡片；未知信源（升级前的旧 app 撞上新后端）静默跳过
    @ViewBuilder
    private func card(_ item: TimelineItem) -> some View {
        if let message = item.telegram {
            MessageCard(
                item: item, message: message,
                onToggleSaved: { toggleSaved(item) },
                onOpenPhoto: { openViewer(for: message, at: $0) })
        } else if let story = item.hn {
            HnCard(item: item, story: story, onToggleSaved: { toggleSaved(item) })
        } else if let tweet = item.x {
            XCard(
                item: item, tweet: tweet,
                onToggleSaved: { toggleSaved(item) },
                onFeedback: { setFeedback(item, $0) },
                onReason: { setReason(item, $0) },
                onOpenPhoto: { openViewer(for: tweet, at: $0) })
        } else if let entry = item.rss {
            RssCard(item: item, entry: entry, onToggleSaved: { toggleSaved(item) })
        }
    }

    @ViewBuilder
    private func detailSheet(_ item: TimelineItem) -> some View {
        if let message = item.telegram {
            MessageDetailSheet(
                item: item, message: message,
                onToggleSaved: { toggleSaved(item) })
        } else if let story = item.hn {
            HnDetailSheet(item: item, story: story, onToggleSaved: { toggleSaved(item) })
        } else if let tweet = item.x {
            XDetailSheet(
                item: item, tweet: tweet,
                onToggleSaved: { toggleSaved(item) },
                onFeedback: { setFeedback(item, $0) },
                onReason: { setReason(item, $0) })
        } else if let entry = item.rss {
            RssDetailSheet(item: item, entry: entry, onToggleSaved: { toggleSaved(item) })
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

    /// 灰色不可点提示：内容已自动更新，仅告知；一会自动消失，点一下也消失
    private func newContentToast(count: Int) -> some View {
        Text("\(count) 条新消息")
            .font(.footnote.weight(.medium))
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Color(.systemGray5), in: Capsule())
            .foregroundStyle(.secondary)
            .shadow(radius: 4, y: 2)
            .padding(.top, 8)
            .onTapGesture { toastCount = nil }
            .task {
                try? await Task.sleep(for: .seconds(4))
                toastCount = nil
            }
    }

    /// 回前台：后台够久且确有新内容才回顶 + 静默刷新 + 灰 toast；
    /// 否则保持阅读位置分毫不动
    private func resumeFromBackground(_ proxy: ScrollViewProxy) async {
        guard let checker, foregroundPolicy.shouldRefreshOnForeground() else { return }
        let count = await checker.check()
        guard count > 0 else { return }
        // 必须先瞬时回顶再刷新：refresh 替换 items 时若滚动位置还很深，
        // 新首屏的卡片会落在视口上方（maxY < 0）被 scroll-to-read 误判为已读
        proxy.scrollTo("timeline-top", anchor: .top)
        await refresh()
        toastCount = count
    }

    private func refresh() async {
        // 先冲刷已读队列（debounce 可能还没发出去），未读视图重载才会真正剔除已读项
        await reader.readReporter.flushNow()
        // 列表要被整体替换：解除武装，新首屏得等用户再滚一次才判读
        // （回前台的静默刷新也走这里）
        scrollReadModel.reset()
        await store.refresh()
    }

    private func openViewer(for message: DisplayMessage, at index: Int) {
        let photos = message.mediaItems.filter { $0.mediaType == "photo" && $0.hasMedia }
        guard !photos.isEmpty else { return }
        viewerItem = ImageViewerItem(
            channelID: message.channelID, photos: photos,
            startIndex: min(index, photos.count - 1))
    }

    /// 卡片上点的是「画出来的第 index 张」（含视频），查看器只装图片——
    /// 两套下标的对齐由 Kit 的 photoIndex(forDisplayed:) 独家负责
    private func openViewer(for tweet: XTweet, at index: Int) {
        guard let start = tweet.photoIndex(forDisplayed: index) else { return }
        viewerItem = ImageViewerItem(
            urls: tweet.photos.compactMap(\.thumbnailURL), startIndex: start)
    }

    /// sheet 打开期间收藏态变化要跟随 store（乐观更新可见）
    private func currentVersion(of item: TimelineItem) -> TimelineItem {
        store.items.first { $0.key == item.key } ?? item
    }

    private func toggleSaved(_ item: TimelineItem) {
        Task { await store.toggleSaved(item) }
    }

    private func setFeedback(_ item: TimelineItem, _ verdict: ItemFeedback) {
        Task { await store.setFeedback(item, verdict) }
    }

    private func setReason(_ item: TimelineItem, _ reason: ItemFeedbackReason) {
        Task { await store.setReason(item, reason) }
    }
}
