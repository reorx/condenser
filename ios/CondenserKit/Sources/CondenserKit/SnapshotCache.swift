import Foundation

/// 响应 JSON 的落盘快照（Caches 目录）：冷启动先渲染快照再后台刷新。
/// 缓存是尽力而为的：save 失败静默丢弃，load 遇缺失/损坏返回 nil 不 crash
/// （spec 明确要求容错，系统也可能随时清 Caches）。
/// 目录带契约版本号：多信源 envelope 是 breaking change，v2 起换目录，
/// 旧契约快照（或未来再升级时的旧文件）decode 失败一律按 miss 处理。
public final class SnapshotCache: @unchecked Sendable {
    /// 快照契约版本：API breaking change 时 +1（v2 = 多信源 envelope；
    /// v3 = RSS 列表载荷只带 content_excerpt——旧快照 decode 得出来但没有摘录，
    /// 会画成空白卡片，按 miss 换目录，代价是冷启动多一次网络请求，一次性）
    public static let contractVersion = 3

    private let directory: URL
    private let encoder = JSONEncoder.condenserAPI
    private let decoder = JSONDecoder.condenserAPI

    public init(directory: URL? = nil) {
        self.directory = directory ?? FileManager.default
            .urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(
                "condenser-snapshots-v\(Self.contractVersion)", isDirectory: true)
    }

    public func save<T: Encodable>(_ value: T, key: String) {
        guard let data = try? encoder.encode(value) else { return }
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? data.write(to: fileURL(for: key), options: .atomic)
    }

    public func load<T: Decodable>(_ type: T.Type, key: String) -> T? {
        guard let data = try? Data(contentsOf: fileURL(for: key)) else { return nil }
        return try? decoder.decode(type, from: data)
    }

    public func remove(key: String) {
        try? FileManager.default.removeItem(at: fileURL(for: key))
    }

    /// key → 文件路径（非法字符替换，internal 供测试构造损坏文件）
    func fileURL(for key: String) -> URL {
        let safe = String(key.map { $0.isLetter || $0.isNumber || $0 == "-" ? $0 : "_" })
        return directory.appendingPathComponent(safe + ".json")
    }
}
