import Foundation
import Observation

/// 收藏（records）列表状态机：全量加载（后端不分页、条目为自包含 envelope——
/// TG 带 channel 快照，HN 带 story 快照）、unsave 乐观移除 + 失败按原位放回。
/// 错误收敛同 TimelineStore：401 走 onUnauthorized，其余进 error 文案且保留内容。
@MainActor
@Observable
public final class RecordsStore {
    public private(set) var items: [TimelineItem] = []
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

    /// 取消收藏：乐观移除；失败按原位置放回（错误文案交给调用方展示）。
    /// 带 note/标注的条目例外（v18 不变式）：服务端只翻 is_saved、行保留，
    /// 所以本地同样只翻旗标——移除了下次刷新它又回来，读起来像 bug。
    public func unsave(_ item: TimelineItem) async {
        guard let index = items.firstIndex(where: { $0.key == item.key }) else { return }
        if item.hasNotes {
            items[index].isSaved = false
            do {
                try await api.deleteRecord(key: item.key)
            } catch {
                if let rollback = items.firstIndex(where: { $0.key == item.key }) {
                    items[rollback].isSaved = true
                }
                handle(error)
            }
            return
        }
        let removed = items.remove(at: index)
        do {
            try await api.deleteRecord(key: item.key)
        } catch {
            items.insert(removed, at: min(index, items.count))
            handle(error)
        }
    }

    /// 收藏里同样可以改标签（反馈是随时会变的活状态，刻意不进收藏快照，
    /// 所以这里改完服务端立刻生效，下次拉取读回来的就是新值）
    public func setFeedback(_ item: TimelineItem, _ tapped: ItemFeedback) async {
        let next = ItemFeedback.next(current: item.feedback, tapped: tapped)
        await write(item, verdict: next, reason: nil)
    }

    /// 选理由 chip（语义同 TimelineStore.setReason）
    public func setReason(_ item: TimelineItem, _ reason: ItemFeedbackReason) async {
        await write(item, verdict: item.feedback ?? .down, reason: reason)
    }

    private func write(_ item: TimelineItem, verdict: ItemFeedback?, reason: ItemFeedbackReason?) async {
        guard let index = items.firstIndex(where: { $0.key == item.key }) else { return }
        let previous = (items[index].feedback, items[index].feedbackReason)
        items[index].feedback = verdict
        items[index].feedbackReason = verdict == nil ? nil : reason
        do {
            if let verdict {
                try await api.setFeedback(key: item.key, verdict: verdict, reason: reason)
            } else {
                try await api.clearFeedback(key: item.key)
            }
        } catch {
            if let rollback = items.firstIndex(where: { $0.key == item.key }) {
                (items[rollback].feedback, items[rollback].feedbackReason) = previous
            }
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
