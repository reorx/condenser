import Testing
@testable import CondenserKit

@Suite("ReadingTextStyle（Mac 字号表）")
struct ReadingTextStyleTests {
    @Test("正常档 = iOS 默认表：正文 17、卡片正文 15、caption 12")
    func normalMatchesIOSDefaults() {
        #expect(ReadingTextStyle.body.pointSize(for: .normal) == 17)
        #expect(ReadingTextStyle.subheadline.pointSize(for: .normal) == 15)
        #expect(ReadingTextStyle.caption.pointSize(for: .normal) == 12)
        #expect(ReadingTextStyle.largeTitle.pointSize(for: .normal) == 34)
    }

    @Test("四档对 body 给出 15 / 17 / 19 / 21，与 iOS S/L/XL/XXL 一致")
    func bodyTiersMatchDynamicType() {
        #expect(FontScale.allCases.map { ReadingTextStyle.body.pointSize(for: $0) } == [15, 17, 19, 21])
    }

    @Test("每种样式的字号随档位严格递增（滑块每一格都看得出变化）")
    func strictlyIncreasingAcrossTiers() {
        for style in ReadingTextStyle.allCases {
            let sizes = FontScale.allCases.map { style.pointSize(for: $0) }
            #expect(sizes == sizes.sorted(), "\(style) \(sizes)")
            #expect(Set(sizes).count == sizes.count, "\(style) 有两档同尺寸: \(sizes)")
        }
    }

    @Test("点值是整数（避免半像素的模糊字）")
    func integralPointSizes() {
        for style in ReadingTextStyle.allCases {
            for scale in FontScale.allCases {
                let size = style.pointSize(for: scale)
                #expect(size == size.rounded())
            }
        }
    }

    @Test("样式之间保持层级：正常档严格递减，其他档最多相邻两级并到同一尺寸（iOS 的 S 档 caption 与 caption2 也同为 11）")
    func hierarchyPreserved() {
        let ladder: [ReadingTextStyle] = [.largeTitle, .title2, .title3, .body, .subheadline, .footnote, .caption, .caption2]
        for scale in FontScale.allCases {
            let sizes = ladder.map { $0.pointSize(for: scale) }
            for (a, b) in zip(sizes, sizes.dropFirst()) {
                if scale == .normal { #expect(a > b, "\(scale) \(sizes)") } else { #expect(a >= b, "\(scale) \(sizes)") }
            }
            #expect(ReadingTextStyle.headline.pointSize(for: scale) == ReadingTextStyle.body.pointSize(for: scale))
        }
    }
}
