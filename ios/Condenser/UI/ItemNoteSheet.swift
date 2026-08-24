import CondenserKit
import SwiftUI

/// 条目评论抽屉：整条内容的一段 note（不是针对某段文字的高亮评论）。
/// 重开即编辑——预填现有 note，清空保存 = 删除（覆盖语义，没有单独删除按钮）。
///
/// 「转发」= 先落库再转发：note 先 POST 成功，再让父视图关掉本抽屉、带着这段
/// 文字打开 ForwardDialog——用户打了字只进 TG 没进笔记的惊讶感必须避免。
/// 转发弹窗里继续改文字只影响发出的消息，不回写 note。
struct ItemNoteSheet: View {
    let itemKey: String
    let initialNote: String
    /// note 已写进服务端（参数是新值，'' = 已清除）——父视图更新本地状态
    var onSaved: (String) -> Void
    /// 「转发」按钮：note 已保存，父视图切换到 ForwardDialog 并预填这段文字
    var onForward: (String) -> Void

    @Environment(ReaderSession.self) private var reader
    @Environment(\.dismiss) private var dismiss

    @State private var text: String
    @State private var sending = false
    @State private var errorText: String?

    init(
        itemKey: String, initialNote: String,
        onSaved: @escaping (String) -> Void, onForward: @escaping (String) -> Void
    ) {
        self.itemKey = itemKey
        self.initialNote = initialNote
        self.onSaved = onSaved
        self.onForward = onForward
        _text = State(initialValue: initialNote)
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                TextEditor(text: $text)
                    .frame(minHeight: 120, maxHeight: 200)
                    .padding(6)
                    .background(Color(.systemGray6), in: RoundedRectangle(cornerRadius: 10))
                    .overlay(alignment: .topLeading) {
                        if text.isEmpty {
                            Text(initialNote.isEmpty ? "对这条内容写点什么…" : "清空保存 = 删除评论")
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
                HStack(spacing: 10) {
                    Button {
                        submit(thenForward: false)
                    } label: {
                        if sending {
                            ProgressView().frame(maxWidth: .infinity)
                        } else {
                            Text("保存").frame(maxWidth: .infinity)
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    Button {
                        submit(thenForward: true)
                    } label: {
                        Label("转发", systemImage: "arrowshape.turn.up.forward")
                    }
                    .buttonStyle(.bordered)
                    // 空评论没有可预填的东西，直接用转发按钮就好
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                .disabled(sending)
                Spacer(minLength: 0)
            }
            .padding(16)
            .navigationTitle("条目评论")
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

    private func submit(thenForward: Bool) {
        errorText = nil
        sending = true
        let note = text.trimmingCharacters(in: .whitespacesAndNewlines)
        Task {
            do {
                try await reader.api.setNote(key: itemKey, note: note)
                onSaved(note)
                if thenForward {
                    onForward(note)
                } else {
                    dismiss()
                }
            } catch {
                errorText = note.isEmpty ? "删除失败，请重试" : "保存失败，请重试"
            }
            sending = false
        }
    }
}
