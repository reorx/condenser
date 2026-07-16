import Foundation
import Observation

/// 收藏（records）列表状态机：全量加载（后端不分页、条目自包含 channel 快照）、
/// unsave 乐观移除 + 失败按原位放回。错误收敛同 TimelineStore：
/// 401 走 onUnauthorized，其余进 error 文案且保留内容。
@MainActor
@Observable
public final class RecordsStore {
    public private(set) var items: [DisplayMessage] = []
    public private(set) var isLoading = false
    public var error: String?

    /// 401 时触发（app 层接 AuthSession.handleUnauthorized）
    public var onUnauthorized: (@MainActor () -> Void)?

    private let api: CondenserAPI
    private var loadedOnce = false

    public init(api: CondenserAPI) {
        self.api = api
    }

    /// 首次加载；已加载过则无操作（refresh 负责重载）
    public func loadInitial() async {
        guard !loadedOnce, !isLoading else { return }
        await refresh()
    }

    public func refresh() async {
        guard !isLoading else { return }
        isLoading = true
        error = nil
        do {
            items = try await api.records()
            loadedOnce = true
        } catch {
            handle(error)
        }
        isLoading = false
    }

    /// 取消收藏：乐观移除；失败按原位置放回（错误文案交给调用方展示）
    public func unsave(_ message: DisplayMessage) async {
        guard let index = items.firstIndex(where: { $0.unitKey == message.unitKey }) else { return }
        let removed = items.remove(at: index)
        do {
            try await api.deleteRecord(message.ref)
        } catch {
            items.insert(removed, at: min(index, items.count))
            handle(error)
        }
    }

    private func handle(_ error: Error) {
        if case APIError.unauthorized = error {
            onUnauthorized?()
            return
        }
        if case let APIError.http(status, detail) = error {
            self.error = detail ?? "请求失败（\(status)）"
        } else {
            self.error = error.localizedDescription
        }
    }
}
