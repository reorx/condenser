import SwiftUI
import AuthenticationServices
import CondenserKit

/// 首启登录页：服务器地址 + 设备名 → ASWebAuthenticationSession 打开
/// <server>/authorize，回调 condenser://auth 换 device token。
struct LoginView: View {
    @Environment(AuthSession.self) private var session
    @Environment(\.webAuthenticationSession) private var webAuthenticationSession

    @State private var serverAddress = "https://condenser.reorx.com"
    @State private var deviceName = UIDevice.current.name
    @State private var errorMessage: String?
    @State private var isAuthorizing = false

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            VStack(spacing: 8) {
                Image(systemName: "text.bubble.fill")
                    .font(.system(size: 56))
                    .foregroundStyle(.tint)
                Text("Condenser")
                    .font(.largeTitle.bold())
                Text("Telegram 频道聚合阅读器")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            VStack(spacing: 12) {
                TextField("服务器地址", text: $serverAddress)
                    .textContentType(.URL)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                TextField("设备名", text: $deviceName)
            }
            .textFieldStyle(.roundedBorder)

            VStack(spacing: 12) {
                Button {
                    Task { await logIn() }
                } label: {
                    if isAuthorizing {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                    } else {
                        Text("登录")
                            .frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(isAuthorizing)

                if let message = errorMessage ?? session.notice {
                    Text(message)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                }
            }

            Spacer()
            Spacer()
        }
        .padding(.horizontal, 32)
        .onAppear {
            if let saved = session.serverURL {
                serverAddress = saved.absoluteString
            }
        }
    }

    private func logIn() async {
        guard let server = AuthFlow.normalizeServerAddress(serverAddress) else {
            errorMessage = "服务器地址无效"
            return
        }
        let name = deviceName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else {
            errorMessage = "设备名不能为空"
            return
        }

        errorMessage = nil
        session.notice = nil
        isAuthorizing = true
        defer { isAuthorizing = false }

        do {
            let callback = try await webAuthenticationSession.authenticate(
                using: AuthFlow.authorizeURL(server: server, deviceName: name),
                callbackURLScheme: AuthFlow.callbackScheme,
                preferredBrowserSession: .shared
            )
            switch AuthFlow.parseCallback(callback) {
            case .authorized(let token, _):
                session.completeLogin(server: server, token: token)
            case .denied:
                errorMessage = "授权被拒绝"
            case nil:
                errorMessage = "回调数据无效"
            }
        } catch let error as ASWebAuthenticationSessionError where error.code == .canceledLogin {
            // 用户主动关闭授权页：留在登录页，不算错误
        } catch {
            errorMessage = "授权失败：\(error.localizedDescription)"
        }
    }
}
