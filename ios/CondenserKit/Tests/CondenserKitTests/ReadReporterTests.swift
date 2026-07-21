import Foundation
import Testing
@testable import CondenserKit

// ReadReporter：滚动过顶入队（item key）→ debounce 合并为一次批量 POST /api/read；
// 本地乐观已读集合；失败后队列不丢、按退避重试。

@MainActor
@Suite("ReadReporter")
struct ReadReporterTests {
    @Test("debounce 窗口内多次入队合并为一次批量请求（跨源 key 混合）")
    func batchesWithinDebounce() async throws {
        let api = StubAPI()
        let reporter = ReadReporter(api: api, debounce: .milliseconds(40))
        reporter.enqueue("tg:1:1")
        reporter.enqueue("tg:1:2")
        reporter.enqueue("hn:900")
        #expect(api.markReadCalls.isEmpty, "debounce 未到不发请求")
        try await Task.sleep(for: .milliseconds(150))
        #expect(api.markReadCalls.count == 1)
        #expect(Set(api.markReadCalls[0]) == ["tg:1:1", "tg:1:2", "hn:900"])
    }

    @Test("入队即乐观置已读；重复入队被忽略")
    func optimisticAndIdempotent() async throws {
        let api = StubAPI()
        let reporter = ReadReporter(api: api, debounce: .milliseconds(40))
        reporter.enqueue("tg:1:1")
        #expect(reporter.readKeys.contains("tg:1:1"), "入队即本地已读")
        reporter.enqueue("tg:1:1")
        try await Task.sleep(for: .milliseconds(150))
        #expect(api.markReadCalls.count == 1)
        #expect(api.markReadCalls[0] == ["tg:1:1"])
    }

    @Test("失败后队列不丢，恢复后重试补发")
    func retryAfterFailure() async throws {
        let api = StubAPI()
        api.markReadError = APIError.http(status: 500, detail: nil)
        let reporter = ReadReporter(api: api, debounce: .milliseconds(20))
        reporter.enqueue("tg:1:1")
        try await Task.sleep(for: .milliseconds(80))
        #expect(api.markReadCalls.isEmpty, "失败不算发送成功")

        api.markReadError = nil
        try await Task.sleep(for: .milliseconds(300))
        #expect(api.markReadCalls.count == 1, "重试补发")
        #expect(api.markReadCalls[0] == ["tg:1:1"])
    }

    @Test("flushNow 立即发送，不等 debounce")
    func flushNow() async throws {
        let api = StubAPI()
        let reporter = ReadReporter(api: api, debounce: .seconds(60))
        reporter.enqueue("hn:42")
        await reporter.flushNow()
        #expect(api.markReadCalls == [["hn:42"]])
    }

    @Test("401 → onUnauthorized")
    func unauthorized() async throws {
        let api = StubAPI()
        api.markReadError = APIError.unauthorized
        let reporter = ReadReporter(api: api, debounce: .milliseconds(10))
        var fired = false
        reporter.onUnauthorized = { fired = true }
        reporter.enqueue("tg:1:1")
        await reporter.flushNow()
        #expect(fired)
    }
}
