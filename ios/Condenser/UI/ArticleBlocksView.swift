import SwiftUI
import CondenserKit

/// 文章全文的块序列渲染：文本块可高亮（标注），图片块撑满内容列、点开进全屏查看器。
/// RSS 详情与 X 长文详情共用（2026-09-16 从 `RssDetailSheet` 抽出）——两者的全文都是
/// 服务端给的 HTML，经 Kit 的 `articleBlocks(fromHTML:baseURL:)` 切块。
///
/// 块序列须由调用方**算一次存进 state** 再传进来：解析是一整篇的正则，放在 body 里
/// SwiftUI 每次重渲染都会重跑（2026-08-23 RSS 卡顿的另一半就是这个）。
///
/// body 是一个 `ForEach`，放进调用方的 `VStack` 里会被摊平成它的子视图，块与块之间
/// 沿用外层的间距——与抽出前直接写在 sheet 里的布局一致。
struct ArticleBlocksView: View {
    let blocks: [ArticleBlock]
    let annotations: ItemAnnotationsModel
    @Binding var viewerItem: ImageViewerItem?

    var body: some View {
        // 标注的 block 下标数的是**文本块序列**（图块不占号）：图块的增删
        // 比文本块的重排常见得多，锚点提示能多活几次管线升级
        let textIndices = Self.textBlockIndices(blocks)
        ForEach(Array(blocks.enumerated()), id: \.offset) { index, block in
            switch block {
            case let .text(text):
                AnnotatedTextView(text: text, block: textIndices[index] ?? 0, model: annotations)
            case let .image(image):
                ArticleImageView(image: image) {
                    viewerItem = Self.viewerItem(blocks, at: index)
                }
            }
        }
    }

    /// 文本块字符串序列（标注的定位底本；图块不在其中）
    static func textBlocks(_ blocks: [ArticleBlock]?) -> [String]? {
        guard let blocks else { return nil }
        let texts = blocks.compactMap { block -> String? in
            if case let .text(text) = block { text } else { nil }
        }
        return texts.isEmpty ? nil : texts
    }

    /// 全块下标 → 文本块下标（图块不占号）
    private static func textBlockIndices(_ blocks: [ArticleBlock]) -> [Int: Int] {
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
    private static func viewerItem(_ blocks: [ArticleBlock], at blockIndex: Int) -> ImageViewerItem {
        let urls = blocks.compactMap { block -> String? in
            guard case let .image(image) = block else { return nil }
            return image.src
        }
        let start = blocks[..<blockIndex].reduce(0) { count, block in
            if case .image = block { count + 1 } else { count }
        }
        return ImageViewerItem(urls: urls, startIndex: start)
    }
}

/// 正文里的一张图：宽度撑满内容列，先按 `<img>` 属性的纵横比（缺省 4:3）画骨架
/// 占位，加载完换成图片自己的天然比例淡入——属性在时两者一致不跳动，属性缺时
/// 只在此刻调整一次（X 长文的图服务端总会注入 width/height）。图片走
/// /api/preview/image 代理，读一篇文章不会让源站（或 X）看到读者的 IP，
/// 与推文媒体同一条规则。
struct ArticleImageView: View {
    let image: ArticleImage
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
