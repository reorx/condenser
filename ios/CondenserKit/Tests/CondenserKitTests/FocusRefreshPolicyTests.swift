import Foundation
import Testing
@testable import CondenserKit

@Suite("Mac focus 新内容检查")
struct FocusRefreshPolicyTests {
    private let t0 = Date(timeIntervalSince1970: 1_784_000_000)

    @Test("首次 focus 不重复请求启动加载")
    func firstFocus() {
        var policy = FocusRefreshPolicy()
        let refresh = policy.noteFocus(at: t0)
        #expect(!refresh)
    }

    @Test("两次 focus 间隔超过十分钟，检查一次")
    func longGap() {
        var policy = FocusRefreshPolicy()
        _ = policy.noteFocus(at: t0)
        policy.noteBlur()
        let refresh = policy.noteFocus(at: t0.addingTimeInterval(601))
        let duplicate = policy.noteFocus(at: t0.addingTimeInterval(602))
        #expect(refresh)
        #expect(!duplicate)
    }

    @Test("不足或恰好十分钟不检查")
    func shortGap() {
        for gap in [10.0, 599.0, 600.0] {
            var policy = FocusRefreshPolicy()
            _ = policy.noteFocus(at: t0)
            policy.noteBlur()
            let refresh = policy.noteFocus(at: t0.addingTimeInterval(gap))
            #expect(!refresh)
        }
    }

    @Test("每次真实 focus 都更新基准，不按上次请求时间累计")
    func everyFocusResetsBaseline() {
        var policy = FocusRefreshPolicy()
        _ = policy.noteFocus(at: t0)
        policy.noteBlur()
        let firstReturn = policy.noteFocus(at: t0.addingTimeInterval(500))
        #expect(!firstReturn)
        policy.noteBlur()
        let secondReturn = policy.noteFocus(at: t0.addingTimeInterval(1000))
        #expect(!secondReturn)
        policy.noteBlur()
        let longReturn = policy.noteFocus(at: t0.addingTimeInterval(1601))
        #expect(longReturn)
    }

    @Test("持续前台超过十分钟不轮询；重复 focus 通知不覆盖基准")
    func duplicateFocus() {
        var policy = FocusRefreshPolicy()
        _ = policy.noteFocus(at: t0)
        let duplicate = policy.noteFocus(at: t0.addingTimeInterval(900))
        #expect(!duplicate)
        policy.noteBlur()
        let refresh = policy.noteFocus(at: t0.addingTimeInterval(901))
        #expect(refresh)
    }

    @Test("检查后重新计时，频繁切窗不重复请求")
    func restartsAfterCheck() {
        var policy = FocusRefreshPolicy()
        _ = policy.noteFocus(at: t0)
        policy.noteBlur()
        let refresh = policy.noteFocus(at: t0.addingTimeInterval(601))
        #expect(refresh)
        policy.noteBlur()
        let shortReturn = policy.noteFocus(at: t0.addingTimeInterval(602))
        #expect(!shortReturn)
    }
}
