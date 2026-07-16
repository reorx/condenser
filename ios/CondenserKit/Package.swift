// swift-tools-version:6.0
import PackageDescription

// 语言模式固定 Swift 5（避免 Swift 6 strict concurrency 的迁移成本），
// tools-version 6.0 以使用 Swift Testing。
// 平台带 macOS 是为了让 `swift test` 在宿主机直接跑（纯逻辑，无 UIKit 依赖）。
let package = Package(
    name: "CondenserKit",
    platforms: [.iOS(.v18), .macOS(.v15)],
    products: [
        .library(name: "CondenserKit", targets: ["CondenserKit"])
    ],
    dependencies: [
        // 第三方依赖统一声明在这里，app target 经 project.yml 传递依赖
    ],
    targets: [
        .target(
            name: "CondenserKit",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "CondenserKitTests",
            dependencies: ["CondenserKit"],
            resources: [.copy("Fixtures")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
