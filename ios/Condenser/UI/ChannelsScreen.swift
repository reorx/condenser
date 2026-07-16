import SwiftUI
import CondenserKit

/// 频道 tab：enabled 订阅列表（头像/标题/未读徽标），点击 push 进单频道 timeline。
struct ChannelsScreen: View {
    @Environment(ReaderSession.self) private var reader

    private var channels: [Subscription] {
        reader.subscriptions.filter(\.enabled)
    }

    var body: some View {
        List(channels) { sub in
            NavigationLink(value: sub) {
                row(sub)
            }
        }
        .listStyle(.plain)
        .overlay {
            if channels.isEmpty {
                emptyState
            }
        }
        .navigationTitle("频道")
        .navigationDestination(for: Subscription.self) { sub in
            ChannelTimelineScreen(subscription: sub)
        }
        .refreshable { await reader.loadSubscriptions() }
        .task { await reader.loadSubscriptions() }
    }

    private func row(_ sub: Subscription) -> some View {
        HStack(spacing: 12) {
            ChannelAvatarView(
                channelID: sub.channelID,
                title: sub.title ?? "#", size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(sub.title ?? "频道 \(sub.channelID)")
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
            Image(systemName: "megaphone")
                .font(.largeTitle)
                .foregroundStyle(.tertiary)
            Text("暂无订阅频道")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }
}

/// 单频道 timeline：复用 MessageListView，store 按频道现建（无快照、无轮询）。
struct ChannelTimelineScreen: View {
    let subscription: Subscription

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
        .navigationTitle(subscription.title ?? "频道 \(subscription.channelID)")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if store == nil {
                store = reader.makeChannelStore(channelID: subscription.channelID)
            }
        }
    }
}
