import SwiftUI
import CondenserKit

/// 登录后的主界面：phase 3 为单 Timeline（NavigationStack）；
/// phase 4 扩展为 TabView（Timeline / 频道 / 收藏）。
struct MainView: View {
    @Environment(AuthSession.self) private var auth
    @State private var reader: ReaderSession?

    var body: some View {
        Group {
            if let reader {
                NavigationStack {
                    TimelineScreen()
                }
                .environment(reader)
            } else {
                ProgressView()
            }
        }
        .onAppear {
            guard reader == nil, let server = auth.serverURL, let token = auth.token else { return }
            reader = ReaderSession(server: server, token: token) { [weak auth] in
                auth?.handleUnauthorized()
            }
        }
    }
}
