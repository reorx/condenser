import SwiftUI
import CondenserKit

/// 分享图的外观常量。**固定浅色、固定字号**：这张图是给收图的人看的，
/// 不该继承分享者的主题与阅读字号设定（`readingFontScale` 在这里刻意不生效）。
///
/// 颜色一律写死，不用 `Color(.secondarySystemBackground)` 这类 UIKit 动态色：
/// `ImageRenderer` 解析动态色走的是进程当前的 trait collection，深色模式下渲出来
/// 会是深底浅字——而 SwiftUI 的 `\.colorScheme` 环境未必管得到 UIKit 那一侧。
/// 两道保险都上：环境强制 light，颜色本身也是常量。
enum ShareStyle {
    /// 卡片宽度（pt）。`scale = 3` → 约 1200px 宽，够手机与桌面看，不至于几 MB
    static let width: CGFloat = 400
    static let scale: CGFloat = 3
    static let padding: CGFloat = 16
    static let spacing: CGFloat = 14
    static var contentWidth: CGFloat { width - padding * 2 }

    static let background = Color.white
    static let label = Color(red: 0.05, green: 0.05, blue: 0.06)
    static let secondary = Color(white: 0.42)
    static let tertiary = Color(white: 0.60)
    /// ≈ 浅色下的 secondarySystemBackground
    static let fill = Color(red: 0.949, green: 0.949, blue: 0.969)
    static let separator = Color(white: 0.87)
    /// ≈ 浅色下的 systemBlue（链接高亮与预览卡的竖条）
    static let accent = Color(red: 0.0, green: 0.478, blue: 1.0)

    /// 字母头像的取色盘，与 app 里的 `ChannelAvatarView` / `XAvatarView` 同一份
    static let avatarPalette: [Color] = [.blue, .green, .orange, .pink, .purple, .teal, .indigo, .red]
}

/// 一条 item 的分享长图。**纯 SwiftUI**：`ImageRenderer` 不渲染 UIKit 桥接视图
/// （抽屉正文用的 `SelectableTextView` 就是一个），也不会等异步加载——所以正文一律
/// `Text`，图片一律用调用方预载好的 `UIImage` 注入，视图里没有任何 async 路径。
///
/// 四个信源共用这一个渲染器：内容的取舍在 Kit 的 `ShareCard` 里做完了
/// （那里有测试盯着），这里只负责把块序列画出来，四个源的观感因此不会各自漂移。
struct ShareCardView: View {
    let card: ShareCard
    /// 预载结果；缺的图画占位块（不整体失败）
    let images: [ShareImageRef: UIImage]

