import CondenserKit
import SwiftUI

/// 一个详情 sheet 的标注状态：条目的高亮列表 + 定位缓存 + 增删改的 API 调用。
/// 每张 sheet 建一份（`@State`），`configure` 在 `.task` 里喂初值——sheet 的
/// item 是列表 envelope 的值拷贝，之后的增删只改这里，列表下次刷新自然追平。
///
/// `blocks` 是**屏幕显示的派生文本**（X 经 t.co 替换、HN/RSS 经 HTML 管线），
/// 与 `locateAnnotation` 的约定一致；nil = 正文未就绪（RSS 全文没到手时的摘录
/// 回落态），此时高亮入口禁用、已有标注也不渲染——摘录里定位出来的范围是错的。
@MainActor
@Observable
final class ItemAnnotationsModel {
    private(set) var itemKey = ""
    private(set) var annotations: [ItemAnnotation] = []
    /// RSS 传 true：新高亮把所在文本块的下标一并存进锚点当搜索提示
    private(set) var usesBlocks = false
    var error: String?

    private var api: APIClient?
    private var blocks: [String]?
    private var configured = false
    /// 定位缓存：annotation id -> 结果（含「定位失败」）。定位是全文子串搜索，
    /// SwiftUI 每次重渲染都会来要 highlights，不缓存就是每帧一遍全文正则量级的活。
    private var resolved: [Int: AnnotationLocation?] = [:]

    func configure(item: TimelineItem, api: APIClient, blocks: [String]?, usesBlocks: Bool = false) {
        guard !configured else { return }
        configured = true
        itemKey = item.key
        annotations = item.annotations ?? []
        self.api = api
        self.blocks = blocks
        self.usesBlocks = usesBlocks
    }

    /// RSS 全文到手（或重取）后替换定位底本
    func setBlocks(_ blocks: [String]?) {
        self.blocks = blocks
        resolved = [:]
    }

    /// 高亮入口可用吗（选中菜单要不要插「高亮」项）
    var canHighlight: Bool { configured && api != nil && blocks != nil }

    func annotation(_ id: Int) -> ItemAnnotation? {
        annotations.first { $0.id == id }
    }

    /// 落在指定块里的高亮（喂给该块的 SelectableTextView）
    func highlights(forBlock index: Int) -> [TextHighlight] {
        guard let blocks else { return [] }
        return annotations.compactMap { annotation in
            guard let location = locate(annotation), location.block == index else { return nil }
            return TextHighlight(id: annotation.id, range: NSRange(location.range, in: blocks[index]))
        }
    }

    /// 正文里找不到的标注：正文不亮，但引文与评论在抽屉尾部保留可见，不静默丢数据
    var orphans: [ItemAnnotation] {
        guard blocks != nil else { return [] }
        return annotations.filter { locate($0) == nil }
    }

    private func locate(_ annotation: ItemAnnotation) -> AnnotationLocation? {
        if let cached = resolved[annotation.id] { return cached }
        let location = blocks.flatMap { locateAnnotation(annotation, in: $0) }
        resolved[annotation.id] = location
        return location
    }

    // MARK: 写路径（错误进 error 文案，UI 顶层展示）

    func addHighlight(_ context: TextSelectionContext, block: Int) async {
        guard let api else { return }
        do {
            let created = try await api.addAnnotation(
                key: itemKey, quote: context.quote, prefix: context.prefix,
                suffix: context.suffix, block: usesBlocks ? block : nil)
            annotations.append(created)
        } catch {
            self.error = "高亮失败，请重试"
        }
    }

    func deleteAnnotation(_ id: Int) async {
        guard let api else { return }
        let removed = annotations
        annotations.removeAll { $0.id == id }
        resolved[id] = nil
        do {
            try await api.deleteAnnotation(key: itemKey, id: id)
        } catch {
            annotations = removed
            self.error = "删除失败，请重试"
        }
    }

    /// 评论镜像 note 语义：整段覆盖，空串 = 清评论留高亮。抛错给评论抽屉自己展示。
    func saveComment(_ id: Int, comment: String) async throws {
        guard let api else { return }
        try await api.updateAnnotationComment(key: itemKey, id: id, comment: comment)
        if let index = annotations.firstIndex(where: { $0.id == id }) {
            annotations[index].comment = comment.isEmpty ? nil : comment
        }
    }
}

/// 卡片头部的批注角标：这条有 note 或高亮（星 = 收藏，这个 = 写过东西——
/// 收藏列表因 v18 会列出「只标注未收藏」的行，没有它们就分不出来）。
/// 只是记号不是按钮：入口在详情 sheet 里。
struct AnnotationBadge: View {
    let item: TimelineItem

