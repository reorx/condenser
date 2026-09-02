import SwiftUI
import CondenserKit

/// HN story 详情 bottom sheet：标题 + 提交信息 + AI 摘要块（有则显示）+ self-post 正文
///（HTML 转纯文本，链接可点）+ 打开原文 / 打开评论 动作。
struct HnDetailSheet: View {
    let item: TimelineItem
    let story: HnStory
    var onToggleSaved: () -> Void

    @Environment(ReaderSession.self) private var reader
    @State private var safariItem: SafariItem?
    @State private var annotations = ItemAnnotationsModel()

    /// self-post 正文的**屏幕文本**——标注锚在它上面，渲染与定位必须同一份派生
    private var bodyText: String? {
        guard let text = story.text, !text.isEmpty else { return nil }
        return hnPlainText(fromHTML: text)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                Text(story.title ?? "(untitled)")
                    .font(.title3.weight(.semibold))
                    .frame(maxWidth: .infinity, alignment: .leading)
                metaLine
                // 摘要块在正文 / 预览卡之前：RssDetailSheet 的顺序。不可标注——机器的话
                if let summary = story.displaySummary {
                    AiSummaryBlock {
                        SelectableTextView(text: summary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                if let text = bodyText {
                    AnnotatedTextView(text: text, model: annotations)
                }
                if let preview = story.preview, preview.error == nil,
                   preview.title != nil || preview.description != nil {
                    previewCard(preview)
                }
                AnnotationFooterView(model: annotations)
                Divider()
                actions
            }
            .padding(16)
        }
        .readingFontScale()
        .task {
            // 外链 story 没有可标注文字（排除项兜底 = 条目级 note）：blocks = nil，
            // 高亮入口自然禁用
            annotations.configure(
                item: item, api: reader.api, blocks: bodyText.map { [$0] })
        }
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

    private var header: some View {
        HStack(spacing: 10) {
            HnGlyph(size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text("Hacker News")
                    .font(.headline)
                if let submitted = story.submittedAt {
                    Text("\(story.author.map { "\($0) · " } ?? "")提交于 \(submitted.formatted(date: .abbreviated, time: .shortened))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer()
        }
    }

    private var metaLine: some View {
        HStack(spacing: 10) {
            Label("\(story.score)", systemImage: "arrowtriangle.up")
                .labelStyle(CompactMetaLabelStyle())
            Label("\(story.commentsCount)", systemImage: "bubble.right")
                .labelStyle(CompactMetaLabelStyle())
            if let domain = story.domain {
                Text(domain).lineLimit(1)
            }
            if let rank = story.dayRank {
                Text("当日 #\(rank)").foregroundStyle(.orange)
            }
            Spacer(minLength: 0)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    /// ingest 预取的链接预览（有内容才展示）
    private func previewCard(_ preview: LinkPreview) -> some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 2)
                .fill(.tint)
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 2) {
                if let site = preview.siteName {
                    Text(site)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.tint)
                }
                if let title = preview.title {
                    Text(title)
                        .font(.caption.weight(.medium))
                        .lineLimit(2)
                }
                if let description = preview.description {
                    Text(description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(8)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10))
        .contentShape(RoundedRectangle(cornerRadius: 10))
        .onTapGesture {
            if let url = story.externalURL {
                open(url)
            }
        }
    }

    private var actions: some View {
        ItemActionRow {
            ItemActionButtons(item: item, onToggleSaved: onToggleSaved)
            if let url = story.externalURL {
                Button {
                    open(url)
                } label: {
                    Label("打开原文", systemImage: "safari")
                        .font(.footnote)
                }
                .buttonStyle(.bordered)
            }
            Button {
                open(story.commentsURL)
            } label: {
                Label("HN 评论", systemImage: "bubble.left.and.bubble.right")
                    .font(.footnote)
            }
            .buttonStyle(.bordered)
            ShareImageButton(card: ShareCard.build(item: item))
        }
    }
}