    var body: some View {
        VStack(alignment: .leading, spacing: ShareStyle.spacing) {
            header
            if let headline = card.headline {
                Text(headline)
                    .font(.title3.weight(.semibold))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            ForEach(Array(card.blocks.enumerated()), id: \.offset) { _, block in
                blockView(block)
            }
            footer
        }
        .padding(ShareStyle.padding)
        .frame(width: ShareStyle.width, alignment: .leading)
        .background(ShareStyle.background)
        .foregroundStyle(ShareStyle.label)
        .tint(ShareStyle.accent)
        .environment(\.colorScheme, .light)
        .dynamicTypeSize(.large)
    }

    private var header: some View {
        HStack(spacing: 10) {
            ShareAvatarView(avatar: card.avatar, images: images, size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(card.title)
                    .font(.headline)
                    .lineLimit(1)
                if let subtitle = card.subtitle {
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(ShareStyle.secondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
    }

    private func metaLine(_ items: [ShareMeta]) -> some View {
        HStack(spacing: 10) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, meta in
                switch meta {
                case let .text(text):
                    Text(text).lineLimit(1)
                default:
                    Label("\(meta.value ?? 0)", systemImage: meta.symbol ?? "circle")
                        .labelStyle(CompactMetaLabelStyle())
                }
            }
            Spacer(minLength: 0)
        }
        .font(.caption)
        .foregroundStyle(ShareStyle.secondary)
    }

    @ViewBuilder
    private func blockView(_ block: ShareBlock) -> some View {
        switch block {
        case let .text(text):
            Text(linkified(text))
                .font(.body)
                .frame(maxWidth: .infinity, alignment: .leading)
        case let .meta(items):
            metaLine(items)
        case let .image(ref):
            ShareImageBox(ref: ref, images: images, cornerRadius: 10)
        case let .imageGrid(refs):
            grid(refs)
        case let .summary(text):
            AiSummaryBlock {
                Text(text)
                    .font(.body)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        case let .quote(quote):
            quoteCard(quote)
        case let .linkCard(link):
            linkCard(link)
        case let .fileChip(label):
            Label(label, systemImage: "doc.fill")
                .font(.caption)
                .foregroundStyle(ShareStyle.secondary)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(ShareStyle.fill, in: Capsule())
        case let .note(text):
            Text(text)
                .font(.caption)
                .foregroundStyle(ShareStyle.secondary)
        }
    }

    /// 多图方格。宽度是定死的，所以格子边长直接算出来——`LazyVGrid` 在
    /// `ImageRenderer` 这种一次性布局里没有好处，非惰性的固定尺寸更可控。
    private func grid(_ refs: [ShareImageRef]) -> some View {
        let columns = refs.count == 2 || refs.count == 4 ? 2 : 3
        let spacing: CGFloat = 4
        let side = (ShareStyle.contentWidth - spacing * CGFloat(columns - 1)) / CGFloat(columns)
        let rows = stride(from: 0, to: refs.count, by: columns).map {
            Array(refs[$0..<min($0 + columns, refs.count)])
        }
        return VStack(alignment: .leading, spacing: spacing) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(spacing: spacing) {
                    ForEach(Array(row.enumerated()), id: \.offset) { _, ref in
                        ShareImageBox(ref: ref, images: images, cornerRadius: 6, square: side)
                    }
                }
            }
        }
    }

    /// 内嵌的被引推：与 app 里的 `XQuoteCard` 同一套视觉语言（缩进的软背景卡）
    private func quoteCard(_ quote: ShareQuote) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                ShareAvatarView(avatar: quote.avatar, images: images, size: 18)
                Text(quote.name)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                if let handle = quote.handle {
                    Text("@\(handle)")
                        .font(.caption2)
                        .foregroundStyle(ShareStyle.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            if let text = quote.text {
                Text(text)
                    .font(.caption)
                    .lineLimit(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let image = quote.image {
                ShareImageBox(ref: image, images: images, cornerRadius: 8, maxHeight: 160)
            }
        }
        .padding(10)
        .background(ShareStyle.fill, in: RoundedRectangle(cornerRadius: 10))
    }

    /// 链接预览卡（TG 的网页预览 / HN 的预取元数据 / X 长文）
    private func linkCard(_ link: ShareLinkCard) -> some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 2)
                .fill(ShareStyle.accent)
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 2) {
                if let site = link.site {
                    Text(site)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ShareStyle.accent)
                }
                if let title = link.title {
                    Text(title)
                        .font(.caption.weight(.medium))
                        .lineLimit(3)
                }
                if let description = link.description {
                    Text(description)
                        .font(.caption)
                        .foregroundStyle(ShareStyle.secondary)
                        .lineLimit(4)
                }
            }
            Spacer(minLength: 0)
            if let image = link.image, let loaded = images[image] {
                Image(uiImage: loaded)
                    .resizable()
                    .scaledToFill()
                    .frame(width: 48, height: 48)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }
        }
        .padding(8)
        .background(ShareStyle.fill, in: RoundedRectangle(cornerRadius: 10))
    }

    /// 落款：左边是这张图从哪个 app 出来的，右边是它的出处（域名或时间）。
    /// 不放二维码/链接——自托管实例的地址对外没有意义，原文链接该在内容里。
    private var footer: some View {
        VStack(spacing: 8) {
            Rectangle()
                .fill(ShareStyle.separator)
                .frame(height: 0.5)
            HStack(spacing: 6) {
                Image("ShareMark")
                    .resizable()
                    .frame(width: 16, height: 16)
                    .clipShape(RoundedRectangle(cornerRadius: 4))
                Text("Condenser")
                    .font(.caption2.weight(.semibold))
                Spacer(minLength: 8)
                if let footnote = card.footnote {
                    Text(footnote)
                        .font(.caption2)
                        .lineLimit(1)
                }
            }
            .foregroundStyle(ShareStyle.tertiary)
        }
    }
}

private extension ShareMeta {
    var value: Int? {
        switch self {
        case let .score(n), let .comments(n), let .likes(n), let .retweets(n), let .replies(n): n
        case .text: nil
        }
    }

