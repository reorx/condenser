import SwiftUI
import CondenserKit

/// fullScreenCover 的载体：一组照片 + 起始下标
struct ImageViewerItem: Identifiable {
    let channelID: Int
    let photos: [MediaItem]
    let startIndex: Int

    var id: String { "\(channelID)/\(photos.first?.messageID ?? 0)/\(startIndex)" }
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
                ForEach(Array(item.photos.enumerated()), id: \.element.messageID) { i, photo in
                    ZoomableAsyncImage(
                        request: reader.api.authedRequest(
                            reader.api.mediaURL(channelID: item.channelID, messageID: photo.messageID)))
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
