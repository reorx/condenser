import Foundation
import Observation

/// 已读收集器：卡片越过判读线 → enqueue(item key) → debounce 合并批量
/// POST /api/read {keys}。readKeys 是本地乐观已读集合（入队即置位，UI 直接消费）；
/// 发送失败重回队列，按 5× debounce 退避重试，队列不丢。
///
/// unsyncedKeys 是 readKeys 的「还没落到服务器」子集：入队即进、服务器确认才出，
/// 失败期间一直留着。卡片据此画绿点——乐观已读把蓝点熄了，同步失败就完全不可见，
/// 而这恰恰是最该看见的状态。
@MainActor
@Observable
public final class ReadReporter {
    public private(set) var readKeys: Set<String> = []
    /// 已判定应读、但还没拿到服务器确认的 key（UI 的绿点）
    public private(set) var unsyncedKeys: Set<String> = []
    /// 401 时触发（app 层接 AuthSession.handleUnauthorized）
    public var onUnauthorized: (@MainActor () -> Void)?

    private let api: CondenserAPI
    private let debounce: Duration
    private var pending: Set<String> = []
    private var flushTask: Task<Void, Never>?
    private var isFlushing = false

    public init(api: CondenserAPI, debounce: Duration = .seconds(2)) {
        self.api = api
        self.debounce = debounce
    }

    public func enqueue(_ key: String) {
        guard !readKeys.contains(key) else { return }
        readKeys.insert(key)
        pending.insert(key)
        unsyncedKeys.insert(key)
        scheduleFlush(after: debounce)
    }

    /// 立即发送（进后台 / 视图消失时调用）
    public func flushNow() async {
        flushTask?.cancel()
        flushTask = nil
        await flush()
    }

    private func scheduleFlush(after delay: Duration) {
        flushTask?.cancel()
        flushTask = Task {
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled else { return }
            await flush()
        }
    }

    private func flush() async {
        guard !isFlushing, !pending.isEmpty else { return }
        isFlushing = true
        let batch = pending
        pending = []
        do {
            try await api.markRead(keys: Array(batch))
            // 只熄灭本批：在途期间新入队的 key 还没发出去，绿点要留着
            unsyncedKeys.subtract(batch)
        } catch APIError.unauthorized {
            // 不重试（要重新登录），队列与绿点一起放弃，免得永远亮着
            unsyncedKeys.subtract(batch)
            onUnauthorized?()
        } catch {
            // 失败重回队列，退避重试；期间新入队的条目一并带上
            pending.formUnion(batch)
            scheduleFlush(after: debounce * 5)
        }
        isFlushing = false
    }
}
