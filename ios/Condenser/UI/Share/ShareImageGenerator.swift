import SwiftUI
import UIKit
import CondenserKit

enum ShareImageError: LocalizedError {
    /// 一张图装不下（见 `maxPixelHeight`）。说「太长」而不是「失败」：
    /// 这是内容的属性，重试多少次都一样
    case tooTall(CGFloat)
    /// 带上量到的高度：没有它，「渲染失败」在一张长图上等于什么都没说
    case renderFailed(CGFloat)

    var errorDescription: String? {
        switch self {
        case let .tooTall(height):
            "这条内容太长了（约 \(Int(height / 800)) 屏），装不进一张图片"
        case let .renderFailed(height):
            "渲染失败（高度约 \(Int(height)) pt），请稍后再试"
        }
    }
}

/// 「生成图片并分享」的流程编排：预载卡片要用的图 → 渲染 → 落成临时文件。
///
/// 三条约束决定了这里的形状：
/// 1. `ImageRenderer` 是**同步一帧**，视图里出现任何 async 加载都渲不进去，
///    所以图必须先取好再注入（`prefetch`）；
/// 2. 预载不能无限等：每张图各自 5 秒上限、并发跑，到点还没到的渲染成占位块——
///    一张挂掉的图不该让整次分享失败，也不该让读者盯着转圈；
/// 3. 位图高度有平台上限（`maxPixelHeight`），所以是**先量后画**：量出来的高度
///    决定 scale，装不下的直接报「太长」，绝不进入光栅化——超限时那一步不会报错，
///    它会安静地给你一张全黑图。
@MainActor
enum ShareImageGenerator {
    /// 单张图的预载上限
    static let imageTimeout: Duration = .seconds(5)
    /// 位图高度的硬上限，2^13。**这是平台限制，不是设计选择**：同一张卡片
    /// 2026-08-23 在模拟器上逐级实测——800×6526px 内容正常、1200×9789px 出来是
    /// **一张全黑图**（`uiImage` 照样返回一个 UIImage，`pngData()` 返回 nil，
    /// JPEG 则给出一张黑的），中间没有任何报错。真机的纹理上限可能到 16384，
    /// 但按能验证到的数取值。
    static let maxPixelHeight: CGFloat = 8192
    /// 清晰度下限：再往下 400pt 宽的卡片连 1x 都不到，收图的人放大也读不了字
    static let minScale: CGFloat = 1
    /// 保险丝：一张图装不下（约十屏）就报错，而不是渲一张读不了的图出来
    static var maxHeight: CGFloat { maxPixelHeight / minScale }
    /// PNG 的适用范围。文字边缘干净是 PNG 的价值，但它对照片几乎不压缩：
    /// 一篇图多的长文 PNG 能到十几 MB，而 JPEG q0.9 是它的十分之一。
    /// 常见的卡片（TG / X / HN / 短文）都在这个高度内，走 PNG。
    static let pngPixelLimit = 4096

    /// 生成分享图并写进临时目录，返回文件 URL（分享结束后由调用方删除）
    static func makeFile(card: ShareCard, api: APIClient) async throws -> URL {
        let images = await prefetch(card.imageRefs, api: api)
        let renderer = ImageRenderer(content: ShareCardView(card: card, images: images))
        renderer.proposedSize = ProposedViewSize(width: ShareStyle.width, height: nil)
        renderer.isOpaque = true

        // 先只量尺寸（不给绘制回调，就不会有位图产生）。scale 不影响布局，所以
        // 量在设 scale 之前，量到的高度反过来决定 scale
        var measured = CGSize.zero
        renderer.render { size, _ in measured = size }
        guard measured.height <= maxHeight else { throw ShareImageError.tooTall(measured.height) }
        // 长文降清晰度而不是拒绝出图：忠实渲染全文是这个功能的要点，
        // 而「一篇长文分享不出去」比「这篇长文的字小一点」糟得多
        renderer.scale = min(ShareStyle.scale, maxPixelHeight / max(measured.height, 1))

        guard let image = renderer.uiImage, let encoded = encode(image) else {
            throw ShareImageError.renderFailed(measured.height)
        }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(card.fileBaseName)
            .appendingPathExtension(encoded.ext)
        try encoded.data.write(to: url, options: .atomic)
        return url
    }

    /// 优先 PNG（文字边缘干净），长图退 JPEG。`UIImage.pngData()` 在图变高之后
    /// 会直接返回 nil——而长图正是这个功能的常态，退 JPEG 是让长文分享得出去的
    /// 唯一办法，代价是文字边缘的一点点损失（scale 3 下看不出来）。
    private static func encode(_ image: UIImage) -> (data: Data, ext: String)? {
        let png = { image.pngData().map { ($0, "png") } }
        let jpeg = { image.jpegData(compressionQuality: 0.9).map { ($0, "jpg") } }
        let tall = (image.cgImage?.height ?? 0) > pngPixelLimit
        return tall ? (jpeg() ?? png()) : (png() ?? jpeg())
    }

    /// 分享面板关掉后删掉临时文件。删不掉也无所谓（系统会清临时目录），
    /// 所以这里不报错——它不是读者需要知道的事。
    static func discard(_ url: URL) {
        try? FileManager.default.removeItem(at: url)
    }

    /// 并发预载，逐张限时。返回的字典就是渲染时的查表依据：缺席 = 画占位块。
    private static func prefetch(
        _ refs: [ShareImageRef], api: APIClient
    ) async -> [ShareImageRef: UIImage] {
        guard !refs.isEmpty else { return [:] }
        return await withTaskGroup(of: (ShareImageRef, UIImage?).self) { group in
            for ref in refs {
                group.addTask {
                    (ref, await load(api.authedRequest(api.url(for: ref.source))))
                }
            }
            var images: [ShareImageRef: UIImage] = [:]
            for await (ref, image) in group {
                images[ref] = image
            }
            return images
        }
    }

    /// 一张图的加载与它的超时赛跑；谁先到用谁的结果
    private static func load(_ request: URLRequest) async -> UIImage? {
        await withTaskGroup(of: UIImage?.self) { group in
            group.addTask { try? await ImageLoader.shared.load(request) }
            group.addTask {
                try? await Task.sleep(for: imageTimeout)
                return nil
            }
            let first = await group.next() ?? nil
            group.cancelAll()
            return first
        }
    }
}

extension APIClient {
    /// 卡片里的图片说明书 → 带鉴权的后端 URL。分享图与阅读界面走同样的代理，
    /// 出一张图不会让源站看到读者的 IP。
    func url(for source: ShareImageSource) -> URL {
        switch source {
        case let .tgMedia(channelID, messageID, thumb):
            mediaURL(channelID: channelID, messageID: messageID, thumb: thumb)
        case let .channelAvatar(id):
            avatarURL(channelID: id)
        case let .xAvatar(handle):
            xAvatarURL(handle: handle)
        case let .proxied(raw):
            proxiedImageURL(raw)
        }
    }
}
