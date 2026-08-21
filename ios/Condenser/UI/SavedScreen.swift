import SwiftUI
import CondenserKit

/// 收藏 tab：GET /api/records 快照列表（条目为自包含 envelope——TG 带 channel、
/// HN 带 story 快照，X / RSS 直接存 payload），星标 = 取消收藏（乐观移除 + 失败回滚），
/// 点开对应详情 sheet。
struct SavedScreen: View {
    @Environment(ReaderSession.self) private var reader
    @State private var selectedItem: TimelineItem?
    @State private var safariItem: SafariItem?
    @State private var viewerItem: ImageViewerItem?

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                if reader.records.isLoading && reader.records.items.isEmpty {
                    ProgressView().padding(.top, 120)
                } else if reader.records.items.isEmpty {
                    emptyState
                }
                ForEach(reader.records.items) { item in
                    VStack(spacing: 0) {
                        card(item)
                            .onTapGesture { selectedItem = item }
                        Divider().padding(.leading, 16)
                    }
                }
                if let error = reader.records.error {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding(.vertical, 12)
                }
            }
        }
        .readingFontScale()
        .autoHideBars()
        .refreshable { await reader.records.refresh() }
        .navigationTitle("收藏")
        .navigationBarTitleDisplayMode(.inline)
        .externalLinks(safari: $safariItem)
        .sheet(item: $selectedItem) { item in
            detailSheet(item)
        }
        .sheet(item: $safariItem) { item in
            SafariView(url: item.url)
                .ignoresSafeArea()
        }
        .fullScreenCover(item: $viewerItem) { item in
            ImageViewerScreen(item: item)
        }
        .task { await reader.records.refresh() }
    }

    /// 按 source 分发卡片（未读点在收藏列表无意义，一律隐藏）
    @ViewBuilder
    private func card(_ item: TimelineItem) -> some View {
        if let message = item.telegram {
            MessageCard(
                item: item, message: message,
                showsUnread: false,
                onToggleSaved: { unsave(item) },
                onOpenPhoto: { openViewer(for: message, at: $0) })
        } else if let story = item.hn {
            HnCard(item: item, story: story, showsUnread: false, onToggleSaved: { unsave(item) })
        } else if let tweet = item.x {
            XCard(
                item: item, tweet: tweet, showsUnread: false,
                onToggleSaved: { unsave(item) },
                onFeedback: { setFeedback(item, $0) },
                onReason: { setReason(item, $0) },
                onOpenPhoto: { openViewer(for: tweet, at: $0) })
        } else if let entry = item.rss {
            RssCard(item: item, entry: entry, showsUnread: false, onToggleSaved: { unsave(item) })
        }
    }

    @ViewBuilder
    private func detailSheet(_ item: TimelineItem) -> some View {
        if let message = item.telegram {
            MessageDetailSheet(
                item: item, message: message,
                onToggleSaved: { unsave(item) })
        } else if let story = item.hn {
            HnDetailSheet(item: item, story: story, onToggleSaved: { unsave(item) })
        } else if let tweet = item.x {
            XDetailSheet(
                item: item, tweet: tweet,
                onToggleSaved: { unsave(item) },
                onFeedback: { setFeedback(item, $0) },
                onReason: { setReason(item, $0) })
        } else if let entry = item.rss {
            RssDetailSheet(item: item, entry: entry, onToggleSaved: { unsave(item) })
        }
    }

    private func openViewer(for message: DisplayMessage, at index: Int) {
        let photos = message.mediaItems.filter { $0.mediaType == "photo" && $0.hasMedia }
        guard !photos.isEmpty else { return }
        viewerItem = ImageViewerItem(
            channelID: message.channelID, photos: photos,
            startIndex: min(index, photos.count - 1))
    }

    private func openViewer(for tweet: XTweet, at index: Int) {
        guard let start = tweet.photoIndex(forDisplayed: index) else { return }
        viewerItem = ImageViewerItem(
            urls: tweet.photos.compactMap(\.thumbnailURL), startIndex: start)
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "star")
                .font(.largeTitle)
                .foregroundStyle(.tertiary)
            Text("还没有收藏")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 120)
    }

    private func unsave(_ item: TimelineItem) {
        Task { await reader.records.unsave(item) }
    }

    private func setFeedback(_ item: TimelineItem, _ verdict: ItemFeedback) {
        Task { await reader.records.setFeedback(item, verdict) }
    }

    private func setReason(_ item: TimelineItem, _ reason: ItemFeedbackReason) {
        Task { await reader.records.setReason(item, reason) }
    }
}
