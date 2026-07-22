import Foundation
import Testing
@testable import CondenserKit

// ForegroundRefreshPolicy：长时间后台后回前台才触发自动刷新。
// noteBackground 记录首次离开前台时刻（inactive → background 连续触发不覆盖）；
// shouldRefreshOnForeground 按后台时长与阈值判定，并清状态避免重复触发。

@Suite("ForegroundRefreshPolicy")
struct ForegroundRefreshPolicyTests {
    private let t0 = Date(timeIntervalSince1970: 1_784_000_000)

    @Test("从未离开前台 → 不刷新")
    func neverBackgrounded() {
        var policy = ForegroundRefreshPolicy(minBackgroundGap: 300)
        let refresh = policy.shouldRefreshOnForeground(at: t0)
        #expect(!refresh)
    }

    @Test("短暂离开（不足阈值）→ 不刷新，且状态已清")
    func shortGap() {
        var policy = ForegroundRefreshPolicy(minBackgroundGap: 300)
        policy.noteBackground(at: t0)
        let shortReturn = policy.shouldRefreshOnForeground(at: t0.addingTimeInterval(10))
        #expect(!shortReturn)
        // 状态已清：紧接着再问（即使时间过了很久）也不误触发
        let askAgain = policy.shouldRefreshOnForeground(at: t0.addingTimeInterval(1000))
        #expect(!askAgain)
    }

    @Test("后台超过阈值 → 刷新一次，随后清状态")
    func longGap() {
        var policy = ForegroundRefreshPolicy(minBackgroundGap: 300)
        policy.noteBackground(at: t0)
        let longReturn = policy.shouldRefreshOnForeground(at: t0.addingTimeInterval(300))
        #expect(longReturn)
        let askAgain = policy.shouldRefreshOnForeground(at: t0.addingTimeInterval(600))
        #expect(!askAgain, "已清状态不重复触发")
    }

    @Test("inactive → background 连续记录保留首次时刻")
    func keepsFirstTimestamp() {
        var policy = ForegroundRefreshPolicy(minBackgroundGap: 300)
        policy.noteBackground(at: t0)
        policy.noteBackground(at: t0.addingTimeInterval(400))
        // 若被第二次覆盖，此刻 gap 为负 → false；保留首次则 350 ≥ 300 → true
        let refresh = policy.shouldRefreshOnForeground(at: t0.addingTimeInterval(350))
        #expect(refresh)
    }

    @Test("回前台后再次离开，重新计时")
    func restartsAfterForeground() {
        var policy = ForegroundRefreshPolicy(minBackgroundGap: 300)
        policy.noteBackground(at: t0)
        _ = policy.shouldRefreshOnForeground(at: t0.addingTimeInterval(10))
        policy.noteBackground(at: t0.addingTimeInterval(100))
        let refresh = policy.shouldRefreshOnForeground(at: t0.addingTimeInterval(500))
        #expect(refresh)
    }
}
