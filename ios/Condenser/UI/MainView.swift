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

    /// 每个 tab 的内容各自再挂一次 `.environment(reader)`（外层 `tabs(reader).environment(reader)`
    /// 仍在）：Mac 上 `.sidebarAdaptable` 的 TabView 切到非首个 tab 时，新 tab 的视图树拿不到
    /// 外层注入的 Observable（2026-09-04 Catalyst 实测，切「设置」即 Fatal error），
    /// iPhone 上不受影响。挂在 tab 内部是两边都对的写法。
    private func tabs(_ reader: ReaderSession) -> some View {
        TabView(selection: $selectedTab) {
            Tab("Timeline", systemImage: "list.bullet.rectangle", value: MainTab.timeline) {
                NavigationStack {
                    TimelineScreen()
                }
                .environment(reader)
            }
            Tab("订阅", systemImage: "square.stack", value: MainTab.subscriptions) {
                NavigationStack(path: $subscriptionsPath) {
                    SubscriptionsScreen(scrollToSource: subsScrollTarget)
                }
                .environment(reader)
            }
            Tab("收藏", systemImage: "star", value: MainTab.saved) {
                NavigationStack {
                    SavedScreen()
                }
                .environment(reader)
            }
            Tab("设置", systemImage: "gearshape", value: MainTab.settings) {
                NavigationStack {
                    SettingsScreen()
                }
                .environment(reader)
            }
        }
        // iPhone 上仍是底部 tab 栏；Mac（与 iPad）上变成侧栏——四个 tab 就是 Mac 阅读器
        // 的标准形状（Mail / News 都这样），底部 tab 栏在桌面窗口里是个错位的手机件
        .tabViewStyle(.sidebarAdaptable)
        #if DEBUG
        .onOpenURL { handleDebugURL($0, reader: reader) }
        .sheet(item: $debugDetail) { item in
            Group {
                if let message = item.telegram {
                    MessageDetailSheet(item: item, message: message, onToggleSaved: {})
                } else if let story = item.hn {
                    HnDetailSheet(item: item, story: story, onToggleSaved: {})
                } else if let tweet = item.x {
                    XDetailSheet(
                        item: item, tweet: tweet, onToggleSaved: {},
                        onFeedback: { _ in }, onReason: { _ in })
                } else if let entry = item.rss {
                    RssDetailSheet(item: item, entry: entry, onToggleSaved: {})
                }
            }
            .environment(reader)
        }
        .fullScreenCover(item: $debugViewer) { item in
            ImageViewerScreen(item: item)
                .environment(reader)
        }
        .sheet(item: $debugForward) { route in
            ForwardDialog(
                itemKey: route.key, isTelegram: route.key.hasPrefix("tg:"),
                debugAutoComment: route.autoComment)
                .environment(reader)
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
    /// hn 直接 push HN feed timeline；x[/feed] / rss[/下标] push 单 feed timeline；
    /// settings 切设置 tab；detail/{cid}/{mid}、
    /// viewer/{cid}/{mid} 弹详情 sheet / 全屏图（消息须已在 timeline 首页中）；
    /// detail/{hn|rss|x}/… 弹另外三个源的详情（单独查一次，不必在首屏里）。
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
        case "rss":
            // rss[/<第几个订阅>]：feed key 是一整个 URL，塞不进路径段，所以用下标指
            let index = parts.dropFirst().first.flatMap(Int.init) ?? 0
            if reader.rssSubs.indices.contains(index) {
                selectedTab = .subscriptions
                subscriptionsPath.append(SubDestination.rssFeed(reader.rssSubs[index]))
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
            } else if parts.dropFirst().first == "hn" {
                // detail/hn[/<story id>]：HN 在聚合流里，但走查想看的那条未必在首屏
                let id = parts.dropFirst(2).first
                Task { debugDetail = await debugHnItem(id: id, reader: reader) }
            } else if parts.dropFirst().first == "rss" {
                // detail/rss[/<条目 id>]：RSS 在聚合流里，但首屏未必有它
                // （未读窗口把存量都标了已读），所以同样单独查一次
                let id = parts.dropFirst(2).first
                Task { debugDetail = await debugRssItem(id: id, reader: reader) }
            } else {
                debugDetail = debugItem(parts, reader: reader)
            }
        case "forward":
            // forward/<item key>[/<comment>]：直接弹转发 dialog；带第 3 段则自动提交
            // （"-" = 不带评论；条目不必在 timeline 首页内，只用 key）
            if let key = parts.dropFirst().first {
                let raw = parts.dropFirst(2).first
                debugForward = DebugForwardRoute(
                    key: key, autoComment: raw.map { $0 == "-" ? "" : $0 })
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

    /// 指定 id 的 story，或第一条 self-post（自文正文 + 预览卡是这个界面最想看的东西）
    private func debugHnItem(id: String?, reader: ReaderSession) async -> TimelineItem? {
        guard let page = try? await reader.api.timeline(limit: 50, source: SourceID.hn)
        else { return nil }
        if let id {
            return page.items.first { $0.hn?.id == Int(id) }
        }
        return page.items.first { $0.hn?.text?.isEmpty == false } ?? page.items.first
    }

    /// 指定 id 的条目，或第一条带正文的（正文渲染是这个界面最想看的东西）。
    /// 按 id 找要翻页：归档按时间倒序，而值得看的往往是老条目（中文长文、缺字段的怪例）
    private func debugRssItem(id: String?, reader: ReaderSession) async -> TimelineItem? {
        var cursor: String?
        for _ in 0..<8 {
            guard let page = try? await reader.api.timeline(
                cursor: cursor, limit: 50, source: SourceID.rss) else { return nil }
            guard let id else {
                return page.items.first { $0.rss?.contentText != nil } ?? page.items.first
            }
            if let hit = page.items.first(where: { $0.rss?.id == Int(id) }) { return hit }
            guard let next = page.nextCursor else { return nil }
            cursor = next
        }
        return nil
    }

    private func debugItem(_ parts: [String], reader: ReaderSession) -> TimelineItem? {
        let ids = Array(parts.dropFirst())
        guard ids.count == 2, let cid = Int(ids[0]), let mid = Int(ids[1]) else { return nil }
        return reader.timeline.items.first { $0.key == "tg:\(cid):\(mid)" }
    }

    private struct DebugForwardRoute: Identifiable {
        let key: String
        let autoComment: String?
        var id: String { key }
    }
    #endif
}
