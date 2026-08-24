import Foundation

// 高亮标注的重定位（计划 2026-08-24-annotations.md 决策 5）。
//
// 锚点锚在**屏幕显示的派生文本**上：四个源的正文都是 Kit 派生的（X 经 t.co →
// display_url 替换，HN/RSS 经 HTML → 纯文本管线），app 升级 = 派生管线可能变，
// 快照冻结的是 payload 不是派生文本——所以 offset 是锚在流沙上，重定位只信引文：
// 搜 `quote` 的所有出现位置，多处命中用 prefix/suffix 挑最像；找不到 = 孤儿
// （返回 nil，UI 在抽屉尾部列出引文与评论，不静默丢数据）。`block` 仅是搜索提示
// （分数打平时优先提示的块），真值永远是引文。
//
// 空白容差：派生管线最常见的漂移就是断行/缩进变化，所以精确搜不到时把正文与引文
// 都做「空白折叠」（连续空白 → 单空格）再搜一次，命中后映射回原文本的索引区间。

/// 一次成功重定位：第几个正文块 + 块内字符区间（喂给高亮渲染）。
public struct AnnotationLocation: Equatable, Sendable {
    public let block: Int
    public let range: Range<String.Index>

    public init(block: Int, range: Range<String.Index>) {
        self.block = block
        self.range = range
    }
}

/// 在正文块序列里重新定位一条标注；nil = 孤儿高亮。
/// 单块正文（TG/HN/X）就传单元素数组，`location.block` 恒为 0。
public func locateAnnotation(_ annotation: ItemAnnotation, in blocks: [String]) -> AnnotationLocation? {
    let quote = annotation.quote.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !quote.isEmpty, !blocks.isEmpty else { return nil }

    var candidates: [(block: Int, range: Range<String.Index>)] = []
    for (index, block) in blocks.enumerated() {
        for range in exactOccurrences(of: quote, in: block) {
            candidates.append((index, range))
        }
    }
    if candidates.isEmpty {
        // 空白折叠兜底：管线漂移（断行、缩进、空格数）不该把标注变成孤儿
        for (index, block) in blocks.enumerated() {
            for range in foldedOccurrences(of: quote, in: block) {
                candidates.append((index, range))
            }
        }
    }
    guard !candidates.isEmpty else { return nil }
    if candidates.count == 1 {
        return AnnotationLocation(block: candidates[0].block, range: candidates[0].range)
    }

    // 多处命中：上下文最像者胜，分数打平时 block 提示是唯一的裁判
    let prefix = foldWhitespace(annotation.prefix ?? "")
    let suffix = foldWhitespace(annotation.suffix ?? "")
    var best = candidates[0]
    var bestScore = -1
    for candidate in candidates {
        let block = blocks[candidate.block]
        let before = foldWhitespace(String(block[..<candidate.range.lowerBound].suffix(80)))
        let after = foldWhitespace(String(block[candidate.range.upperBound...].prefix(80)))
        var score = 2 * (commonSuffixLength(prefix, before) + commonPrefixLength(suffix, after))
        if candidate.block == annotation.block { score += 1 }
        if score > bestScore {
            bestScore = score
            best = candidate
        }
    }
    return AnnotationLocation(block: best.block, range: best.range)
}

// MARK: - 搜索

private func exactOccurrences(of needle: String, in hay: String) -> [Range<String.Index>] {
    var out: [Range<String.Index>] = []
    var from = hay.startIndex
    while from < hay.endIndex, let r = hay.range(of: needle, range: from..<hay.endIndex) {
        out.append(r)
        from = hay.index(after: r.lowerBound)
    }
    return out
}

/// 空白折叠后的文本 + 「折叠字符位 → 原文本区间」的映射。
/// 折叠规则：任意连续空白（含换行）→ 单个空格；一个折叠字符位对应原文本里
/// 它覆盖的整个区间，命中区间由首字符的起点和末字符的终点拼回。
private struct FoldedText {
    let text: String
    let starts: [String.Index]
    let ends: [String.Index]
}

private func fold(_ s: String) -> FoldedText {
    var text = ""
    var starts: [String.Index] = []
    var ends: [String.Index] = []
    var i = s.startIndex
    while i < s.endIndex {
        if s[i].isWhitespace {
            let runStart = i
            while i < s.endIndex, s[i].isWhitespace { i = s.index(after: i) }
            text.append(" ")
            starts.append(runStart)
            ends.append(i)
        } else {
            text.append(s[i])
            starts.append(i)
            i = s.index(after: i)
            ends.append(i)
        }
    }
    return FoldedText(text: text, starts: starts, ends: ends)
}

private func foldWhitespace(_ s: String) -> String {
    fold(s).text
}

private func foldedOccurrences(of needle: String, in hay: String) -> [Range<String.Index>] {
    let foldedNeedle = foldWhitespace(needle).trimmingCharacters(in: .whitespaces)
    guard !foldedNeedle.isEmpty else { return [] }
    let folded = fold(hay)
    var out: [Range<String.Index>] = []
    for r in exactOccurrences(of: foldedNeedle, in: folded.text) {
        let lo = folded.text.distance(from: folded.text.startIndex, to: r.lowerBound)
        let hi = folded.text.distance(from: folded.text.startIndex, to: r.upperBound)
        out.append(folded.starts[lo]..<folded.ends[hi - 1])
    }
    return out
}

// MARK: - 上下文打分

private func commonPrefixLength(_ a: String, _ b: String) -> Int {
    var count = 0
    for (x, y) in zip(a, b) {
        guard x == y else { break }
        count += 1
    }
    return count
}

private func commonSuffixLength(_ a: String, _ b: String) -> Int {
    var count = 0
    for (x, y) in zip(a.reversed(), b.reversed()) {
        guard x == y else { break }
        count += 1
    }
    return count
}