    var body: some View {
        if item.hasNotes {
            Image(systemName: "text.bubble.fill")
                .font(.caption)
                .foregroundStyle(.indigo.opacity(0.7))
        }
    }
}

/// 详情 sheet 正文块的标注宿主：包一层 SelectableTextView，接上高亮渲染、
/// 「高亮」菜单项、点高亮的「评论/删除」，以及评论小抽屉。四个源的 sheet 共用。
struct AnnotatedTextView: View {
    let text: String
    var urlEntities: [XUrlEntity]? = nil
    var block: Int = 0
    let model: ItemAnnotationsModel

    @State private var commentTarget: ItemAnnotation?

    var body: some View {
        SelectableTextView(
            text: text,
            urlEntities: urlEntities,
            highlights: model.highlights(forBlock: block),
            onHighlightSelection: model.canHighlight
                ? { context in Task { await model.addHighlight(context, block: block) } }
                : nil,
            onAnnotationComment: { id in commentTarget = model.annotation(id) },
            onAnnotationDelete: { id in Task { await model.deleteAnnotation(id) } })
            .frame(maxWidth: .infinity, alignment: .leading)
            .sheet(item: $commentTarget) { annotation in
                AnnotationCommentSheet(
                    quote: annotation.quote,
                    initialComment: annotation.comment ?? ""
                ) { text in
                    try await model.saveComment(annotation.id, comment: text)
                }
            }
    }
}

/// 抽屉尾部的孤儿高亮列表 + 标注层的错误行。正文改版后引文可能再也搜不到，
/// 但那是用户写下的东西——展示引文与评论，给一个删除的出口，绝不静默扔掉。
struct AnnotationFooterView: View {
    let model: ItemAnnotationsModel

    var body: some View {
        if let error = model.error {
            Text(error)
                .font(.caption)
                .foregroundStyle(.red)
        }
        let orphans = model.orphans
        if !orphans.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Label("失效的高亮（原文已变，引文保留）", systemImage: "highlighter")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                ForEach(orphans) { annotation in
                    HStack(alignment: .top, spacing: 8) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(annotation.quote)
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                                .padding(6)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(
                                    Color.yellow.opacity(0.18),
                                    in: RoundedRectangle(cornerRadius: 6))
                            if let comment = annotation.comment, !comment.isEmpty {
                                Text(comment)
                                    .font(.footnote)
                            }
                        }
                        Button {
                            Task { await model.deleteAnnotation(annotation.id) }
                        } label: {
                            Image(systemName: "trash")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }
}

/// 高亮的评论小抽屉：顶部引文 + 输入框 + 确认。预填现有评论，清空确认 = 删评论
/// 留高亮（与条目 note 同一套覆盖语义）。
struct AnnotationCommentSheet: View {
    let quote: String
    let initialComment: String
    let submit: (String) async throws -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var text: String
    @State private var sending = false
    @State private var errorText: String?

    init(quote: String, initialComment: String, submit: @escaping (String) async throws -> Void) {
        self.quote = quote
        self.initialComment = initialComment
        self.submit = submit
        _text = State(initialValue: initialComment)
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                Text(quote)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .lineLimit(4)
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.yellow.opacity(0.18), in: RoundedRectangle(cornerRadius: 8))
                TextEditor(text: $text)
                    .frame(minHeight: 96, maxHeight: 160)
                    .padding(6)
                    .background(Color(.systemGray6), in: RoundedRectangle(cornerRadius: 10))
                    .overlay(alignment: .topLeading) {
                        if text.isEmpty {
                            Text(initialComment.isEmpty ? "对这段高亮写点什么…" : "清空保存 = 删除评论（高亮保留）")
                                .font(.footnote)
                                .foregroundStyle(.tertiary)
                                .padding(.top, 14)
                                .padding(.leading, 11)
                                .allowsHitTesting(false)
                        }
                    }
                if let errorText {
                    Text(errorText)
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
                Button {
                    confirm()
                } label: {
                    if sending {
                        ProgressView().frame(maxWidth: .infinity)
                    } else {
                        Text("确认").frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(sending)
                Spacer(minLength: 0)
            }
            .padding(16)
            .navigationTitle("高亮评论")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium])
        .presentationDragIndicator(.visible)
    }

    private func confirm() {
        errorText = nil
        sending = true
        Task {
            do {
                try await submit(text.trimmingCharacters(in: .whitespacesAndNewlines))
                dismiss()
            } catch {
                errorText = "保存失败，请重试"
            }
            sending = false
        }
    }
}
