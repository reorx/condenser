import SwiftUI
import CondenserKit

/// feed 条目详情 bottom sheet：标题 + 来源信息 + 全文（HTML 转纯文本，链接可点）
/// + 收藏 / 转发 / 打开原文。
///
/// 卡片上截断的正文在这里给全的，所以这张 sheet 对 RSS 比对别的源更重要：
/// 很多 feed 直接把整篇文章发过来，读完根本不用出 app。
struct RssDetailSheet: View {
    let item: TimelineItem
    let entry: RssEntry
    var onToggleSaved: () -> Void

    @Environment(ReaderSession.self) private var reader

    @State private var safariItem: SafariItem?
    /// 全文的纯文本。列表载荷只带约 500 字的摘录（2026-08-23），所以这张 sheet
    /// 打开时单独取一次全文；nil = 还没到手，此时先显示摘录。
    @State private var articleText: String?
    /// 取全文这件事有没有走完。与 `articleText != nil` 不是一回事：只发标题+链接的
    /// feed 取回来也是空正文，那是成功，不是还在转圈。
    @State private var articleLoaded = false
    @State private var articleFailed = false

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
                if let summary = entry.summary, !summary.isEmpty {
                    summarySection(summary)
                }
                articleSection
                Divider()
                actions
            }
            .padding(16)
        }
        .task(id: entry.id) { await loadArticle() }
        .readingFontScale()
        .edgeSwipeToDismiss()
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .externalLinks(safari: $safariItem)
        .sheet(item: $safariItem) { item in
            SafariView(url: item.url)
                .ignoresSafeArea()
        }
    }

    /// sheet 自己的按钮不走 openURL 环境（那是给子树用的，读到的是外层列表的
    /// 那份，Safari 会从这张 sheet 背后弹出来），所以直接调统一出口
    private func open(_ url: URL) {
        openExternalURL(url) { safariItem = SafariItem(url: $0) }
    }

    /// 正文区：全文到手前先给摘录——一段真的正文开头总比一块空白好读，
    /// 取失败了也就停在这段上，而不是把正文清空。
    /// HTML→纯文本的解析在 `loadArticle` 里算一次存进 state，不放在 body 里：
    /// 那是一整篇的正则，SwiftUI 每次重渲染都会重跑一遍。
    @ViewBuilder
    private var articleSection: some View {
        if let text = articleText ?? entry.contentText {
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

    /// 快照里已经带全文的条目（改版前存下的收藏）直接用，不必再问一次网络。
    private func loadArticle() async {
        if let text = entry.articleText {
            articleText = text
            articleLoaded = true
            return
        }
        do {
            articleText = try await reader.api.rssEntry(id: entry.id).rss?.articleText
        } catch {
            articleFailed = true
        }
        articleLoaded = true
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
        }
    }
}