    /// 语义 → 图标，与卡片/抽屉里用的是同一套符号
    var symbol: String? {
        switch self {
        case .score: "arrowtriangle.up"
        case .comments, .replies: "bubble.right"
        case .likes: "heart"
        case .retweets: "arrow.2.squarepath"
        case .text: nil
        }
    }
}

/// 卡片里的一张图：取到了就画图，没取到（超时 / 404 / 超出预载上限）画灰色占位块。
/// 占位块沿用后端给的纵横比（缺省 4:3），所以缺一张图不会让版面塌掉。
private struct ShareImageBox: View {
    let ref: ShareImageRef
    let images: [ShareImageRef: UIImage]
    var cornerRadius: CGFloat = 10
    /// 方格模式：固定边长的正方形
    var square: CGFloat?
    var maxHeight: CGFloat?

    var body: some View {
        Group {
            if let loaded = images[ref] {
                if let square {
                    Image(uiImage: loaded)
                        .resizable()
                        .scaledToFill()
                        .frame(width: square, height: square)
                } else {
                    Image(uiImage: loaded)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                }
            } else {
                ShareStyle.fill
                    .aspectRatio(square != nil ? 1 : ratio, contentMode: .fit)
                    .frame(width: square, height: square)
                    .overlay {
                        Image(systemName: "photo")
                            .foregroundStyle(ShareStyle.tertiary)
                    }
            }
        }
        // maxHeight 要罩住两个分支：只罩住「取到了」那支的话，引用推里缺的那张图
        // 会画出一块比真图高得多的灰块
        .frame(maxWidth: square ?? .infinity, maxHeight: maxHeight)
        .clipShape(RoundedRectangle(cornerRadius: cornerRadius))
    }

    private var ratio: CGFloat {
        ref.aspectRatio.map { CGFloat($0) } ?? 4 / 3
    }
}

/// 头像位：预载到了画图，没有就画字母头像（取色规则与 app 内一致），
/// 信源本身没有头像的画信源标记。
private struct ShareAvatarView: View {
    let avatar: ShareAvatar
    let images: [ShareImageRef: UIImage]
    var size: CGFloat = 40

    var body: some View {
        switch avatar {
        case let .remote(ref, initial, seed):
            if let loaded = images[ref] {
                Image(uiImage: loaded)
                    .resizable()
                    .scaledToFill()
                    .frame(width: size, height: size)
                    .clipShape(Circle())
            } else {
                letter(initial, seed: seed)
            }
        case let .letter(initial, seed):
            letter(initial, seed: seed)
        case let .glyph(glyph):
            ShareGlyphView(glyph: glyph, size: size)
        }
    }

    private func letter(_ initial: String, seed: Int) -> some View {
        ZStack {
            ShareStyle.avatarPalette[abs(seed) % ShareStyle.avatarPalette.count]
            Text(initial)
                .font(.system(size: size * 0.45, weight: .semibold))
                .foregroundStyle(.white)
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
    }
}

/// 信源标记。刻意不复用 `HnGlyph` / `XGlyph` / `RssGlyph`：那三个里有
/// `Color.primary` 与 `Color(.systemBackground)`，在离屏渲染里可能按深色解析
/// （X 的方块会变成白底黑字）。分享图的外观必须是定死的，所以颜色在这里写死。
private struct ShareGlyphView: View {
    let glyph: ShareGlyph
    var size: CGFloat = 40

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.22)
            .fill(fill)
            .frame(width: size, height: size)
            .overlay { symbol }
    }

    private var fill: Color {
        switch glyph {
        case .hn: Color(red: 1.0, green: 0.4, blue: 0.0)
        case .x: Color(red: 0.05, green: 0.05, blue: 0.06)
        case .rss: Color(red: 0.96, green: 0.62, blue: 0.04)
        }
    }

    @ViewBuilder
    private var symbol: some View {
        switch glyph {
        case .hn:
            Text("Y")
                .font(.system(size: size * 0.55, weight: .bold))
                .foregroundStyle(.white)
        case .x:
            Text("𝕏")
                .font(.system(size: size * 0.6))
                .foregroundStyle(.white)
        case .rss:
            Image(systemName: "dot.radiowaves.up.forward")
                .font(.system(size: size * 0.48, weight: .bold))
                .foregroundStyle(.white)
        }
    }
}
