import Testing
@testable import CondenserKit

@Suite("FontScale")
struct FontScaleTests {
    @Test("档位从小到大有序，共 4 档")
    func orderedCases() {
        #expect(FontScale.allCases == [.small, .normal, .large, .xLarge])
    }

    @Test("默认档位是正常")
    func defaultIsNormal() {
        #expect(FontScale.default == .normal)
    }

    @Test("显示名：小/正常/略大/大")
    func displayNames() {
        #expect(FontScale.small.displayName == "小")
        #expect(FontScale.normal.displayName == "正常")
        #expect(FontScale.large.displayName == "略大")
        #expect(FontScale.xLarge.displayName == "大")
    }

    @Test("rawValue 往返，可持久化")
    func rawValueRoundTrip() {
        for scale in FontScale.allCases {
            #expect(FontScale(rawValue: scale.rawValue) == scale)
        }
    }

    @Test("未知 rawValue 回退默认档（存储值损坏/降级兼容）")
    func unknownRawValueFallsBack() {
        #expect(FontScale(storedValue: "huge") == .normal)
        #expect(FontScale(storedValue: "") == .normal)
    }

    @Test("slider index 往返")
    func sliderIndexRoundTrip() {
        for (i, scale) in FontScale.allCases.enumerated() {
            #expect(scale.sliderIndex == i)
            #expect(FontScale(sliderIndex: i) == scale)
        }
    }

    @Test("slider index 越界钳制到边界档位")
    func sliderIndexClamps() {
        #expect(FontScale(sliderIndex: -1) == .small)
        #expect(FontScale(sliderIndex: 99) == .xLarge)
    }
}
