import SwiftUI
import CondenserKit

/// 收藏 tab：GET /api/records 快照列表（条目自包含 channel），
/// 星标 = 取消收藏（乐观移除 + 失败回滚），点开同一详情 sheet。
struct SavedScreen: View {
    @Environment(ReaderSession.self) private var reader
    @State private var selectedMessage: DisplayMessage?
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
                ForEach(reader.records.items, id: \.unitKey) { message in
                    VStack(spacing: 0) {
                        MessageCard(
                            message: message,
                            showsUnread: false,
                            onToggleSaved: { unsave(message) },
                            onOpenPhoto: { openViewer(for: message, at: $0) })
                            .onTapGesture { selectedMessage = message }
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
        .environment(\.openURL, OpenURLAction { url in
            safariItem = SafariItem(url: url)
            return .handled
        })
        .sheet(item: $selectedMessage) { message in
            MessageDetailSheet(
                message: message,
                onToggleSaved: { unsave(message) })
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

    private func openViewer(for message: DisplayMessage, at index: Int) {
        let photos = message.mediaItems.filter { $0.mediaType == "photo" && $0.hasMedia }
        guard !photos.isEmpty else { return }
        viewerItem = ImageViewerItem(
            channelID: message.channelID, photos: photos,
            startIndex: min(index, photos.count - 1))
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

    private func unsave(_ message: DisplayMessage) {
        Task { await reader.records.unsave(message) }
    }
}
