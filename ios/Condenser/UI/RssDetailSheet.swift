import SwiftUI
import CondenserKit

/// feed 条目详情 bottom sheet：标题 + 来源信息 + 全文（文本块 + 图片块，链接可点、
/// 点图进全屏查看器）+ 收藏 / 转发 / 打开原文。
///
/// 卡片上截断的正文在这里给全的，所以这张 sheet 对 RSS 比对别的源更重要：
/// 很多 feed 直接把整篇文章发过来，读完根本不用出 app。
struct RssDetailSheet: View {
    let item: TimelineItem
    let entry: RssEntry
    var onToggleSaved: () -> Void

    @Environment(ReaderSession.self) private var reader

    @State private var safariItem: SafariItem?
    @State private var viewerItem: ImageViewerItem?
    /// 全文解析出的块序列。列表载荷只带约 500 字的摘录（2026-08-23），所以这张
    /// sheet 打开时单独取一次全文；nil = 还没到手，此时先显示摘录。
    @State private var articleBlocks: [RssBlock]?
    /// 取全文这件事有没有走完。与 `articleBlocks != nil` 不是一回事：只发标题+链接
    /// 的 feed 取回来也是空正文，那是成功，不是还在转圈。
    @State private var articleLoaded = false
    @State private var articleFailed = false
    @State private var annotations = ItemAnnotationsModel()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                Text(entry.displayTitle)
                    .font(.title3.weight(.semibold))
                    .frame(maxWidth: .infinity, alignment: .leading)
                metaLine
                // 摘要在上、全文在下，两样都给：卡片上只放得下一个，
                // 但读者点进来是要读文章的，不是要读它的转述
                // （摘要块刻意不接标注——生成物，模型一换就重写）
                if let summary = entry.summary, !summary.isEmpty {
                    summarySection(summary)
                }
                articleSection
                AnnotationFooterView(model: annotations)
                Divider()
                actions
            }
            .padding(16)
        }
        .task(id: entry.id) { await loadArticle() }
        .readingFontScale()
        .edgeSwipeToDismiss()
        .detailSheetPresentation()
        .externalLinks(safari: $safariItem)
        .sheet(item: $safariItem) { item in
            SafariView(url: item.url)
                .ignoresSafeArea()
        }
        .fullScreenCover(item: $viewerItem) { item in
            ImageViewerScreen(item: item)
        }
    }

    /// sheet 自己的按钮不走 openURL 环境（那是给子树用的，读到的是外层列表的
    /// 那份，Safari 会从这张 sheet 背后弹出来），所以直接调统一出口
    private func open(_ url: URL) {
        openExternalURL(url) { safariItem = SafariItem(url: $0) }
    }

    /// 正文区：全文到手前先给摘录——一段真的正文开头总比一块空白好读，
    /// 取失败了也就停在这段上，而不是把正文清空。
    /// HTML→块的解析在 `loadArticle` 里算一次存进 state，不放在 body 里：
    /// 那是一整篇的正则，SwiftUI 每次重渲染都会重跑一遍。
    @ViewBuilder
    private var articleSection: some View {
        if let blocks = articleBlocks, !blocks.isEmpty {
            // 标注的 block 下标数的是**文本块序列**（图块不占号）：图块的增删
            // 比文本块的重排常见得多，锚点提示能多活几次管线升级
            let textIndices = Self.textBlockIndices(blocks)
            ForEach(Array(blocks.enumerated()), id: \.offset) { index, block in
                switch block {
                case let .text(text):
                    AnnotatedTextView(text: text, block: textIndices[index] ?? 0, model: annotations)
                case let .image(image):
                    RssArticleImageView(image: image) {
                        openViewer(blocks, at: index)
                    }
                }
            }
        } else if let text = entry.contentText {
            // 摘录回落态：全文没到手，定位没有底本，高亮入口禁用（model.blocks
            // 仍是 nil），已有标注也不上色——摘录里的范围是错的
            SelectableTextView(text: text)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        if !articleLoaded {
            HStack(spacing: 6) {
                ProgressView().controlSize(.small)
                Text("正在加载全文…")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        } else if articleFailed {
            Text("正文加载失败")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    /// 快照里已经带全文的条目（改版前存下的收藏）直接解析，不必再问一次网络。
    /// 相对路径的图片按文章 link 解析成绝对 URL。
    private func loadArticle() async {
        // blocks 先给 nil：全文到手前高亮入口保持禁用（摘录不是定位底本）
        annotations.configure(item: item, api: reader.api, blocks: nil, usesBlocks: true)
        if let content = entry.content {
            articleBlocks = rssBlocks(fromHTML: content, baseURL: entry.articleURL)
            articleLoaded = true
            annotations.setBlocks(Self.textBlocks(articleBlocks))
            return
        }
        do {
            if let content = try await reader.api.rssEntry(id: entry.id).rss?.content {
                articleBlocks = rssBlocks(fromHTML: content, baseURL: entry.articleURL)
                annotations.setBlocks(Self.textBlocks(articleBlocks))
            }
        } catch {
            articleFailed = true
        }
        articleLoaded = true
    }

    /// 文本块字符串序列（标注的定位底本；图块不在其中）
    private static func textBlocks(_ blocks: [RssBlock]?) -> [String]? {
        guard let blocks else { return nil }
        let texts = blocks.compactMap { block -> String? in
            if case let .text(text) = block { text } else { nil }
        }
        return texts.isEmpty ? nil : texts
    }

    /// 全块下标 → 文本块下标（图块不占号）
    private static func textBlockIndices(_ blocks: [RssBlock]) -> [Int: Int] {
        var mapping: [Int: Int] = [:]
        var next = 0
        for (index, block) in blocks.enumerated() {
            if case .text = block {
                mapping[index] = next
                next += 1
            }
        }
        return mapping
    }

    /// 查看器收全文所有图片并从点中的那张起，所以在里面能左右翻
    private func openViewer(_ blocks: [RssBlock], at blockIndex: Int) {
        let urls = blocks.compactMap { block -> String? in
            guard case let .image(image) = block else { return nil }
            return image.src
        }
        let start = blocks[..<blockIndex].reduce(0) { count, block in
            if case .image = block { count + 1 } else { count }
        }
        viewerItem = ImageViewerItem(urls: urls, startIndex: start)
    }

    private var header: some View {
        HStack(spacing: 10) {
            RssGlyph(size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.feedLabel)
                    .font(.headline)
                    .lineLimit(1)
                if let published = entry.publishedAt {
                    Text("\(entry.author.map { "\($0) · " } ?? "")发布于 \(published.formatted(date: .abbreviated, time: .shortened))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer()
        }
    }

    /// 时间线位置只在它与声明时间不一致时才说——那正是 feed 报了个不可信时间戳
    /// （缺失，或未来）而后端把它钳住的时候，读者会奇怪这条为什么排在这里
    @ViewBuilder
    private var metaLine: some View {
        if entry.publishedAt == nil || entry.publishedAt != item.datetime {
            Label(
                "时间线位置 \(item.datetime.formatted(date: .abbreviated, time: .shortened))",
                systemImage: "clock.arrow.circlepath")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    /// 摘要与原文正文长得一样，所以装进引用块（与卡片同款）而不是混排在正文上方
    private func summarySection(_ text: String) -> some View {
        AiSummaryBlock {
            SelectableTextView(text: text)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var actions: some View {
        ItemActionRow {
            ItemActionButtons(item: item, onToggleSaved: onToggleSaved)
            if let url = entry.articleURL {
                Button {
                    open(url)
                } label: {
                    Label("打开原文", systemImage: "safari")
                        .font(.footnote)
                }
                .buttonStyle(.bordered)
            }
            ShareImageButton(card: shareCard)
        }
    }

    /// 分享图用的是**这张 sheet 取回来的全文**，不是列表载荷里那 500 字摘录。
    /// 全文还没到手时给 nil（按钮画出来但按不动）——让人按下去拿到半篇文章，
    /// 比让他多等一秒糟得多；取失败了则退回摘录，短，但分享得出去。
    private var shareCard: ShareCard? {
        guard articleLoaded else { return nil }
        return ShareCard.build(item: item, articleBlocks: articleBlocks)
    }
}

/// 正文里的一张图：宽度撑满内容列，先按 `<img>` 属性的纵横比（缺省 4:3）画骨架
/// 占位，加载完换成图片自己的天然比例淡入——属性在时两者一致不跳动，属性缺时
/// 只在此刻调整一次。图片走 /api/preview/image 代理，读一篇文章不会让源站看到
/// 读者的 IP（与推文媒体同一条规则）。
private struct RssArticleImageView: View {
    let image: RssImage
    var onTap: () -> Void

    @Environment(ReaderSession.self) private var reader

    @State private var loaded: UIImage?
    @State private var failed = false

    var body: some View {
        Group {
            if let loaded {
                Image(uiImage: loaded)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .transition(.opacity)
            } else {
                Color(.secondarySystemBackground)
                    .aspectRatio(placeholderRatio, contentMode: .fit)
                    .overlay {
                        if failed {
                            Image(systemName: "photo")
                                .foregroundStyle(.tertiary)
                        }
                    }
            }
        }
        .frame(maxWidth: .infinity)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .contentShape(RoundedRectangle(cornerRadius: 8))
        .onTapGesture {
            // 代理都取不回来的图，查看器里也只会失败一次，不如不开
            if !failed { onTap() }
        }
        .task(id: image.src) {
            failed = false
            do {
                let request = reader.api.authedRequest(reader.api.proxiedImageURL(image.src))
                let result = try await ImageLoader.shared.load(request)
                withAnimation(.easeIn(duration: 0.15)) { loaded = result }
            } catch {
                failed = true
            }
        }
    }

    private var placeholderRatio: CGFloat {
        guard let width = image.width, let height = image.height, width > 0, height > 0
        else { return 4 / 3 }
        return CGFloat(width) / CGFloat(height)
    }
}
