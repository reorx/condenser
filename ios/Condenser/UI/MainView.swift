import SwiftUI
import CondenserKit

/// 登录后的主界面：四 tab（Timeline / 订阅 / 收藏 / 设置），各自持有独立 NavigationStack。
struct MainView: View {
    enum MainTab: Hashable {
        case timeline, subscriptions, saved, settings
    }

    @Environment(AuthSession.self) private var auth
    @State private var reader: ReaderSession?
    @State private var selectedTab: MainTab = .timeline
    @State private var subscriptionsPath = NavigationPath()
    /// tab/subs/<source> 走查用：订阅列表进来就滚到该信源分组（只有 DEBUG 路由会设它）
    @State private var subsScrollTarget: String?
    #if DEBUG
    @State private var debugDetail: TimelineItem?
    @State private var debugViewer: ImageViewerItem?
    @State private var debugForward: DebugForwardRoute?
    #endif

    var body: some View {
        Group {
            if let reader {
                tabs(reader)
                    .environment(reader)
            } else {
                ProgressView()
            }
        }
        .onAppear {
            guard reader == nil, let server = auth.serverURL, let token = auth.token else { return }
            reader = ReaderSession(server: server, token: token) { [weak auth] in
                auth?.handleUnauthorized()
            }
        }
    }

    private func tabs(_ reader: ReaderSession) -> some View {
        TabView(selection: $selectedTab) {
            Tab("Timeline", systemImage: "list.bullet.rectangle", value: MainTab.timeline) {
                NavigationStack {
                    TimelineScreen()
                }
            }
            Tab("订阅", systemImage: "square.stack", value: MainTab.subscriptions) {
                NavigationStack(path: $subscriptionsPath) {
                    SubscriptionsScreen(scrollToSource: subsScrollTarget)
                }
            }
            Tab("收藏", systemImage: "star", value: MainTab.saved) {
                NavigationStack {
                    SavedScreen()
                }
            }
            Tab("设置", systemImage: "gearshape", value: MainTab.settings) {
                NavigationStack {
                    SettingsScreen()
                }
            }
        }
        #if DEBUG
        .onOpenURL { handleDebugURL($0, reader: reader) }
        .sheet(item: $debugDetail) { item in
            if let message = item.telegram {
                MessageDetailSheet(item: item, message: message, onToggleSaved: {})
            } else if let story = item.hn {
                HnDetailSheet(item: item, story: story, onToggleSaved: {})
            } else if let tweet = item.x {
                XDetailSheet(item: item, tweet: tweet, onToggleSaved: {}, onFeedback: { _ in })
            }
        }
        .fullScreenCover(item: $debugViewer) { item in
            ImageViewerScreen(item: item)
        }
        .sheet(item: $debugForward) { route in
            ForwardDialog(
                channelID: route.channelID, messageID: route.messageID,
                debugAutoComment: route.autoComment)
        }
        .task { await applyDebugRouteIfNeeded(reader) }
        #endif
    }

    #if DEBUG
    /// CLI 驱动的界面走查：启动时带 SIMCTL_CHILD_CONDENSER_DEBUG_ROUTE=<route>
    /// （openurl 会弹系统确认框、模拟器窗口无法点击时的兜底）。
    /// 路由等 timeline 首屏加载完再应用，detail/viewer 才找得到消息。
    private func applyDebugRouteIfNeeded(_ reader: ReaderSession) async {
        guard let route = ProcessInfo.processInfo.environment["CONDENSER_DEBUG_ROUTE"],
              let url = URL(string: "condenser://debug/\(route)") else { return }
        for _ in 0..<40 where reader.timeline.items.isEmpty {
            try? await Task.sleep(for: .milliseconds(250))
        }
        handleDebugURL(url, reader: reader)
    }

