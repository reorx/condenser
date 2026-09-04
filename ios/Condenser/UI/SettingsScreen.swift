import SwiftUI
import CondenserKit

/// 设置 tab：服务器地址/设备名只读展示、外观跟随系统、登出。
/// 服务端 token 吊销走 web 端设置页（spec：登出只清本地 Keychain）。
/// 自身不含 NavigationStack，由挂载点（tab / debug sheet）提供。
struct SettingsScreen: View {
    @Environment(AuthSession.self) private var auth
    @Environment(ReaderSession.self) private var reader

    @State private var confirmSignOut = false
    @AppStorage(FontScale.storageKey) private var fontScaleRaw = FontScale.default.rawValue
    @State private var forwardChannel = ""
    @State private var forwardSaving = false
    @State private var forwardSaved = false
    @State private var forwardError: String?

    private var fontScale: FontScale { FontScale(storedValue: fontScaleRaw) }

    var body: some View {
        Form {
            Section("服务器") {
                LabeledContent("地址", value: auth.serverURL?.absoluteString ?? "—")
                LabeledContent("设备名", value: auth.deviceName ?? Platform.deviceName)
            }
            Section {
                LabeledContent("主题", value: "跟随系统")
            } header: {
                Text("外观")
            }
            Section {
                fontScaleSlider
                FontScalePreviewCard(scale: fontScale)
            } header: {
                Text("字号")
            } footer: {
                Text("调整消息列表与详情页的文字大小。")
            }
            Section {
                TextField("@channel 或 t.me 链接", text: $forwardChannel)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .onSubmit { saveForwardChannel() }
                Button(forwardSaved ? "已保存" : "保存") {
                    saveForwardChannel()
                }
                .disabled(forwardSaving)
                .foregroundStyle(forwardSaved ? .green : Color.accentColor)
            } header: {
                Text("转发")
            } footer: {
                Text(forwardError ?? "「转发到我的频道」的目标频道；清空后保存即取消配置。")
                    .foregroundStyle(forwardError == nil ? Color.secondary : .red)
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
        .task {
            // 回填已配置的目标频道；拉不到就留空（保存路径会报错兜底）
            if let meta = try? await reader.api.appMeta() {
                forwardChannel = meta.forwardChannel ?? ""
            }
        }
        .confirmationDialog("确定登出？", isPresented: $confirmSignOut, titleVisibility: .visible) {
            Button("登出", role: .destructive) {
                Task {
                    await reader.readReporter.flushNow()
                    auth.signOut()
                }
            }
        }
    }

    private func saveForwardChannel() {
        forwardError = nil
        forwardSaving = true
        Task {
            do {
                let meta = try await reader.api.setForwardChannel(
                    forwardChannel.trimmingCharacters(in: .whitespacesAndNewlines))
                forwardChannel = meta.forwardChannel ?? ""
                forwardSaved = true
                try? await Task.sleep(for: .seconds(1.5))
                forwardSaved = false
            } catch {
                forwardError = "保存失败，请稍后再试"
            }
            forwardSaving = false
        }
    }

    private var appVersion: String {
        let short = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?"
        return "\(short) (\(build))"
    }

    /// 离散滑块（4 档）+ 档位标签；标签可直接点选
    private var fontScaleSlider: some View {
        VStack(spacing: 4) {
            Slider(
                value: Binding(
                    get: { Double(fontScale.sliderIndex) },
                    set: { fontScaleRaw = FontScale(sliderIndex: Int($0.rounded())).rawValue }),
                in: 0...Double(FontScale.allCases.count - 1),
                step: 1)
            HStack {
                ForEach(Array(FontScale.allCases.enumerated()), id: \.element) { index, scale in
                    Text(scale.displayName)
                        .font(.caption)
                        .foregroundStyle(scale == fontScale ? Color.accentColor : Color.secondary)
                        .frame(maxWidth: .infinity, alignment: labelAlignment(index))
                        .contentShape(Rectangle())
                        .onTapGesture { fontScaleRaw = scale.rawValue }
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func labelAlignment(_ index: Int) -> Alignment {
        switch index {
        case 0: .leading
        case FontScale.allCases.count - 1: .trailing
        default: .center
        }
    }
}

/// 字号预览：静态 mock 消息卡片（不依赖网络/真实数据），布局与 MessageCard 一致
private struct FontScalePreviewCard: View {
    let scale: FontScale

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Circle()
                    .fill(.tint.opacity(0.15))
                    .frame(width: 36, height: 36)
                    .overlay {
                        Text("凝")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.tint)
                    }
                VStack(alignment: .leading, spacing: 1) {
                    Text("Condenser 精选")
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(1)
                    Text("5 分钟前")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Image(systemName: "star")
                    .foregroundStyle(.secondary)
            }
            Text("这是消息卡片的字号预览。滑动上方滑块，正文会像这样实时缩放，方便找到最舒适的阅读大小。")
                .font(.subheadline)
        }
        .padding(.vertical, 4)
        .dynamicTypeSize(scale.dynamicTypeSize)
        .animation(.snappy(duration: 0.15), value: scale)
    }
}
