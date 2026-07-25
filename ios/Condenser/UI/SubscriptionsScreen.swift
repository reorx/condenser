import SwiftUI
import CondenserKit

/// 订阅项导航目标：TG 频道 → 单频道 timeline；HN / X feed → 该 feed 的 timeline。
/// X 的 For You 不进聚合流，这里的两级列表就是它唯一的入口。
enum SubDestination: Hashable {
    case telegramChannel(SourceSub)
    case hnFeed(SourceSub)
    case xFeed(SourceSub)
}

/// 订阅 tab（原「频道」）：按 信源 → 订阅 两级展示（数据源 GET /api/sources）。
/// iOS 仍为只读客户端，订阅的增删改留在 web。
struct SubscriptionsScreen: View {
    /// DEBUG 走查用：进来就滚到某个信源分组（模拟器窗口收不到合成手势，
    /// 只能靠启动路由导航，见 AGENTS.md「CLI 驱动的界面走查」）
    var scrollToSource: String?

    @Environment(ReaderSession.self) private var reader

    var body: some View {
        ScrollViewReader { proxy in
            list
                .onAppear {
                    guard let scrollToSource else { return }
                    proxy.scrollTo(scrollToSource, anchor: .top)
                }
        }
    }

    private var list: some View {
        List {
            ForEach(reader.sources) { group in
                Section(SourceID.label(group.source)) {
                    ForEach(enabledSubs(group)) { sub in
                        NavigationLink(value: destination(group.source, sub)) {
                            row(group.source, sub)
                        }
                    }
                }
                .id(group.source)
            }
        }
        .listStyle(.insetGrouped)
        .overlay {
            if reader.sources.allSatisfy({ $0.subscriptions.filter(\.enabled).isEmpty }) {
                emptyState
            }
        }
        .navigationTitle("订阅")
        .navigationDestination(for: SubDestination.self) { dest in
            switch dest {
            case .telegramChannel(let sub):
                ChannelTimelineScreen(subscription: sub)
            case .hnFeed(let sub):
                HnFeedTimelineScreen(subscription: sub)
            case .xFeed(let sub):
                XFeedTimelineScreen(subscription: sub)
            }
        }
        .refreshable { await reader.loadSources() }
        .task { await reader.loadSources() }
    }

    private func enabledSubs(_ group: SourceGroup) -> [SourceSub] {
        group.subscriptions.filter(\.enabled)
    }

    private func destination(_ source: String, _ sub: SourceSub) -> SubDestination {
        switch source {
        case SourceID.hn: .hnFeed(sub)
        case SourceID.x: .xFeed(sub)
        default: .telegramChannel(sub)
        }
    }

    private func row(_ source: String, _ sub: SourceSub) -> some View {
        HStack(spacing: 12) {
            switch source {
            case SourceID.hn:
                HnGlyph(size: 40)
            case SourceID.x:
                // For You 没有作者可言，用信源标记；关注人用他自己的头像
                if sub.channelID.description == XFeed.foryou {
                    XGlyph(size: 40)
                } else {
                    XAvatarView(handle: sub.username, name: sub.name, size: 40)
                }
            default:
                ChannelAvatarView(
                    channelID: sub.channelID.intValue,
                    title: sub.name ?? "#", size: 40)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(rowTitle(source, sub))
                    .font(.subheadline.weight(.medium))
                    .lineLimit(1)
                if let username = sub.username {
                    Text("@\(username)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            if sub.unread > 0 {
                Text("\(sub.unread)")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(.tint, in: Capsule())
            }
        }
        .padding(.vertical, 2)
    }

    /// X 关注人的 name 在首次 push 学到真实显示名前是 NULL，
    /// 这时回落 @handle 而不是画一个占位（否则会出现「@x @x」）
    private func rowTitle(_ source: String, _ sub: SourceSub) -> String {
        if source == SourceID.x {
            return XFeed.label(sub.channelID.description, name: sub.name)
        }
        return sub.name ?? "频道 \(sub.channelID.description)"
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "square.stack")
                .font(.largeTitle)
                .foregroundStyle(.tertiary)
            Text("暂无订阅")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }
}

/// 单频道 timeline（TG）：复用 MessageListView，store 按频道现建（无快照、无轮询）。
struct ChannelTimelineScreen: View {
    let subscription: SourceSub

    @Environment(ReaderSession.self) private var reader
    @State private var store: TimelineStore?

    var body: some View {
        Group {
            if let store {
                MessageListView(store: store, emptyLabel: "该频道暂无消息")
            } else {
                Color.clear
            }
        }
        .navigationTitle(subscription.name ?? "频道 \(subscription.channelID.description)")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if store == nil, let channelID = subscription.channelID.intValue {
                store = reader.makeChannelStore(channelID: channelID)
            }
        }
    }
}

/// HN feed timeline：v1 单 feed（front）= source=hn 的全量视图；
/// 无 TG 专属能力（fetch-older 上拉、频道头像等自动缺席）。
struct HnFeedTimelineScreen: View {
    let subscription: SourceSub

    @Environment(ReaderSession.self) private var reader
    @State private var store: TimelineStore?

    var body: some View {
        Group {
            if let store {
                MessageListView(store: store, emptyLabel: "还没有归档的 story")
            } else {
                Color.clear
            }
        }
        .navigationTitle(subscription.name ?? "Hacker News")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if store == nil {
                store = reader.makeHnStore()
            }
        }
    }
}

/// 单个 X feed 的 timeline（For You 或某个关注人）：X 是第一个「一个信源多个 feed」
/// 的源，所以 store 要带 feed 作用域。For You **不进聚合流**（一天 ~1000 条会淹没
/// TG/HN），这个界面就是它唯一的入口。
struct XFeedTimelineScreen: View {
    let subscription: SourceSub

    @Environment(ReaderSession.self) private var reader
    @State private var store: TimelineStore?

    private var feed: String { subscription.channelID.description }

    var body: some View {
        Group {
            if let store {
                MessageListView(store: store, emptyLabel: "还没有归档的推文")
            } else {
                Color.clear
            }
        }
        .navigationTitle(XFeed.label(feed, name: subscription.name))
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if store == nil {
                store = reader.makeXStore(feed: feed)
            }
        }
    }
}
