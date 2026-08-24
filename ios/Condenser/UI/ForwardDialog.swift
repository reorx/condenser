import SwiftUI
import CondenserKit

/// 「转发到我的频道」sheet：评论输入 + 确认。Telegram 条目评论非空 → quote 新消息
/// （评论文字 + t.me 链接），留空 → 原生 forward；其他信源没有「原生转发」这回事，
/// 服务端把标题和链接渲染成一条新消息，留空就是只发这条。目标频道在设置页配置
/// （app_meta.forward_channel），未配置时引导去设置。
struct ForwardDialog: View {
    let itemKey: String
    /// 只影响文案：留空时到底是「原样转发」还是「只发标题和链接」，两件事不一样
    let isTelegram: Bool
    /// 预填评论（条目评论抽屉的「转发」入口）。在这里继续改只影响发出的消息，
    /// 不回写 note——note 在打开本弹窗之前已经落库。
    var initialComment: String? = nil
    #if DEBUG
    /// CLI 走查（debug 路由 forward/<item key>/<comment>）：就绪后自动填入并提交，
    /// "" = 不带评论。真实网络请求，真实落地目标频道。
    var debugAutoComment: String?
    #endif

    @Environment(ReaderSession.self) private var reader
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL

    private enum Phase: Equatable {
        case loading
        case notConfigured
        case ready
        case sending
        case done(link: String)
    }

    @State private var phase: Phase = .loading
    @State private var comment = ""
    @State private var errorText: String?

    var body: some View {
        NavigationStack {
            content
                .padding(16)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .navigationTitle("转发到我的频道")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("取消") { dismiss() }
                    }
                }
        }
        .presentationDetents([.medium])
        .presentationDragIndicator(.visible)
        .task {
            if let initialComment, comment.isEmpty {
                comment = initialComment
            }
            // 先确认目标频道已配置，未配置时直接引导，不必等提交才报 422
            if let meta = try? await reader.api.appMeta() {
                phase = meta.forwardChannel == nil ? .notConfigured : .ready
            } else {
                phase = .ready  // meta 拉不到就放行，由提交路径兜底报错
            }
            #if DEBUG
            if let auto = debugAutoComment, phase == .ready {
                comment = auto
                try? await Task.sleep(for: .seconds(1))
                submit()
            }
            #endif
        }
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .loading:
            ProgressView()
                .frame(maxWidth: .infinity)
                .padding(.top, 40)
        case .notConfigured:
            VStack(spacing: 12) {
                Image(systemName: "gearshape")
                    .font(.largeTitle)
                    .foregroundStyle(.secondary)
                Text("尚未配置目标频道")
                    .font(.headline)
                Text("请先在「设置」tab 的「转发」区块填写你的频道（@handle 或 t.me 链接）。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 32)
        case .ready, .sending:
            composer
        case .done(let link):
            VStack(spacing: 12) {
                Image(systemName: "checkmark.circle.fill")
                    .font(.largeTitle)
                    .foregroundStyle(.green)
                Text("已转发")
                    .font(.headline)
                HStack(spacing: 10) {
                    if let url = URL(string: link) {
                        Button {
                            openURL(url)
                        } label: {
                            Label("在 Telegram 打开", systemImage: "paperplane")
                                .font(.footnote)
                        }
                        .buttonStyle(.bordered)
                    }
                    Button("完成") { dismiss() }
                        .buttonStyle(.borderedProminent)
                        .font(.footnote)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 32)
        }
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(isTelegram
                ? "写上自己的看法会通过文字 + 链接引用的形式发布新消息。"
                : "写上自己的看法会和标题、链接一起发布成一条新消息。")
                .font(.footnote)
                .foregroundStyle(.secondary)
            TextEditor(text: $comment)
                .frame(minHeight: 96, maxHeight: 160)
                .padding(6)
                .background(Color(.systemGray6), in: RoundedRectangle(cornerRadius: 10))
                .overlay(alignment: .topLeading) {
                    if comment.isEmpty {
                        Text(isTelegram
                            ? "留空则原样转发（保留 Forwarded from 头）"
                            : "留空则只发标题和链接")
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
                submit()
            } label: {
                if phase == .sending {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                } else {
                    Text("确认转发")
                        .frame(maxWidth: .infinity)
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(phase == .sending)
        }
    }

    private func submit() {
        errorText = nil
        phase = .sending
        Task {
            do {
                let result = try await reader.api.forwardItem(key: itemKey, comment: comment)
                phase = .done(link: result.link)
            } catch {
                phase = .ready
                errorText = Self.errorMessage(error)
            }
        }
    }

    /// 后端错误 → 面向用户的中文提示（契约见 routers/messages.py）
    static func errorMessage(_ error: Error) -> String {
        switch error {
        case APIError.http(422, _):
            "尚未配置目标频道，请先在设置中填写"
        case APIError.http(404, _):
            "原消息不存在（可能已被删除）"
        case APIError.http(429, _):
            "操作太频繁，被 Telegram 限流，请稍后再试"
        case APIError.http(503, _):
            "Telegram 未连接，请在网页版重新登录"
        case APIError.http(_, let detail?):
            "转发失败：\(detail)"
        default:
            "转发失败，请稍后再试"
        }
    }
}