    /// 路由：tab/{timeline|subs|channels|saved} 切 tab；channel/{id} push 频道 timeline；
    /// hn 直接 push HN feed timeline；settings 切设置 tab；detail/{cid}/{mid}、
    /// viewer/{cid}/{mid} 弹详情 sheet / 全屏图（消息须已在 timeline 首页中）。
    /// 也可 `simctl openurl booted "condenser://debug/<route>"`
    /// （需在模拟器里手动点一次 Open 确认）。
    private func handleDebugURL(_ url: URL, reader: ReaderSession) {
        guard url.scheme == "condenser", url.host() == "debug" else { return }
        let parts = Array(url.pathComponents.dropFirst())
        switch parts.first {
        case "tab":
            switch parts.dropFirst().first {
            case "channels", "subs", "subscriptions":
                // tab/subs/<source> 可选第三段：直接滚到那个信源分组
                subsScrollTarget = parts.dropFirst(2).first
                selectedTab = .subscriptions
            case "saved": selectedTab = .saved
            default: selectedTab = .timeline
            }
        case "channel":
            if let id = parts.dropFirst().first.flatMap(Int.init),
               let sub = reader.telegramSub(for: id) {
                selectedTab = .subscriptions
                subscriptionsPath.append(SubDestination.telegramChannel(sub))
            }
        case "hn":
            if let sub = reader.hnSubs.first {
                selectedTab = .subscriptions
                subscriptionsPath.append(SubDestination.hnFeed(sub))
            }
        case "x":
            // x/<feed>（缺省第一条订阅）：For You 不在聚合流里，只能这样直达
            let feed = parts.dropFirst().first
            let sub = feed.flatMap { key in
                reader.xSubs.first { $0.channelID.description == key }
            } ?? reader.xSubs.first
            if let sub {
                selectedTab = .subscriptions
                subscriptionsPath.append(SubDestination.xFeed(sub))
            }
        case "settings":
            selectedTab = .settings
        case "detail":
            // detail/x/<feed>[/<tweet id>]：X 条目要单独走一次网络——For You 不在
            // 聚合 timeline 里，从 reader.timeline.items 里永远找不到它
            if parts.dropFirst().first == "x" {
                let feed = parts.dropFirst(2).first ?? XFeed.foryou
                let id = parts.dropFirst(3).first
                Task { debugDetail = await debugXItem(feed: feed, id: id, reader: reader) }
            } else {
                debugDetail = debugItem(parts, reader: reader)
            }
        case "forward":
            // forward/<cid>/<mid>[/<comment>]：直接弹转发 dialog；带第 4 段则自动提交
            // （"-" = 空评论原生转发；消息不必在 timeline 首页内）
            if let cid = parts.dropFirst().first.flatMap(Int.init),
               let mid = parts.dropFirst(2).first.flatMap(Int.init) {
                let raw = parts.dropFirst(3).first
                debugForward = DebugForwardRoute(
                    channelID: cid, messageID: mid,
                    autoComment: raw.map { $0 == "-" ? "" : $0 })
            }
        case "viewer":
            if let message = debugItem(parts, reader: reader)?.telegram {
                let photos = message.mediaItems.filter { $0.mediaType == "photo" && $0.hasMedia }
                if !photos.isEmpty {
                    debugViewer = ImageViewerItem(
                        channelID: message.channelID, photos: photos, startIndex: 0)
                }
            }
        default:
            break
        }
    }

    /// 指定 id 的推文，或该 feed 里第一条有判定的（判定证据是这个界面最想看的东西）
    private func debugXItem(feed: String, id: String?, reader: ReaderSession) async -> TimelineItem? {
        guard let page = try? await reader.api.timeline(limit: 50, source: SourceID.x, feed: feed)
        else { return nil }
        if let id {
            return page.items.first { $0.x?.id == id }
        }
        return page.items.first { $0.x?.verdict?.isFinding == true } ?? page.items.first
    }

    private func debugItem(_ parts: [String], reader: ReaderSession) -> TimelineItem? {
        let ids = Array(parts.dropFirst())
        guard ids.count == 2, let cid = Int(ids[0]), let mid = Int(ids[1]) else { return nil }
        return reader.timeline.items.first { $0.key == "tg:\(cid):\(mid)" }
    }

    private struct DebugForwardRoute: Identifiable {
        let channelID: Int
        let messageID: Int
        let autoComment: String?
        var id: String { "\(channelID)/\(messageID)" }
    }
    #endif
}
