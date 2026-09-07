import Foundation
import Testing
@testable import CondenserKit

// 票据缓存的纯状态机（plan 2026-09-07 §5.1）。票据 5 分钟有效，剩余不足 60s 时该换新；
// 点击永远同步、永远用当下缓存的票（可能为 nil），所以 cached / shouldRefresh 是两个
// 独立的问题：进入 margin 后"该刷新"但票"仍可用"。

@Suite("Purifier 票据状态机")
struct PurifierTicketsTests {
    private let t0 = Date(timeIntervalSince1970: 1_000_000)

    @Test("初始：无票，需要刷新")
    func initialState() {
        let tickets = PurifierTickets()
        #expect(tickets.cached(now: t0) == nil)
        #expect(tickets.shouldRefresh(now: t0))
    }

    @Test("store 后可读，且不需要刷新")
    func storedIsUsable() {
        var tickets = PurifierTickets()
        tickets.store(ticket: "T1", ttl: 300, now: t0)
        #expect(tickets.cached(now: t0) == "T1")
        #expect(tickets.cached(now: t0.addingTimeInterval(200)) == "T1")
        #expect(!tickets.shouldRefresh(now: t0.addingTimeInterval(200)))
    }

    @Test("进入 60s margin：需要刷新，但票仍可用")
    func marginRefreshesButStillUsable() {
        var tickets = PurifierTickets()
        tickets.store(ticket: "T1", ttl: 300, now: t0)
        let inMargin = t0.addingTimeInterval(250)
        #expect(tickets.shouldRefresh(now: inMargin))
        #expect(tickets.cached(now: inMargin) == "T1")
    }

    @Test("硬过期后 cached 为 nil")
    func expiredIsNil() {
        var tickets = PurifierTickets()
        tickets.store(ticket: "T1", ttl: 300, now: t0)
        #expect(tickets.cached(now: t0.addingTimeInterval(300)) == nil)
        #expect(tickets.shouldRefresh(now: t0.addingTimeInterval(300)))
    }

    @Test("clear 复位到初始态")
    func clearResets() {
        var tickets = PurifierTickets()
        tickets.store(ticket: "T1", ttl: 300, now: t0)
        tickets.clear()
        #expect(tickets.cached(now: t0) == nil)
        #expect(tickets.shouldRefresh(now: t0))
    }
}
