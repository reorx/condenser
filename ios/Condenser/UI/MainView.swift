import SwiftUI

/// 登录后的主界面占位：phase 3 替换为 TabView（Timeline / 频道 / 收藏）。
struct MainView: View {
    @Environment(AuthSession.self) private var session

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 48))
                .foregroundStyle(.green)
            Text("已连接")
                .font(.title2.bold())
            if let host = session.serverURL?.host() {
                Text(host)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Button("登出", role: .destructive) {
                session.signOut()
            }
            .padding(.top, 24)
        }
    }
}
