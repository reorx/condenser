import Foundation
import Testing
@testable import CondenserKit

@Suite("MessageTimestamp")
struct MessageTimestampTests {
    let now = Date(timeIntervalSince1970: 1_752_800_000)

    @Test("3 天内的消息用相对时间")
    func recentIsRelative() {
        #expect(MessageTimestamp.style(for: now.addingTimeInterval(-3600), now: now) == .relative)
        #expect(MessageTimestamp.style(for: now.addingTimeInterval(-2 * 86_400), now: now) == .relative)
    }

    @Test("差一点满 3 天仍是相对时间")
    func justUnderThresholdIsRelative() {
        let date = now.addingTimeInterval(-(3 * 86_400 - 60))
        #expect(MessageTimestamp.style(for: date, now: now) == .relative)
    }

    @Test("超过 3 天切换为绝对时间")
    func overThresholdIsAbsolute() {
        let date = now.addingTimeInterval(-(3 * 86_400 + 60))
        #expect(MessageTimestamp.style(for: date, now: now) == .absolute)
    }

    @Test("未来时间（时钟偏差）按相对时间处理")
    func futureIsRelative() {
        let date = now.addingTimeInterval(600)
        #expect(MessageTimestamp.style(for: date, now: now) == .relative)
    }
}
