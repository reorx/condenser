import Testing
@testable import CondenserKit

@Suite("EdgeSwipe：左边缘右滑关闭抽屉的判定")
struct EdgeSwipeTests {
    @Test("明确向右的横向滑动关闭抽屉")
    func dismissesOnHorizontalSwipeRight() {
        #expect(EdgeSwipe.shouldDismiss(dx: 120, dy: 10))
        #expect(EdgeSwipe.shouldDismiss(dx: 61, dy: -30))
    }

    @Test("位移不到门槛不关：手指在边缘蹭一下不该丢掉正在读的文章")
    func ignoresShortSwipe() {
        #expect(!EdgeSwipe.shouldDismiss(dx: 60, dy: 0))
        #expect(!EdgeSwipe.shouldDismiss(dx: 30, dy: 0))
    }

    @Test("纵向位移压过横向的不关：贴着左边缘竖着滚长文是滚动，不是关闭")
    func ignoresVerticalScroll() {
        #expect(!EdgeSwipe.shouldDismiss(dx: 80, dy: 200))
        #expect(!EdgeSwipe.shouldDismiss(dx: 80, dy: -200))
        #expect(!EdgeSwipe.shouldDismiss(dx: 80, dy: 80))
    }

    @Test("向左滑不关")
    func ignoresSwipeLeft() {
        #expect(!EdgeSwipe.shouldDismiss(dx: -200, dy: 0))
    }
}
