import SwiftUI
import CondenserKit

/// 紧凑消息卡片：头像 + 频道名 + 相对时间 + 收藏星；正文预览 5 行；
/// 媒体缩略图（单图按 API 尺寸预留纵横比，多图网格方形）；转发标记。
struct MessageCard: View {
    let message: DisplayMessage
    var onToggleSaved: () -> Void

    @Environment(ReaderSession.self) private var reader

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            if message.isForwarded {
                Label(forwardLabel, systemImage: "arrowshape.turn.up.right")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            if let text = message.text, !text.isEmpty {
                Text(text)
                    .font(.subheadline)
                    .lineLimit(5)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            MessageMediaView(message: message)
            if let webpage = message.webpage {
                WebPagePreviewCard(message: message, webpage: webpage)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .contentShape(Rectangle())
    }

    private var header: some View {
        HStack(spacing: 10) {
            ChannelAvatarView(
                channelID: message.channelID,
                title: reader.channelTitle(for: message.channelID))
            VStack(alignment: .leading, spacing: 1) {
                Text(reader.channelTitle(for: message.channelID))
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                HStack(spacing: 4) {
                    if isUnread {
                        Circle().fill(.tint).frame(width: 6, height: 6)
                    }
                    Text(message.date.formatted(.relative(presentation: .named)))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if message.isEdited {
                        Text("已编辑")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
            Spacer(minLength: 8)
            Button(action: onToggleSaved) {
                Image(systemName: isSaved ? "star.fill" : "star")
                    .foregroundStyle(isSaved ? .orange : .secondary)
            }
            .buttonStyle(.plain)
        }
    }

    private var isSaved: Bool { message.isSaved ?? false }

    private var isUnread: Bool {
        !(message.isRead ?? false) && !reader.readReporter.readRefs.contains(message.ref)
    }

    private var forwardLabel: String {
        let info = message.forwardInfo
        let source = info?.fromChannelName ?? info?.fromUserName ?? info?.postAuthor
        return source.map { "转发自 \($0)" } ?? "转发"
    }
}

/// 媒体区：photo 缩略图；单图按 API 尺寸预留纵横比，多图方形网格；
/// 视频/文件显示类型 chip（v1 不播放）。
struct MessageMediaView: View {
    let message: DisplayMessage

    @Environment(ReaderSession.self) private var reader

    private var photos: [MediaItem] {
        message.mediaItems.filter { $0.mediaType == "photo" && $0.hasMedia }
    }

    private var others: [MediaItem] {
        message.mediaItems.filter { $0.hasMedia && $0.mediaType != "photo" && $0.mediaType != "webpage" }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if photos.count == 1 {
                singlePhoto(photos[0])
            } else if photos.count > 1 {
                photoGrid
            }
            ForEach(others, id: \.messageID) { item in
                fileChip(item)
            }
        }
    }

    private func singlePhoto(_ item: MediaItem) -> some View {
        let ratio: CGFloat = if let w = item.width, let h = item.height, h > 0 {
            CGFloat(w) / CGFloat(h)
        } else {
            4 / 3
        }
        return AuthedAsyncImage(request: thumbRequest(item))
            .aspectRatio(ratio, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var photoGrid: some View {
        // 2/4 张走 2 列（避免孤行），其余 3 列
        let columns = Array(
            repeating: GridItem(.flexible(), spacing: 4),
            count: photos.count == 2 || photos.count == 4 ? 2 : 3)
        return LazyVGrid(columns: columns, spacing: 4) {
            ForEach(photos, id: \.messageID) { item in
                AuthedAsyncImage(request: thumbRequest(item))
                    .aspectRatio(1, contentMode: .fill)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }
        }
    }

    private func fileChip(_ item: MediaItem) -> some View {
        Label(
            item.mediaType == "document" ? "视频 / 文件" : (item.mediaType ?? "附件"),
            systemImage: "doc.fill")
            .font(.caption)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Color(.secondarySystemBackground), in: Capsule())
    }

    private func thumbRequest(_ item: MediaItem) -> URLRequest {
        reader.api.authedRequest(
            reader.api.mediaURL(channelID: message.channelID, messageID: item.messageID, thumb: true))
    }
}

/// Telegram 内嵌网页预览卡片
struct WebPagePreviewCard: View {
    let message: DisplayMessage
    let webpage: WebPagePreview

    @Environment(ReaderSession.self) private var reader

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 2)
                .fill(.tint)
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 2) {
                if let site = webpage.siteName {
                    Text(site)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.tint)
                }
                if let title = webpage.title {
                    Text(title)
                        .font(.caption.weight(.medium))
                        .lineLimit(2)
                }
                if let description = webpage.description {
                    Text(description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 0)
            if webpage.hasPhoto {
                AuthedAsyncImage(request: reader.api.authedRequest(
                    reader.api.mediaURL(channelID: message.channelID, messageID: message.id, thumb: true)))
                    .frame(width: 48, height: 48)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }
        }
        .padding(8)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10))
    }
}
