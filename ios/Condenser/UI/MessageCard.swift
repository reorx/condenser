import SwiftUI
import CondenserKit

/// 紧凑消息卡片（Telegram 条目）：头像 + 频道名 + 相对时间 + 收藏星；正文预览
/// （截断显示蓝色 more，链接可直接点击）；媒体缩略图（点击直接开全屏查看器）；转发标记。
/// 已读/收藏态在外层 TimelineItem envelope 上。
struct MessageCard: View {
    let item: TimelineItem
    let message: DisplayMessage
    /// 收藏列表不展示未读点（records 不携带已读态）
    var showsUnread = true
    var onToggleSaved: () -> Void
    /// 点击第 i 张图片（timeline 直接全屏查看，不经详情 sheet）
    var onOpenPhoto: ((Int) -> Void)? = nil

    @Environment(ReaderSession.self) private var reader

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            // 有来源主体的转发已在 header 展示；只剩隐藏来源时才补一行降级标记
            if message.isForwarded, message.forwardSource == nil {
                Label("转发", systemImage: "arrowshape.turn.up.right")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            if let text = message.text, !text.isEmpty {
                TruncatableText(text: text)
            }
            MessageMediaView(message: message, onOpenPhoto: onOpenPhoto)
            if let webpage = message.webpage {
                WebPagePreviewCard(message: message, webpage: webpage)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .contentShape(Rectangle())
    }

    /// 转发消息以来源频道/用户为主体（头像 + 名称），小字标 Forwarded by 订阅频道；
    /// 普通消息主体即订阅频道本身。
    private var header: some View {
        let source = message.forwardSource
        return HStack(spacing: 10) {
            ChannelAvatarView(
                channelID: source.map(\.peerID) ?? message.channelID,
                title: source?.name ?? reader.channelTitle(for: message))
            VStack(alignment: .leading, spacing: 1) {
                Text(source?.name ?? reader.channelTitle(for: message))
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                HStack(spacing: 4) {
                    ReadStateDot(item: item, showsUnread: showsUnread)
                    Text(source != nil
                        ? "Forwarded by \(reader.channelTitle(for: message)) · \(timestampText)"
                        : timestampText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            AnnotationBadge(item: item)
            Button(action: onToggleSaved) {
                Image(systemName: isSaved ? "star.fill" : "star")
                    .foregroundStyle(isSaved ? .orange : .secondary)
            }
            .buttonStyle(.plain)
        }
    }

    /// 3 天内相对时间，更早直接绝对时间（与详情 sheet 同格式）
    private var timestampText: String {
        switch MessageTimestamp.style(for: message.date) {
        case .relative:
            message.date.formatted(.relative(presentation: .named))
        case .absolute:
            message.date.formatted(date: .abbreviated, time: .shortened)
        }
    }

    private var isSaved: Bool { item.isSaved }
}

/// 8 行截断正文：隐藏的不限行副本测高判断是否截断，截断时末尾追加蓝色 more；
/// 链接高亮、可直接点击（由列表层的 openURL 环境接管）。TG 与 X 卡片共用。
struct TruncatableText: View {
    let text: String
    /// X 专用（schema v13）：t.co → 原始链接的替换元数据，其他卡片不传
    var urlEntities: [XUrlEntity]? = nil

    @State private var limitedHeight: CGFloat = 0
    @State private var fullHeight: CGFloat = 0

    private var isTruncated: Bool { fullHeight > limitedHeight + 1 }

    var body: some View {
        let attributed = linkified(text, urlEntities: urlEntities)
        VStack(alignment: .leading, spacing: 2) {
            Text(attributed)
                .font(.subheadline)
                .lineLimit(8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { limitedHeight = $0 }
                .background(alignment: .topLeading) {
                    // 测量用副本：不参与布局尺寸，只报告全文高度
                    Text(attributed)
                        .font(.subheadline)
                        .fixedSize(horizontal: false, vertical: true)
                        .hidden()
                        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { fullHeight = $0 }
                }
            if isTruncated {
                Text("more")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.tint)
            }
        }
    }
}

/// 媒体区：photo 缩略图；单图按 API 尺寸预留纵横比（竖图收敛到 3:4），多图方形网格；
/// 缩略图始终装在固定占位盒里再裁剪，避免原图尺寸把布局撑爆。
/// 视频/文件显示类型 chip（v1 不播放）。
struct MessageMediaView: View {
    let message: DisplayMessage
    /// 点击第 i 张图片；nil 时图片不响应点击
    var onOpenPhoto: ((Int) -> Void)? = nil

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
        photoBox(item, index: 0, ratio: previewRatio(item), cornerRadius: 10)
    }

    private var photoGrid: some View {
        // 2/4 张走 2 列（避免孤行），其余 3 列
        let columns = Array(
            repeating: GridItem(.flexible(), spacing: 4),
            count: photos.count == 2 || photos.count == 4 ? 2 : 3)
        return LazyVGrid(columns: columns, spacing: 4) {
            ForEach(Array(photos.enumerated()), id: \.element.messageID) { index, item in
                photoBox(item, index: index, ratio: 1, cornerRadius: 6)
            }
        }
    }

    /// 固定纵横比的占位盒 + overlay 装图：图片以 fill 居中裁剪，绝不影响布局尺寸
    private func photoBox(_ item: MediaItem, index: Int, ratio: CGFloat, cornerRadius: CGFloat) -> some View {
        Color.clear
            .aspectRatio(ratio, contentMode: .fit)
            .overlay { AuthedAsyncImage(request: thumbRequest(item)) }
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius))
            .contentShape(RoundedRectangle(cornerRadius: cornerRadius))
            .onTapGesture { onOpenPhoto?(index) }
    }

    /// 竖图收敛到最小 3:4，避免单图占满整屏（全图看详情/查看器）
    private func previewRatio(_ item: MediaItem) -> CGFloat {
        guard let w = item.width, let h = item.height, w > 0, h > 0 else { return 4 / 3 }
        return max(CGFloat(w) / CGFloat(h), 3 / 4)
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

/// Telegram 内嵌网页预览卡片；点击整卡打开链接（openURL 环境接管 → in-app Safari）
struct WebPagePreviewCard: View {
    let message: DisplayMessage
    let webpage: WebPagePreview

    @Environment(ReaderSession.self) private var reader
    @Environment(\.openURL) private var openURL

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
        .contentShape(RoundedRectangle(cornerRadius: 10))
        .onTapGesture {
            if let raw = webpage.url, let url = URL(string: raw) {
                openURL(url)
            }
        }
    }
}
