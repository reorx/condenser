import SwiftUI
import CondenserKit

/// 设置 tab：服务器地址/设备名只读展示、外观跟随系统、登出。
/// 服务端 token 吊销走 web 端设置页（spec：登出只清本地 Keychain）。
/// 自身不含 NavigationStack，由挂载点（tab / debug sheet）提供。
struct SettingsScreen: View {
    @Environment(AuthSession.self) private var auth
    @Environment(ReaderSession.self) private var reader

    @State private var confirmSignOut = false

    var body: some View {
        Form {
            Section("服务器") {
                LabeledContent("地址", value: auth.serverURL?.absoluteString ?? "—")
                LabeledContent("设备名", value: auth.deviceName ?? UIDevice.current.name)
            }
            Section {
                LabeledContent("主题", value: "跟随系统")
            } header: {
                Text("外观")
            }
            Section {
                Button("登出", role: .destructive) {
                    confirmSignOut = true
                }
                .frame(maxWidth: .infinity)
            } footer: {
                Text("登出仅清除本机 token；如需吊销设备授权，请在网页版设置中操作。")
            }
            Section {
                LabeledContent("版本", value: appVersion)
            }
        }
        .navigationTitle("设置")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog("确定登出？", isPresented: $confirmSignOut, titleVisibility: .visible) {
            Button("登出", role: .destructive) {
                Task {
                    await reader.readReporter.flushNow()
                    auth.signOut()
                }
            }
        }
    }

    private var appVersion: String {
        let short = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?"
        return "\(short) (\(build))"
    }
}
