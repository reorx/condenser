import SwiftUI
import CondenserKit

/// TimelineStore 驱动的多信源列表核心：无限滚动 + 下拉刷新 + 滚动即已读 + 详情 sheet。
/// 按 item.source 分发卡片（MessageCard / HnCard / XCard / RssCard）。
///
/// **阅读现场（plan 2026-09-07）**：滚动锚点（`scrollPosition(id:)` 报的顶部卡片 key）与
/// 打开的详情 sheet 按 `store.scopeKey` 写进 `ReadingState`，store 首次加载完就照它恢复；
/// 主 timeline 的启动加载走 `loadInitial(preferSnapshot:)`——快照即现场，不打网络替换。
/// 内容刷新只有两条路径：用户下拉，以及点上方的蓝色胶囊「↑ N 条新内容」。胶囊由
/// `NewContentChecker`（`/timeline/new/count`）在启动恢复现场后与回前台时各问一次决定
/// 弹不弹；它只告知，不回顶、不刷新、不动列表，右侧的 ✕ 只把它收掉。
/// 频道/feed timeline 不传 checker，纯列表复用（现场恢复照样有）。
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
    /// `scrollPosition(id:)` 的绑定：视口顶部那张卡片的 key（或顶部哨兵）。
    /// 读它 = 记现场；写它 = 回顶 / 恢复现场
    @State private var scrolledID: String?
    /// 蓝色胶囊的计数；nil = 不显示
    @State private var pillCount: Int?
    /// 用户按 ✕ 时的计数：再次检查若还是这个数就不再弹，免得成了赖着不走的提醒
    @State private var dismissedCount = 0
    /// 启动路径只走一次：首个 store 用快照当现场；之后切信源重建的 store 走快照→网络替换
    @State private var didHandleLaunch = false
    @State private var foregroundPolicy = ForegroundRefreshPolicy()

    private let topSentinel = "timeline-top"

    /// 底部上拉触发 fetch-older 只对单频道视图开放（后端接口按频道拉取，TG 专属）
    private var supportsFetchOlder: Bool { store.channelID != nil }

    var body: some View {
        ScrollView {
            listBody
                .scrollTargetLayout()
                .readingColumn()
        }
        .scrollPosition(id: $scrolledID, anchor: .top)
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
            if let count = pillCount {
                newContentPill(count: count)
            }
        }
        .animation(.snappy, value: pillCount == nil)
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                Task { await resumeFromBackground() }
            } else {
                foregroundPolicy.noteBackground()
                // 退后台即落盘现场：本地乐观已读先写进条目，快照里才不会满是过期的蓝点
                store.markLocallyRead(reader.readReporter.readKeys)
                store.persistSnapshot()
            }
        }
        .onChange(of: scrolledID) { _, id in
            guard let id, !store.items.isEmpty else { return }
            reader.readingState.rememberList(store.scopeKey, top: .some(id == topSentinel ? nil : id))
        }
        .onChange(of: selectedItem?.key) { _, key in
            reader.readingState.rememberList(store.scopeKey, open: .some(key))
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
            let isLaunch = checker != nil && !didHandleLaunch
            didHandleLaunch = true
            let onSnapshot = await store.loadInitial(preferSnapshot: isLaunch)
            restoreListState()
            // 停在快照上 = 内容是上次离开时的；问一句有多少新的，弹胶囊告知，不动列表
            if onSnapshot {
                await checkForNewContent()
            }
        }
    }

    private var listBody: some View {
        LazyVStack(spacing: 0, pinnedViews: []) {
            // 顶部哨兵：scrollPosition 在顶部时报它；回顶 = 把绑定设成它
            Color.clear.frame(height: 1).id(topSentinel)
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

    /// 蓝色可点胶囊：主体「↑ N 条新内容」点了才回顶 + 刷新（蓝 = 有动作，和灰色的
    /// 「只是告知」区分开）；右侧 ✕ 只把胶囊收掉，列表分毫不动。不自动消失——
    /// 它是等着被操作的提示，不是一闪而过的通知。
    private func newContentPill(count: Int) -> some View {
        HStack(spacing: 0) {
            Button {
                Task { await jumpToNewest() }
            } label: {
                Label("\(count) 条新内容", systemImage: "arrow.up")
                    .font(.footnote.weight(.semibold))
                    .padding(.leading, 14)
                    .padding(.trailing, 10)
                    .padding(.vertical, 9)
            }
            .accessibilityHint("回到顶部并刷新")
            Rectangle()
                .fill(.white.opacity(0.45))
                .frame(width: 1, height: 16)
            Button {
                dismissedCount = count
                pillCount = nil
            } label: {
                Image(systemName: "xmark")
                    .font(.footnote.weight(.bold))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 9)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel("忽略")
        }
        .buttonStyle(.plain)
        .foregroundStyle(.white)
        .background(Color.blue, in: Capsule())
        .shadow(color: .black.opacity(0.18), radius: 6, y: 3)
        .padding(.top, 8)
        .transition(.move(edge: .top).combined(with: .opacity))
    }

    /// store 首次加载完：滚回上次的顶部卡片、重开上次开着的抽屉——两样都只在
    /// 那条还在列表里时做，找不到就从顶部开始（快照截断 / 单 feed 视图没有快照）
    private func restoreListState() {
        guard let saved = reader.readingState.list(store.scopeKey) else { return }
        if let top = saved.topItemKey, store.items.contains(where: { $0.key == top }) {
            scrolledID = top
        }
        if let open = saved.openItemKey, let item = store.items.first(where: { $0.key == open }) {
            selectedItem = item
        }
    }

    /// 问一次有多少新内容，决定胶囊弹不弹：0 收起；用户 ✕ 掉过的那个数不再弹
    private func checkForNewContent() async {
        guard let checker else { return }
        let count = await checker.check()
        if count > 0, count != dismissedCount {
            pillCount = count
        } else if count == 0 {
            pillCount = nil
        }
    }

    /// 回前台：后台够久才去问；结果只影响胶囊，阅读位置分毫不动
    private func resumeFromBackground() async {
        guard checker != nil, foregroundPolicy.shouldRefreshOnForeground() else { return }
        await checkForNewContent()
    }

    /// 点胶囊主体：先瞬时回顶再刷新——refresh 替换 items 时若滚动位置还很深，
    /// 新首屏的卡片会落在视口上方（maxY < 0）被 scroll-to-read 误判为已读
    private func jumpToNewest() async {
        pillCount = nil
        scrolledID = topSentinel
        await refresh()
    }

    private func refresh() async {
        // 先冲刷已读队列（debounce 可能还没发出去），未读视图重载才会真正剔除已读项
        await reader.readReporter.flushNow()
        // 列表要被整体替换：解除武装，新首屏得等用户再滚一次才判读
        scrollReadModel.reset()
        await store.refresh()
        // 刷新后内容就是最新的：胶囊没有存在的理由，✕ 的记忆也清零
        pillCount = nil
        dismissedCount = 0
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
