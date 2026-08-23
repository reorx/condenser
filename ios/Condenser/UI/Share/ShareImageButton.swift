import SwiftUI
import CondenserKit

/// 详情抽屉动作行行尾的「分享图片」：把这条内容渲成一张长图，交给系统分享面板。
///
/// 为什么是图不是链接：这个 app 连的是自托管实例，链接对外没有意义；而截屏只能截到
/// 一屏，长文分享出去总是半截。图是唯一能把「一条完整内容」原样递给别人的形态。
///
/// 点了才生成（预载图片 + 渲染要几百毫秒到几秒），期间按钮原地转圈并禁用。
struct ShareImageButton: View {
    /// nil = 这条还没准备好（RSS 的全文尚未到手）。按钮照画但按不动——
    /// 让人按下去拿到半篇文章，比让他多等一秒糟得多。
    let card: ShareCard?

    @Environment(ReaderSession.self) private var reader

    @State private var busy = false
    @State private var errorText: String?
    @State private var showError = false

    var body: some View {
        Button(action: generate) {
            Label {
                Text(busy ? "生成中…" : "分享图片")
            } icon: {
                if busy {
                    ProgressView().controlSize(.mini)
                } else {
                    Image(systemName: "square.and.arrow.up")
                }
            }
            .font(.footnote)
        }
        .buttonStyle(.bordered)
        .disabled(busy || card == nil)
        .alert("生成分享图失败", isPresented: $showError) {
            Button("好", role: .cancel) {}
        } message: {
            Text(errorText ?? "")
        }
        #if DEBUG
        // CLI 走查（SIMCTL_CHILD_CONDENSER_DEBUG_SHARE=1）：抽屉一出现就自动按这个按钮。
        // 动作行是横向滚动的，分享按钮排在行尾，模拟器窗口又收不到合成手势——
        // 没有这个入口，出图这件事只能靠人在真机上点。走完真实流程（预载 → 渲染 →
        // 分享面板），生成的 PNG 留在 app 容器的临时目录里，拿得出来逐像素看。
        // `id:` 是必须的：RSS 的 card 要等全文到手才从 nil 变出来，而 task 闭包捕获的是
        // **当时那个** struct 实例的 card——不给 id 的话它永远看着 nil（踩过）
        .task(id: card?.key) {
            guard ProcessInfo.processInfo.environment["CONDENSER_DEBUG_SHARE"] == "1",
                  card != nil else { return }
            try? await Task.sleep(for: .seconds(1))
            generate()
        }
        #endif
    }

    @MainActor
    private func generate() {
        guard let card, !busy else { return }
        busy = true
        Task {
            do {
                let url = try await ShareImageGenerator.makeFile(card: card, api: reader.api)
                busy = false
                presentShareSheet(fileURL: url) { ShareImageGenerator.discard(url) }
            } catch {
                busy = false
                errorText = error.localizedDescription
                showError = true
            }
        }
    }
}
