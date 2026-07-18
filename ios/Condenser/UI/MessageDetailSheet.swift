import SwiftUI
import SafariServices
import CondenserKit

/// 详情 bottom sheet：全文（链接可点 → SFSafariViewController）、原图、
/// 转发来源、本地时区时间、收藏、在 Telegram 打开。
struct MessageDetailSheet: View {
    let message: DisplayMessage
    var onToggleSaved: () -> Void

    @Environment(ReaderSession.self) private var reader
    @State private var safariItem: SafariItem?
    @State private var viewerItem: ImageViewerItem?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                if message.isForwarded {
                    forwardBox
                }
                if let text = message.text, !text.isEmpty {
                    Text(linkified(text))
                        .font(.body)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                images
                if let webpage = message.webpage {
                    // 点击卡片打开链接：WebPagePreviewCard 自带 openURL 点击，走下方环境接管
                    WebPagePreviewCard(message: message, webpage: webpage)
                }
                footer
            }
            .padding(16)
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .environment(\.openURL, OpenURLAction { url in
            safariItem = SafariItem(url: url)
            return .handled
        })
        .sheet(item: $safariItem) { item in
            SafariView(url: item.url)
                .ignoresSafeArea()
        }
        .fullScreenCover(item: $viewerItem) { item in
            ImageViewerScreen(item: item)
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            ChannelAvatarView(
                channelID: message.channelID,
                title: reader.channelTitle(for: message), size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(reader.channelTitle(for: message))
                    .font(.headline)
                    .lineLimit(1)
                Text(message.date.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button(action: onToggleSaved) {
                Image(systemName: (message.isSaved ?? false) ? "star.fill" : "star")
                    .foregroundStyle((message.isSaved ?? false) ? .orange : .secondary)
            }
            .buttonStyle(.plain)
        }
    }

    private var forwardBox: some View {
        let info = message.forwardInfo
        let source = info?.fromChannelName ?? info?.fromUserName ?? info?.postAuthor
        return Label(
            source.map { "转发自 \($0)" } ?? "转发",
            systemImage: "arrowshape.turn.up.right")
            .font(.footnote)
            .foregroundStyle(.secondary)
    }

    @ViewBuilder
    private var images: some View {
        let photos = message.mediaItems.filter { $0.mediaType == "photo" && $0.hasMedia }
        ForEach(Array(photos.enumerated()), id: \.element.messageID) { index, item in
            AuthedAsyncImage(
                request: reader.api.authedRequest(
                    reader.api.mediaURL(channelID: message.channelID, messageID: item.messageID)),
                contentMode: .fit)
                .aspectRatio(aspectRatio(item), contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .onTapGesture {
                    viewerItem = ImageViewerItem(
                        channelID: message.channelID, photos: photos, startIndex: index)
                }
        }
        let others = message.mediaItems.filter { $0.hasMedia && $0.mediaType != "photo" && $0.mediaType != "webpage" }
        ForEach(others, id: \.messageID) { item in
            Label(item.mediaType ?? "附件", systemImage: "doc.fill")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private var footer: some View {
        if let username = reader.channelUsername(for: message),
           let url = URL(string: "https://t.me/\(username)/\(message.id)") {
            Link(destination: url) {
                Label("在 Telegram 打开", systemImage: "paperplane")
                    .font(.footnote)
            }
        }
    }

    private func aspectRatio(_ item: MediaItem) -> CGFloat {
        if let w = item.width, let h = item.height, h > 0 {
            CGFloat(w) / CGFloat(h)
        } else {
            4 / 3
        }
    }
}

struct SafariItem: Identifiable {
    let url: URL
    var id: String { url.absoluteString }
}

struct SafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        SFSafariViewController(url: url)
    }

    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}
