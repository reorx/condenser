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
    #if DEBUG
    @State private var debugDetail: TimelineItem?
    @State private var debugViewer: ImageViewerItem?
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
                    SubscriptionsScreen()
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
            }
        }
        .fullScreenCover(item: $debugViewer) { item in
            ImageViewerScreen(item: item)
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
            case "channels", "subs", "subscriptions": selectedTab = .subscriptions
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
        case "settings":
            selectedTab = .settings
        case "detail":
            debugDetail = debugItem(parts, reader: reader)
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

    private func debugItem(_ parts: [String], reader: ReaderSession) -> TimelineItem? {
        let ids = Array(parts.dropFirst())
        guard ids.count == 2, let cid = Int(ids[0]), let mid = Int(ids[1]) else { return nil }
        return reader.timeline.items.first { $0.key == "tg:\(cid):\(mid)" }
    }
    #endif
}
