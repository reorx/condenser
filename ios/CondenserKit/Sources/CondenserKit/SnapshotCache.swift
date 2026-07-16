import Foundation

/// 响应 JSON 的落盘快照（Caches 目录）：冷启动先渲染快照再后台刷新。
/// 缓存是尽力而为的：save 失败静默丢弃，load 遇缺失/损坏返回 nil 不 crash
/// （spec 明确要求容错，系统也可能随时清 Caches）。
public final class SnapshotCache: @unchecked Sendable {
    private let directory: URL
    private let encoder = JSONEncoder.condenserAPI
    private let decoder = JSONDecoder.condenserAPI

    public init(directory: URL? = nil) {
        self.directory = directory ?? FileManager.default
            .urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("condenser-snapshots", isDirectory: true)
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
