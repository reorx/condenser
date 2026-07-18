import Foundation
import Testing
@testable import CondenserKit

@Suite("BarsVisibilityModel")
struct BarsVisibilityModelTests {
    let t0 = ContinuousClock.now

    private func scrollingModel() -> BarsVisibilityModel {
        var model = BarsVisibilityModel()
        model.isUserScrolling = true
        return model
    }

    @Test("初始 bars 可见")
    func initiallyVisible() {
        #expect(!BarsVisibilityModel().barsHidden)
    }

    @Test("用户上滑超过阈值隐藏 bars")
    func hidesOnScrollUp() {
        var model = scrollingModel()
        let changed = model.handleScroll(from: 100, to: 120, now: t0)
        #expect(changed)
        #expect(model.barsHidden)
    }

    @Test("回滑超过阈值恢复 bars")
    func showsOnScrollDown() {
        var model = scrollingModel()
        _ = model.handleScroll(from: 100, to: 120, now: t0)
        let changed = model.handleScroll(from: 120, to: 100, now: t0.advanced(by: .seconds(1)))
        #expect(changed)
        #expect(!model.barsHidden)
    }

    @Test("阈值内抖动不切换")
    func ignoresJitter() {
        var model = scrollingModel()
        let up = model.handleScroll(from: 100, to: 105, now: t0)
        #expect(!up)
        let down = model.handleScroll(from: 105, to: 99, now: t0)
        #expect(!down)
        #expect(!model.barsHidden)
    }

    @Test("非用户滚动（insets 动画/程序滚动）不触发方向判定")
    func ignoresNonUserScroll() {
        var model = BarsVisibilityModel()
        let changed = model.handleScroll(from: 100, to: 200, now: t0)
        #expect(!changed)
        #expect(!model.barsHidden)
    }

    @Test("切换后冷却期内忽略 insets 动画造成的反向位移（自激振荡回归）")
    func ignoresInsetFeedbackDuringCooldown() {
        var model = scrollingModel()
        let hidden = model.handleScroll(from: 100, to: 120, now: t0)
        #expect(hidden)
        // 导航栏隐藏动画：被监听值逐帧骤降 ~100pt，甚至变负触及"顶部"规则
        let drop = model.handleScroll(from: 120, to: 60, now: t0.advanced(by: .milliseconds(50)))
        #expect(!drop)
        let negative = model.handleScroll(from: 60, to: -40, now: t0.advanced(by: .milliseconds(120)))
        #expect(!negative)
        #expect(model.barsHidden)
    }

    @Test("冷却期结束后恢复方向判定")
    func resumesAfterCooldown() {
        var model = scrollingModel()
        _ = model.handleScroll(from: 100, to: 120, now: t0)
        let changed = model.handleScroll(from: 120, to: 100, now: t0.advanced(by: .milliseconds(500)))
        #expect(changed)
        #expect(!model.barsHidden)
    }

    @Test("到达顶部总是恢复 bars，即使位移在阈值内")
    func showsAtTop() {
        var model = scrollingModel()
        _ = model.handleScroll(from: 100, to: 120, now: t0)
        let changed = model.handleScroll(from: 5, to: -1, now: t0.advanced(by: .seconds(1)))
        #expect(changed)
        #expect(!model.barsHidden)
    }

    @Test("程序滚动回顶（非用户滚动）也恢复 bars")
    func showsAtTopOnProgrammaticScroll() {
        var model = scrollingModel()
        _ = model.handleScroll(from: 100, to: 120, now: t0)
        model.isUserScrolling = false
        let changed = model.handleScroll(from: 300, to: -10, now: t0.advanced(by: .seconds(1)))
        #expect(changed)
        #expect(!model.barsHidden)
    }
}
