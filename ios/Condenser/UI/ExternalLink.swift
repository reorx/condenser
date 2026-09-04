import SafariServices
import SwiftUI
import CondenserKit

/// app 内所有外链的统一出口。
///
/// 规则：X 的链接（推文 / 作者主页）优先深链进 X app——读者点「在 X 上打开」
/// 要的是能点赞、能回复、已经登录好的原生界面，而 in-app Safari 里的 x.com 是个
/// 逼你登录的壳；没装 X app（深链打不开）就回落 in-app Safari，行为与从前一致。
/// 其余链接一律 in-app Safari：为读一条链接把人踢出 app 的代价太大。
///
/// 不用 `canOpenURL` 判断，直接 `open` 拿结果回落：`canOpenURL` 要求
/// Info.plist 声明 `LSApplicationQueriesSchemes`，漏了就永远返回 false，
/// 于是深链静默失效成「一切照旧」——这种回归没有测试抓得住。
@MainActor
func openExternalURL(_ url: URL, fallback: @escaping (URL) -> Void) {
    let app = UIApplication.shared
    // Mac：没有 X app 可深链，也没有 in-app Safari（Catalyst 上 SFSafariViewController
    // 本来就是转手给 Safari）。桌面上「在浏览器里打开」就是读者期待的行为，直接开。
    if Platform.isMac {
        app.open(url)
        return
    }
    guard let deepLink = xAppURL(for: url) else {
        fallback(url)
        return
    }
    app.open(deepLink, options: [:]) { opened in
        if opened { return }
        // `twitter://` 是 X 改名前就注册的老 scheme，哪天它不认了还有一条路：
        // x.com 的 universal link（app 认领了这个域名，系统直接送进去；
        // 没人认领时 universalLinksOnly 只返回 false，不会自己弹 Safari）。
        app.open(url, options: [.universalLinksOnly: true]) { viaUniversalLink in
            if !viaUniversalLink { fallback(url) }
        }
    }
}

extension View {
    /// 接管子树里的链接点击（正文链接、卡片点击、近邻行……）走 `openExternalURL`。
    /// `safari` 是回落用的 in-app Safari sheet 绑定。
    @MainActor
    func externalLinks(safari: Binding<SafariItem?>) -> some View {
        environment(\.openURL, OpenURLAction { url in
            openExternalURL(url) { safari.wrappedValue = SafariItem(url: $0) }
            return .handled
        })
    }
}

struct SafariItem: Identifiable {
    let url: URL
    var id: String { url.absoluteString }
}

struct SafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        SFSafariViewController(url: url)
    }

    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}
