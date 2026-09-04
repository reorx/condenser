import SwiftUI

/// 平台差异的唯一集中点：同一份代码编成 iPhone app 和 Mac Catalyst app
/// （plan `kb/plans/2026-09-04-mac-catalyst.md`）。判断放在编译期而不是
/// `UIDevice.userInterfaceIdiom`——后者在 Catalyst 的 iPad idiom 下会答「pad」。
enum Platform {
    static let isMac: Bool = {
        #if targetEnvironment(macCatalyst)
        true
        #else
        false
        #endif
    }()

    /// 登录页预填 / 设置页展示的设备名。Catalyst 下 `UIDevice.current.name` 答的是
    /// 字面的「iPad」，改取主机名（去掉 mDNS 的 `.local` 后缀）。
    static var deviceName: String {
        if isMac {
            let host = ProcessInfo.processInfo.hostName
            return host.hasSuffix(".local") ? String(host.dropLast(".local".count)) : host
        }
        return UIDevice.current.name
    }
}

/// 阅读列：Mac 窗口能拉到 1500pt 宽，卡片跟着铺满就是一行两百字的正文。
/// 与 web 前端的内容列同一取舍——限宽居中。iPhone 上什么也不做。
struct ReadingColumn: ViewModifier {
    static let maxWidth: CGFloat = 720

    func body(content: Content) -> some View {
        if Platform.isMac {
            content
                .frame(maxWidth: Self.maxWidth)
                .frame(maxWidth: .infinity)
        } else {
            content
        }
    }
}

extension View {
    func readingColumn() -> some View {
        modifier(ReadingColumn())
    }
}

/// 详情抽屉的呈现方式。iPhone：半屏/全屏两档 + grabber；Mac：Catalyst 的默认 sheet 是
/// 一块约 460pt 见方的固定框，读一篇长文像从门缝里看，改成 `.page` 尺寸，并补一个
/// 右上角关闭钮（Mac 上没有下滑关闭，Esc 也走这个按钮）。
struct DetailSheetPresentation: ViewModifier {
    @Environment(\.dismiss) private var dismiss

    func body(content: Content) -> some View {
        if Platform.isMac {
            content
                .presentationSizing(.page)
                .overlay(alignment: .topTrailing) {
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.title2)
                            .symbolRenderingMode(.hierarchical)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                    .keyboardShortcut(.cancelAction)
                    .padding(12)
                }
        } else {
            content
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }
}

extension View {
    func detailSheetPresentation() -> some View {
        modifier(DetailSheetPresentation())
    }
}
