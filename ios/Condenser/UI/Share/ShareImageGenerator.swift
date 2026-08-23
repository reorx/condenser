import SwiftUI
import UIKit
import CondenserKit

enum ShareImageError: LocalizedError {
    /// 内容高得离谱（一篇几万字的长文）——与其在渲染时把内存打爆，不如说清楚
    case tooTall(CGFloat)
    case renderFailed

    var errorDescription: String? {
        switch self {
        case let .tooTall(height):
            "这条内容太长了（约 \(Int(height)) pt），生成的图片会大到没法分享"
        case .renderFailed:
            "渲染失败，请稍后再试"
        }
    }
}

/// 「生成图片并分享」的流程编排：预载卡片要用的图 → 渲染 → 落成临时 PNG。
///
/// 三条约束决定了这里的形状：
/// 1. `ImageRenderer` 是**同步一帧**，视图里出现任何 async 加载都渲不进去，
///    所以图必须先取好再注入（`prefetch`）；
/// 2. 预载不能无限等：每张图各自 5 秒上限、并发跑，到点还没到的渲染成占位块——
///    一张挂掉的图不该让整次分享失败，也不该让读者盯着转圈；
/// 3. 高度不封顶（忠实渲染全文），只留一道保险丝：先量一次，超过阈值直接报错，
///    不进入光栅化。
@MainActor
enum ShareImageGenerator {
    /// 单张图的预载上限
    static let imageTimeout: Duration = .seconds(5)
    /// 保险丝：`400 × 20000pt` 在 scale 3 下已是 1200 × 60000px 的位图（约 288MB）
    static let maxHeight: CGFloat = 20000

    /// 生成分享图并写进临时目录，返回文件 URL（分享结束后由调用方删除）
    static func makeFile(card: ShareCard, api: APIClient) async throws -> URL {
        let images = await prefetch(card.imageRefs, api: api)
        let renderer = ImageRenderer(content: ShareCardView(card: card, images: images))
        renderer.scale = ShareStyle.scale
        renderer.proposedSize = ProposedViewSize(width: ShareStyle.width, height: nil)
        renderer.isOpaque = true

        // 先只量尺寸（不给绘制回调，就不会有位图产生）
        var measured = CGSize.zero
        renderer.render { size, _ in measured = size }
        guard measured.height <= maxHeight else { throw ShareImageError.tooTall(measured.height) }

        guard let image = renderer.uiImage, let data = image.pngData() else {
            throw ShareImageError.renderFailed
        }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(card.fileName)
        try data.write(to: url, options: .atomic)
        return url
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
