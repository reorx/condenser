import Testing
@testable import CondenserKit

/// Mac 详情栏的宽度规则：跟着窗口宽度走，但夹在一个可读区间里；
/// 窗口窄到两栏并排放不下时，详情栏盖满整个内容区（仍在窗口内，绝不弹模态）。
@Suite("DetailColumnLayout")
struct DetailColumnLayoutTests {
    @Test("宽窗口：栏宽封顶，不跟着窗口无限变宽")
    func wideWindowCapsAtMax() {
        #expect(DetailColumnLayout.columnWidth(containerWidth: 1600) == DetailColumnLayout.maxWidth)
        #expect(DetailColumnLayout.columnWidth(containerWidth: 1200) == DetailColumnLayout.maxWidth)
    }

    @Test("中等窗口：按比例取宽")
    func mediumWindowIsProportional() {
        let w = DetailColumnLayout.columnWidth(containerWidth: 1000)
        #expect(w == (1000 * DetailColumnLayout.fraction).rounded())
        #expect(w > DetailColumnLayout.minWidth && w < DetailColumnLayout.maxWidth)
    }

    @Test("窄窗口：栏宽不低于下限，列表还留得下最小宽度")
    func narrowWindowKeepsMinimums() {
        let container = DetailColumnLayout.minWidth + DetailColumnLayout.minListWidth
        #expect(DetailColumnLayout.columnWidth(containerWidth: container) == DetailColumnLayout.minWidth)
    }

    @Test("放不下两栏：详情栏盖满整个内容区")
    func tooNarrowCoversList() {
        let container = DetailColumnLayout.minWidth + DetailColumnLayout.minListWidth - 1
        #expect(DetailColumnLayout.columnWidth(containerWidth: container) == container)
        #expect(DetailColumnLayout.columnWidth(containerWidth: 0) == 0)
    }
}
