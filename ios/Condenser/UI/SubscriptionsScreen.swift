import SwiftUI
import CondenserKit

/// 订阅项导航目标：TG 频道 → 单频道 timeline；HN feed → 该 feed 的 timeline。
enum SubDestination: Hashable {
    case telegramChannel(SourceSub)
    case hnFeed(SourceSub)
}

/// 订阅 tab（原「频道」）：按 信源 → 订阅 两级展示（数据源 GET /api/sources）。
/// iOS 仍为只读客户端，订阅的增删改留在 web。
struct SubscriptionsScreen: View {
    @Environment(ReaderSession.self) private var reader

    var body: some View {
        List {
            ForEach(reader.sources) { group in
                Section(SourceID.label(group.source)) {
                    ForEach(enabledSubs(group)) { sub in
                        NavigationLink(value: destination(group.source, sub)) {
                            row(group.source, sub)
                        }
                    }
                }
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
            }
        }
        .refreshable { await reader.loadSources() }
        .task { await reader.loadSources() }
    }

    private func enabledSubs(_ group: SourceGroup) -> [SourceSub] {
        group.subscriptions.filter(\.enabled)
    }

    private func destination(_ source: String, _ sub: SourceSub) -> SubDestination {
        source == SourceID.hn ? .hnFeed(sub) : .telegramChannel(sub)
    }

    private func row(_ source: String, _ sub: SourceSub) -> some View {
        HStack(spacing: 12) {
            if source == SourceID.hn {
                HnGlyph(size: 40)
            } else {
                ChannelAvatarView(
                    channelID: sub.channelID.intValue,
                    title: sub.name ?? "#", size: 40)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(sub.name ?? "频道 \(sub.channelID.description)")
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
