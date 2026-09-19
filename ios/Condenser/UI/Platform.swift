import SwiftUI
import CondenserKit

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

/// 详情的容器：iPhone 弹 `.sheet(item:)`；Mac 在列表右侧展开一栏（2026-09-04）。
/// 不用 sheet 是因为 Catalyst 的 `.page` sheet 比窗口宽时 macOS 会把整个窗口挪开给它
/// 腾位置——窗口贴着屏幕左边，一开详情就被顶着往右跑。栏在窗口内展开，窗口原地不动。
/// 宽度规则在 Kit 的 `DetailColumnLayout`（有测试）。
///
/// 两处细节：详情视图挂 `.id(item.id)`——sheet 每次呈现都是新视图树，而栏里换条目只是
/// 换了参数，不加 id 的话上一条的 `@State`（标注模型、已加载的全文）会留在下一条里；
/// 关闭动作通过 `\.detailColumnDismiss` 环境值下发，栏不是 presentation，
/// `@Environment(\.dismiss)` 在里面什么也不做。
struct DetailPresentation<Item: Identifiable, Detail: View>: ViewModifier {
    @Binding var item: Item?
    @ViewBuilder let detail: (Item) -> Detail
    @State private var containerWidth: CGFloat = 0

    func body(content: Content) -> some View {
        if Platform.isMac {
            HStack(spacing: 0) {
                content
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                if let item {
                    // 盖满列表时不画分隔线：栏已经占了整个宽度，再加 1pt 就溢出容器
                    if !coversList { Divider() }
                    detail(item)
                        .id(item.id)
                        .environment(\.detailColumnDismiss, DetailColumnDismiss { self.item = nil })
                        .frame(width: columnWidth)
                        .background(Color(.systemBackground))
                        .transition(.move(edge: .trailing))
                }
            }
            // ⚠️ 宽度要量**父容器给的**尺寸，所以先 `.frame(maxWidth: .infinity)` 再测：
            // 直接量 HStack 自身会把子视图的总宽量进去——栏宽取自上一轮测量值，加上分隔线
            // 就比容器宽 1pt，测量值每轮 +1，布局死循环（2026-09-04 实测：三个实例各吃满
            // 一个核，AppleScript quit / ⌘Q 都无响应，只能 kill -9）。
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { containerWidth = $0 }
            .clipped()
            .animation(.easeInOut(duration: 0.2), value: item == nil)
        } else {
            content.sheet(item: $item, content: detail)
        }
    }

    private var columnWidth: CGFloat {
        DetailColumnLayout.columnWidth(containerWidth: containerWidth)
    }

    private var coversList: Bool { columnWidth >= containerWidth }
}

/// 详情栏的关闭动作（闭包不 Equatable，包一层才能进环境）
struct DetailColumnDismiss {
    let action: () -> Void
    func callAsFunction() { action() }
}

extension EnvironmentValues {
    /// 非 nil = 当前详情正在 Mac 的右侧栏里显示，关闭要走它而不是 `dismiss`
    @Entry var detailColumnDismiss: DetailColumnDismiss?
}

extension View {
    func detailPresentation<Item: Identifiable, Detail: View>(
        item: Binding<Item?>, @ViewBuilder detail: @escaping (Item) -> Detail
    ) -> some View {
        modifier(DetailPresentation(item: item, detail: detail))
    }

    /// Mac 上详情栏开着时，列表里对应那张卡片的选中底色；iPhone 上什么也不做
    ///（抽屉盖着列表，选中态没人看）
    @ViewBuilder
    func detailSelectionHighlight(_ isSelected: Bool) -> some View {
        if Platform.isMac {
            background(isSelected ? Color.accentColor.opacity(0.10) : Color.clear)
        } else {
            self
        }
    }
}

/// 详情视图自身的呈现修饰。iPhone：半屏/全屏两档 + grabber + 左边缘右滑关闭。Mac 分两种情况：
/// 在右侧栏里（`detailColumnDismiss` 非 nil）——顶部一行关闭钮，关闭走环境里的动作；
/// 仍以 sheet 出现时（DEBUG 路由直接弹的详情）——Catalyst 的默认 sheet 是一块约 460pt
/// 见方的固定框，读一篇长文像从门缝里看，改成 `.page` 尺寸 + 右上角关闭钮。
/// 两种 Mac 形态的关闭钮都接 Esc（`.cancelAction`）。
struct DetailSheetPresentation: ViewModifier {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.detailColumnDismiss) private var columnDismiss

    func body(content: Content) -> some View {
        if let columnDismiss {
            // 关闭钮单独占一行而不是叠在内容上：栏只有 360-520pt 宽，叠上去会压住
            // 头部那行频道名 / 作者名
            VStack(spacing: 0) {
                HStack {
                    Spacer()
                    closeButton { columnDismiss() }
                }
                .padding(.horizontal, 12)
                .padding(.top, 8)
                content
            }
        } else if Platform.isMac {
            content
                .presentationSizing(.page)
                .overlay(alignment: .topTrailing) {
                    closeButton { dismiss() }
                        .padding(12)
                }
        } else {
            // 左边缘右滑关闭挂在这里而不是各个抽屉自己身上：四个源的抽屉都经过这个修饰，
            // 漏挂一个就是一个单手关不掉的抽屉。Mac 的两种形态没有触摸手势，不需要
            content
                .edgeSwipeToDismiss()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }

    private func closeButton(_ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: "xmark.circle.fill")
                .font(.title2)
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.secondary)
        }
        .buttonStyle(.plain)
        .keyboardShortcut(.cancelAction)
    }
}

extension View {
    func detailSheetPresentation() -> some View {
        modifier(DetailSheetPresentation())
    }
}
