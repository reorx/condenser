import SwiftUI
import CondenserKit

/// AsyncImage 的带认证版本：skeleton 占位 → 淡入；失败显示占位图标。
struct AuthedAsyncImage: View {
    let request: URLRequest
    var contentMode: ContentMode = .fill

    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
                    .transition(.opacity)
            } else {
                Rectangle()
                    .fill(Color(.secondarySystemBackground))
                if failed {
                    Image(systemName: "photo")
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .task(id: request.url) {
            failed = false
            do {
                let loaded = try await ImageLoader.shared.load(request)
                withAnimation(.easeIn(duration: 0.15)) { image = loaded }
            } catch {
                failed = true
            }
        }
    }
}

/// 频道头像：/api/channels/{id}/avatar，失败回退彩色首字母。
struct ChannelAvatarView: View {
    let channelID: Int
    let title: String
    var size: CGFloat = 36

    @Environment(ReaderSession.self) private var reader
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                fallbackColor
                Text(initial)
                    .font(.system(size: size * 0.45, weight: .semibold))
                    .foregroundStyle(.white)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .task(id: channelID) {
            image = try? await ImageLoader.shared.load(
                reader.api.authedRequest(reader.api.avatarURL(channelID: channelID)))
        }
    }

    private var initial: String {
        title.first.map(String.init)?.uppercased() ?? "#"
    }

    private var fallbackColor: Color {
        // 与 web 版一致的思路：按 id 稳定取色
        let palette: [Color] = [.blue, .green, .orange, .pink, .purple, .teal, .indigo, .red]
        return palette[abs(channelID) % palette.count]
    }
}
