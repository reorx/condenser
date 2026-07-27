import SwiftUI
import SafariServices
import CondenserKit

/// 详情 bottom sheet（Telegram 条目）：全文（链接可点 → SFSafariViewController）、
/// 原图、转发来源、本地时区时间、收藏、在 Telegram 打开。
struct MessageDetailSheet: View {
    let item: TimelineItem
    let message: DisplayMessage
    var onToggleSaved: () -> Void

    @Environment(ReaderSession.self) private var reader
    @State private var safariItem: SafariItem?
    @State private var viewerItem: ImageViewerItem?
    @State private var copied = false
    @State private var stats: MessageStats?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                if let stats, !stats.isEmpty {
                    MessageStatsRow(stats: stats)
                }
                if message.isForwarded, message.forwardSource == nil {
                    forwardBox
                }
                if let text = message.text, !text.isEmpty {
                    SelectableTextView(text: text)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                images
                if let webpage = message.webpage {
                    // 点击卡片打开链接：WebPagePreviewCard 自带 openURL 点击，走下方环境接管
                    WebPagePreviewCard(message: message, webpage: webpage)
                }
                Divider()
                actions
            }
            .padding(16)
        }
        .readingFontScale()
        .task {
            // 实时 stats 拉不到（掉线/限流/消息已删）就不显示，不打断阅读
            stats = try? await reader.api.messageStats(
                channelID: message.channelID, messageID: message.id)
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

    /// 与列表卡片一致：转发消息以来源为主体，小字标 Forwarded by 订阅频道
    private var header: some View {
        let source = message.forwardSource
        let dateText = message.date.formatted(date: .abbreviated, time: .shortened)
        return HStack(spacing: 10) {
            ChannelAvatarView(
                channelID: source.map(\.peerID) ?? message.channelID,
                title: source?.name ?? reader.channelTitle(for: message), size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(source?.name ?? reader.channelTitle(for: message))
                    .font(.headline)
                    .lineLimit(1)
                Text(source != nil
                    ? "Forwarded by \(reader.channelTitle(for: message)) · \(dateText)"
                    : dateText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
        }
    }

    /// 隐藏来源的转发（无名字可展示）才走这行降级标记
    private var forwardBox: some View {
        Label("转发", systemImage: "arrowshape.turn.up.right")
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

    private var actions: some View {
        ItemActionRow {
            ItemActionButtons(item: item, onToggleSaved: onToggleSaved)
            if let text = message.text, !text.isEmpty {
                Button {
                    UIPasteboard.general.string = text
                    copied = true
                    Task {
                        try? await Task.sleep(for: .seconds(1.5))
                        copied = false
                    }
                } label: {
                    Label(copied ? "已复制" : "复制全文",
                          systemImage: copied ? "checkmark" : "doc.on.doc")
                        .font(.footnote)
                }
                .buttonStyle(.bordered)
                .tint(copied ? .green : nil)
            }
            if let username = reader.channelUsername(for: message),
               let url = URL(string: "https://t.me/\(username)/\(message.id)") {
                Link(destination: url) {
                    Label("在 Telegram 打开", systemImage: "paperplane")
                        .font(.footnote)
                }
                .buttonStyle(.bordered)
            }
        }
        .sensoryFeedback(.success, trigger: copied) { _, new in new }
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
