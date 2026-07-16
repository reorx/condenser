import Foundation
import Testing
@testable import CondenserKit

// ReadReporter：滚动过顶入队 → debounce 合并为一次批量 POST /api/read；
// 本地乐观已读集合；失败后队列不丢、按退避重试。

@MainActor
@Suite("ReadReporter")
struct ReadReporterTests {
    @Test("debounce 窗口内多次入队合并为一次批量请求")
    func batchesWithinDebounce() async throws {
        let api = StubAPI()
        let reporter = ReadReporter(api: api, debounce: .milliseconds(40))
        reporter.enqueue(MsgRef(channelID: 1, messageID: 1))
        reporter.enqueue(MsgRef(channelID: 1, messageID: 2))
        reporter.enqueue(MsgRef(channelID: 2, messageID: 9))
        #expect(api.markReadCalls.isEmpty, "debounce 未到不发请求")
        try await Task.sleep(for: .milliseconds(150))
        #expect(api.markReadCalls.count == 1)
        #expect(Set(api.markReadCalls[0]) == [
            MsgRef(channelID: 1, messageID: 1),
            MsgRef(channelID: 1, messageID: 2),
            MsgRef(channelID: 2, messageID: 9),
        ])
    }

    @Test("入队即乐观置已读；重复入队被忽略")
    func optimisticAndIdempotent() async throws {
        let api = StubAPI()
        let reporter = ReadReporter(api: api, debounce: .milliseconds(40))
        let ref = MsgRef(channelID: 1, messageID: 1)
        reporter.enqueue(ref)
        #expect(reporter.readRefs.contains(ref), "入队即本地已读")
        reporter.enqueue(ref)
        try await Task.sleep(for: .milliseconds(150))
        #expect(api.markReadCalls.count == 1)
        #expect(api.markReadCalls[0] == [ref])
    }

    @Test("失败后队列不丢，恢复后重试补发")
    func retryAfterFailure() async throws {
        let api = StubAPI()
        api.markReadError = APIError.http(status: 500, detail: nil)
        let reporter = ReadReporter(api: api, debounce: .milliseconds(20))
        reporter.enqueue(MsgRef(channelID: 1, messageID: 1))
        try await Task.sleep(for: .milliseconds(80))
        #expect(api.markReadCalls.isEmpty, "失败不算发送成功")

        api.markReadError = nil
        try await Task.sleep(for: .milliseconds(300))
        #expect(api.markReadCalls.count == 1, "重试补发")
        #expect(api.markReadCalls[0] == [MsgRef(channelID: 1, messageID: 1)])
    }

    @Test("flushNow 立即发送，不等 debounce")
    func flushNow() async throws {
        let api = StubAPI()
        let reporter = ReadReporter(api: api, debounce: .seconds(60))
        reporter.enqueue(MsgRef(channelID: 1, messageID: 1))
        await reporter.flushNow()
        #expect(api.markReadCalls.count == 1)
    }

    @Test("401 → onUnauthorized")
    func unauthorized() async throws {
        let api = StubAPI()
        api.markReadError = APIError.unauthorized
        let reporter = ReadReporter(api: api, debounce: .milliseconds(10))
        var fired = false
        reporter.onUnauthorized = { fired = true }
        reporter.enqueue(MsgRef(channelID: 1, messageID: 1))
        await reporter.flushNow()
        #expect(fired)
    }
}
