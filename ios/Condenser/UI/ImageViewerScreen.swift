import SwiftUI
import CondenserKit

/// 查看器里的一张图：TG 走按消息寻址的媒体代理，X 走通用图片代理
/// （两者都带 Bearer，浏览器/客户端从不直连源站）
enum ViewerPhoto: Hashable {
    case telegram(channelID: Int, messageID: Int)
    case proxied(url: String)

    var key: String {
        switch self {
        case let .telegram(channelID, messageID): "tg/\(channelID)/\(messageID)"
        case let .proxied(url): url
        }
    }
}

/// fullScreenCover 的载体：一组照片 + 起始下标
struct ImageViewerItem: Identifiable {
    let photos: [ViewerPhoto]
    let startIndex: Int

    var id: String { "\(photos.first?.key ?? "")/\(startIndex)" }

    /// TG 相册：按消息 id 寻址
    init(channelID: Int, photos: [MediaItem], startIndex: Int) {
        self.photos = photos.map { .telegram(channelID: channelID, messageID: $0.messageID) }
        self.startIndex = startIndex
    }

    /// 推文媒体：原始 URL 交给服务端代理
    init(urls: [String], startIndex: Int) {
        photos = urls.map { .proxied(url: $0) }
        self.startIndex = startIndex
    }
}

/// 全屏图片浏览器：TabView(.page) 多图切换 + UIScrollView 双指缩放（双击切换）+
/// 未缩放时下滑关闭。图片走 ImageLoader（带 Bearer header、URLCache 磁盘缓存）。
struct ImageViewerScreen: View {
    let item: ImageViewerItem

    @Environment(ReaderSession.self) private var reader
    @Environment(\.dismiss) private var dismiss

    @State private var index: Int
    @State private var dragOffset: CGFloat = 0

    init(item: ImageViewerItem) {
        self.item = item
        _index = State(initialValue: item.startIndex)
    }

    var body: some View {
        ZStack {
            Color.black
                .opacity(backdropOpacity)
                .ignoresSafeArea()
            TabView(selection: $index) {
                ForEach(Array(item.photos.enumerated()), id: \.element.key) { i, photo in
                    ZoomableAsyncImage(request: reader.api.authedRequest(url(for: photo)))
                        .tag(i)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: item.photos.count > 1 ? .automatic : .never))
            .offset(y: dragOffset)
        }
        .overlay(alignment: .topTrailing) {
            Button {
                dismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(10)
                    .background(.black.opacity(0.4), in: Circle())
            }
            .padding(.trailing, 16)
        }
        // 未缩放时 UIScrollView 不消费竖向 pan，这里接管纵向为主的下拉手势
        .simultaneousGesture(
            DragGesture()
                .onChanged { value in
                    guard value.translation.height > 0,
                          abs(value.translation.height) > abs(value.translation.width)
                    else { return }
                    dragOffset = value.translation.height
                }
                .onEnded { value in
                    if dragOffset > 120 || value.predictedEndTranslation.height > 300 {
                        dismiss()
                    } else {
                        withAnimation(.spring(duration: 0.3)) { dragOffset = 0 }
                    }
                }
        )
        .statusBarHidden()
        .presentationBackground(.clear)
    }

    private var backdropOpacity: Double {
        max(0.4, 1 - Double(dragOffset) / 500)
    }

    private func url(for photo: ViewerPhoto) -> URL {
        switch photo {
        case let .telegram(channelID, messageID):
            reader.api.mediaURL(channelID: channelID, messageID: messageID)
        case let .proxied(raw):
            reader.api.proxiedImageURL(raw)
        }
    }
}

/// 先加载 UIImage（authed），完成后交给 ZoomableImageView 缩放展示。
private struct ZoomableAsyncImage: View {
    let request: URLRequest

    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        ZStack {
            if let image {
                ZoomableImageView(image: image)
            } else if failed {
                Image(systemName: "photo")
                    .font(.largeTitle)
                    .foregroundStyle(.white.opacity(0.5))
            } else {
                ProgressView().tint(.white)
            }
        }
        .task(id: request.url) {
            failed = false
            do {
                image = try await ImageLoader.shared.load(request)
            } catch {
                failed = true
            }
        }
    }
}

/// UIScrollView + UIImageView 的经典缩放容器：捏合 1x–4x，双击在 1x/2.5x 间切换。
private struct ZoomableImageView: UIViewRepresentable {
    let image: UIImage

    func makeUIView(context: Context) -> UIScrollView {
        let scrollView = UIScrollView()
        scrollView.minimumZoomScale = 1
        scrollView.maximumZoomScale = 4
        scrollView.showsHorizontalScrollIndicator = false
        scrollView.showsVerticalScrollIndicator = false
        scrollView.backgroundColor = .clear
        scrollView.delegate = context.coordinator
        scrollView.contentInsetAdjustmentBehavior = .never

        let imageView = UIImageView(image: image)
        imageView.contentMode = .scaleAspectFit
        imageView.frame = scrollView.bounds
        imageView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        scrollView.addSubview(imageView)
        context.coordinator.imageView = imageView

        let doubleTap = UITapGestureRecognizer(
            target: context.coordinator, action: #selector(Coordinator.handleDoubleTap(_:)))
        doubleTap.numberOfTapsRequired = 2
        scrollView.addGestureRecognizer(doubleTap)
        return scrollView
    }

    func updateUIView(_ scrollView: UIScrollView, context: Context) {
        context.coordinator.imageView?.image = image
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, UIScrollViewDelegate {
        weak var imageView: UIImageView?

        func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }

        @objc func handleDoubleTap(_ gesture: UITapGestureRecognizer) {
            guard let scrollView = gesture.view as? UIScrollView else { return }
            if scrollView.zoomScale > 1 {
                scrollView.setZoomScale(1, animated: true)
            } else {
                let point = gesture.location(in: imageView)
                let size = CGSize(
                    width: scrollView.bounds.width / 2.5,
                    height: scrollView.bounds.height / 2.5)
                scrollView.zoom(
                    to: CGRect(
                        x: point.x - size.width / 2, y: point.y - size.height / 2,
                        width: size.width, height: size.height),
                    animated: true)
            }
        }
    }
}
