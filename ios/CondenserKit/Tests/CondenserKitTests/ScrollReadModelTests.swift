import CoreGraphics
import Testing
@testable import CondenserKit

// 「滚过即已读」判定：判读线是视口下边界（卡片下边界进到视口里就算看过），
// 但必须先被用户滚动武装过——否则首屏一渲染就会被整屏判读。

@Suite("ScrollReadModel")
struct ScrollReadModelTests {
    @Test("卡片下边界进入视口内即算看过；恰好压在下沿也算")
    func passesWhenBottomEntersViewport() {
        // 视口高 800：下边界 799 已在视口内
        #expect(ScrollReadModel.hasPassedReadLine(frameMaxY: 799, viewportHeight: 800))
        #expect(ScrollReadModel.hasPassedReadLine(frameMaxY: 800, viewportHeight: 800),
                "恰好等于视口下沿算完整可见")
    }

    @Test("下边界还在视口下方（没看全）不算看过")
    func notPassedWhenBelowViewport() {
        #expect(!ScrollReadModel.hasPassedReadLine(frameMaxY: 801, viewportHeight: 800))
        #expect(!ScrollReadModel.hasPassedReadLine(frameMaxY: 2000, viewportHeight: 800))
    }

    @Test("旧规则「整体移出视口上方」是新规则的子集")
    func passedTopIsSubset() {
        #expect(ScrollReadModel.hasPassedReadLine(frameMaxY: -1, viewportHeight: 800))
        #expect(ScrollReadModel.hasPassedReadLine(frameMaxY: -500, viewportHeight: 800))
    }

    @Test("视口高度未知时退化成旧规则，绝不把整屏判成已读")
    func degradesToOldRuleWithoutViewport() {
        // UI 层拿不到 scrollView bounds 时传 0
        #expect(!ScrollReadModel.hasPassedReadLine(frameMaxY: 10, viewportHeight: 0))
        #expect(ScrollReadModel.hasPassedReadLine(frameMaxY: -10, viewportHeight: 0))
    }

    @Test("初始未武装，用户滚动后武装")
    func armsOnUserScroll() {
        var model = ScrollReadModel()
        #expect(!model.armed, "首屏渲染完还没滚动过，不判读")
        model.noteUserScroll()
        #expect(model.armed)
        model.noteUserScroll()
        #expect(model.armed, "重复滚动保持武装")
    }

    @Test("刷新替换列表后解除武装，新首屏不被瞬间批量标记")
    func resetDisarms() {
        var model = ScrollReadModel()
        model.noteUserScroll()
        model.reset()
        #expect(!model.armed)
        model.noteUserScroll()
        #expect(model.armed, "解除后再滚动可重新武装")
    }
}
