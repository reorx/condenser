import SwiftUI
import CondenserKit

/// HN story 详情 bottom sheet：标题 + 提交信息 + self-post 正文（HTML 转纯文本，
/// 链接可点）+ 打开原文 / 打开评论 动作。
struct HnDetailSheet: View {
    let item: TimelineItem
    let story: HnStory
    var onToggleSaved: () -> Void

    @State private var safariItem: SafariItem?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                Text(story.title ?? "(untitled)")
                    .font(.title3.weight(.semibold))
                    .frame(maxWidth: .infinity, alignment: .leading)
                metaLine
                if let text = story.text, !text.isEmpty {
                    SelectableTextView(text: hnPlainText(fromHTML: text))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if let preview = story.preview, preview.error == nil,
                   preview.title != nil || preview.description != nil {
                    previewCard(preview)
                }
                Divider()
                actions
            }
            .padding(16)
        }
        .readingFontScale()
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
                safariItem = SafariItem(url: url)
            }
        }
    }

    private var actions: some View {
        ItemActionRow {
            ItemActionButtons(item: item, onToggleSaved: onToggleSaved)
            if let url = story.externalURL {
                Button {
                    safariItem = SafariItem(url: url)
                } label: {
                    Label("打开原文", systemImage: "safari")
                        .font(.footnote)
                }
                .buttonStyle(.bordered)
            }
            Button {
                safariItem = SafariItem(url: story.commentsURL)
            } label: {
                Label("HN 评论", systemImage: "bubble.left.and.bubble.right")
                    .font(.footnote)
            }
            .buttonStyle(.bordered)
        }
    }
}
