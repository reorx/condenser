import Foundation
import Testing
@testable import CondenserKit

// 标注（schema v18）：envelope 的 note/annotations 解码，与引文三元组的重定位。
// 计划：kb/plans/2026-08-24-annotations.md。
//
// 锚点是 {quote, prefix, suffix}（W3C TextQuoteSelector），锚在**屏幕显示的派生
// 文本**上——四个源的正文都是 Kit 派生的，app 升级 = 派生管线可能变，所以 offset
// 不可靠，重定位必须是「搜引文、上下文挑最像」的纯函数；找不到 = 孤儿（nil），
// 引文与评论仍可见，不静默丢数据。

@Suite("Annotation models")
struct AnnotationModelTests {
    private let decoder = JSONDecoder.condenserAPI

    @Test("envelope 带 note/annotations 时解码完整")
    func decodesNoteAndAnnotations() throws {
        let json = #"""
        {"source": "hn", "key": "hn:42", "datetime": "2026-08-24T01:00:00Z",
         "is_read": false, "is_saved": false,
         "note": "整体想法",
         "annotations": [
           {"id": 1, "quote": "quoted text", "prefix": "before ", "suffix": " after",
            "block": 2, "comment": "有意思", "created_at": "2026-08-24T01:02:03Z"},
           {"id": 2, "quote": "bare", "prefix": "", "suffix": "",
            "block": null, "comment": null, "created_at": "2026-08-24T01:02:04Z"}
         ]}
        """#
        let item = try decoder.decode(TimelineItem.self, from: Data(json.utf8))
        #expect(item.note == "整体想法")
        let anns = try #require(item.annotations)
        #expect(anns.count == 2)
        #expect(anns[0].id == 1)
        #expect(anns[0].quote == "quoted text")
        #expect(anns[0].prefix == "before ")
        #expect(anns[0].block == 2)
        #expect(anns[0].comment == "有意思")
        #expect(anns[1].block == nil)
        #expect(anns[1].comment == nil)
    }

    @Test("旧服务器不带这两个字段：解码为 nil，不炸")
    func decodesWithoutFields() throws {
        let json = #"""
        {"source": "hn", "key": "hn:42", "datetime": "2026-08-24T01:00:00Z",
         "is_read": true, "is_saved": true}
        """#
        let item = try decoder.decode(TimelineItem.self, from: Data(json.utf8))
        #expect(item.note == nil)
        #expect(item.annotations == nil)
    }
}

@Suite("Annotation relocation")
struct AnnotationRelocationTests {
    private func ann(
        _ quote: String, prefix: String = "", suffix: String = "", block: Int? = nil
    ) -> ItemAnnotation {
        ItemAnnotation(
            id: 1, quote: quote, prefix: prefix, suffix: suffix, block: block,
            comment: nil, createdAt: nil)
    }

    private func text(of location: AnnotationLocation, in blocks: [String]) -> String {
        String(blocks[location.block][location.range])
    }

    @Test("唯一命中：直接定位")
    func uniqueHit() throws {
        let blocks = ["The quick brown fox jumps over the lazy dog."]
        let loc = try #require(locateAnnotation(ann("brown fox"), in: blocks))
        #expect(loc.block == 0)
        #expect(text(of: loc, in: blocks) == "brown fox")
    }

    @Test("多处命中：prefix/suffix 挑最像的那处")
    func contextDisambiguates() throws {
        let blocks = ["say cat here, then cat there, finally cat done"]
        let loc = try #require(
            locateAnnotation(ann("cat", prefix: "then ", suffix: " there"), in: blocks))
        let before = String(blocks[0][..<loc.range.lowerBound])
        #expect(before.hasSuffix("then "))
    }

    @Test("跨块的多处命中：上下文挑对块")
    func contextPicksBlock() throws {
        let blocks = ["the word target sits here", "another target lives elsewhere"]
        let loc = try #require(
            locateAnnotation(ann("target", prefix: "another ", suffix: " lives"), in: blocks))
        #expect(loc.block == 1)
    }

    @Test("派生管线的空白漂移仍命中（换行/多空格差异）")
    func whitespaceDriftStillHits() throws {
        // 标注时正文是一行；管线升级后同一段被断成了两行 + 缩进
        let blocks = ["An idea that\n  spans lines now."]
        let loc = try #require(locateAnnotation(ann("idea that spans lines"), in: blocks))
        #expect(loc.block == 0)
        let hit = text(of: loc, in: blocks)
        #expect(hit.hasPrefix("idea"))
        #expect(hit.hasSuffix("lines"))
    }

    @Test("正文里已无引文：孤儿，返回 nil")
    func orphanReturnsNil() {
        let blocks = ["completely different text"]
        #expect(locateAnnotation(ann("vanished quote"), in: blocks) == nil)
    }

    @Test("block 提示失效（块序重排）：全文搜兜底")
    func staleBlockHintFallsBack() throws {
        // 标注时引文在块 3；重排后它在块 0，且块 3 已不存在
        let blocks = ["the anchor phrase is here"]
        let loc = try #require(locateAnnotation(ann("anchor phrase", block: 3), in: blocks))
        #expect(loc.block == 0)
    }

    @Test("block 提示 + 多处等价命中：提示的块优先")
    func blockHintBreaksTies() throws {
        let blocks = ["repeat me", "repeat me"]
        let loc = try #require(locateAnnotation(ann("repeat me", block: 1), in: blocks))
        #expect(loc.block == 1)
    }

    @Test("空 blocks / 空引文：nil，不越界")
    func degenerateInputs() {
        #expect(locateAnnotation(ann("x"), in: []) == nil)
        #expect(locateAnnotation(ann(""), in: ["some text"]) == nil)
        #expect(locateAnnotation(ann("   "), in: ["some text"]) == nil)
    }
}
