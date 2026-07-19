import CoreGraphics
import Testing
@testable import CondenserKit

// 底部"继续上拉加载更早"的手势决策：阈值触发、单手势只触发一次、
// 回弹后可再次触发、非用户拖拽不触发；以及 overscroll 几何换算。

@Suite("PullToLoadOlderModel")
struct PullToLoadOlderModelTests {
    @Test("拖拽越过阈值触发一次，同一手势不重复触发")
    func firesOncePerGesture() {
        var model = PullToLoadOlderModel(threshold: 70)
        let below = model.handleOverscroll(30, isDragging: true)
        #expect(!below, "未到阈值不触发")
        let fired = model.handleOverscroll(75, isDragging: true)
        #expect(fired)
        let again = model.handleOverscroll(90, isDragging: true)
        #expect(!again, "同一手势继续拉不重复触发")
        let back = model.handleOverscroll(72, isDragging: true)
        #expect(!back)
    }

    @Test("回弹到内容底部以内后可再次触发")
    func rearmsAfterBounceBack() {
        var model = PullToLoadOlderModel(threshold: 70)
        let first = model.handleOverscroll(80, isDragging: true)
        #expect(first)
        let bounce = model.handleOverscroll(0, isDragging: false)
        #expect(!bounce, "回弹本身不触发")
        let second = model.handleOverscroll(80, isDragging: true)
        #expect(second, "复位后新手势可再触发")
    }

    @Test("非用户拖拽（惯性回弹）越过阈值不触发")
    func ignoresNonDragOverscroll() {
        var model = PullToLoadOlderModel(threshold: 70)
        let inertial = model.handleOverscroll(100, isDragging: false)
        #expect(!inertial)
        let dragged = model.handleOverscroll(100, isDragging: true)
        #expect(dragged, "但用户拖拽仍可触发")
    }

    @Test("bottomOverscroll：长内容滚到底为 0，越过内容底边为正")
    func overscrollGeometryLongContent() {
        // 内容 2000，容器 800，底 inset 50 → 底部静止 offset = 2000+50-800 = 1250
        let atRest = PullToLoadOlderModel.bottomOverscroll(
            contentOffsetY: 1250, contentHeight: 2000, containerHeight: 800,
            topInset: 100, bottomInset: 50)
        #expect(atRest == 0)
        let pulled = PullToLoadOlderModel.bottomOverscroll(
            contentOffsetY: 1330, contentHeight: 2000, containerHeight: 800,
            topInset: 100, bottomInset: 50)
        #expect(pulled == 80)
    }

    @Test("bottomOverscroll：内容不满一屏时静止为 0，上拉为正")
    func overscrollGeometryShortContent() {
        // 内容 200 < 容器 800，顶部静止 offset = -topInset
        let atRest = PullToLoadOlderModel.bottomOverscroll(
            contentOffsetY: -100, contentHeight: 200, containerHeight: 800,
            topInset: 100, bottomInset: 50)
        #expect(atRest == 0)
        let pulled = PullToLoadOlderModel.bottomOverscroll(
            contentOffsetY: -40, contentHeight: 200, containerHeight: 800,
            topInset: 100, bottomInset: 50)
        #expect(pulled == 60)
    }
}
