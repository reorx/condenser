---
created: 2026-10-25
tags:
  - keyword-filter
  - cjk
  - telegram
  - frontend
---

# 关键词过滤：拉丁文按整词匹配，中日韩按包含匹配

## PRD

### 背景

关键词过滤是把含某个词的 Telegram 消息从时间线里静默藏掉。现在的规则是「不分大小写的子串」：只要文本里出现这几个字母就算命中，不管它是不是一个独立的词。

2026-10-25 想过滤 `arc`（Arc 浏览器），预览里却出现了 `harrychen.xyz/archive/`、`quietsearch-kagi` 这类链接。用线上库只读实测了一遍（4295 条带文本的消息），子串匹配对短英文词的误伤非常普遍：

| 关键词 | 子串命中 | 按词边界 | 被误伤的典型例子 |
|---|---|---|---|
| arc | 78 | 2 | archives、counterpointresearch、quietsearch |
| ad | 193 | 15 | iPadOS、roadmap、advice |
| pr | 364 | 13 | Pro、processes、projects |
| rust | 47 | 42 | trust、VirusTotal |
| mac | 56 | 28 | macOS、Machine |
| gpt | 138 | 88 | ChatGPT |
| 起床时间 | 113 | 113 | 无 |

`arc` 按词边界剩下的 2 条，正好都是在说 Arc 浏览器。过滤的错误是不对称的：多藏了用户看不到也不知道，少藏了用户还能看见、再补一条规则。所以误伤比漏网更糟，必须解决。

同时 mac 丢了 macOS、gpt 丢了 ChatGPT，说明整词匹配有时也会漏掉用户想藏的东西，用户需要一个自己放宽的办法。

中日韩文字不用空格分词，不能照搬英文的做法。实测过用中文分词来判断「是不是一个词」，结果被它排除的几乎都是真命中：「中文版」「中文翻译」「币圈」「人民币」「苹果公司」「很长时间」。经典的跨词误伤（`中文` 命中「其中文件」）在 1197 条里一次没出现。中文复合词由语素拼成，「包含这个语素」基本就是用户的本意。

### 目标

用户输入一个英文关键词时，只藏掉真正提到这个词的消息，不误伤包含这串字母的长词和链接。中日韩关键词保持现在的「包含即命中」。需要更宽的匹配时，用户能自己放宽，而且在预览里就能看到「有多少条因为只是包含而没被藏」。

### 功能与交互

**1. 匹配规则**

关键词两端各自判断：

- 这一端是英文等用空格分词的文字里的字母或数字，就要求这一端在词的边界上，即文本里紧挨着的那个字符不能是这类字母或数字。
- 这一端是中日韩文字、标点或符号，这一端不加限制。
- 中日韩文字、空格、标点、emoji、下划线，对英文词来说都算边界。很多消息里英文直接贴着汉字写（线上 16% 的消息如此），「我觉得arc是垃圾」里的 arc 必须能命中。
- 韩文虽然用空格分词，但助词直接黏在名词后面（삼성은），所以和中日文一样按包含匹配。

例子：

| 关键词 | 命中 | 不命中 |
|---|---|---|
| `arc` | 我觉得arc是垃圾、Arc 浏览器、arc.net、#arc、arc_browser | archive、quietsearch |
| `arc浏览器` | 用arc浏览器 | search浏览器 |
| `#ad` | 这条是 #ad | #adverts |
| `c++` | 学 c++ 的 | abc++ |
| `iPhone 15` | iPhone 15 Pro | iPhone 150 |
| `zhihu.com` | www.zhihu.com/question | — |
| `起床时间` | 今天的起床时间是 | — |
| `中文` | 中文版、其中文件（包含即命中，已知并接受） | — |

大小写照旧不区分。关键词里的空格可以对应文本里的多个空格或换行：`open ai` 也命中 `open  AI`。

链接里的百分号编码（`%E8%B3%AD` 这类）不参与匹配，否则 `ad` 会命中 `%AD`。

**2. 用 `*` 放宽**

关键词开头或结尾加 `*`，那一端就不再要求词边界：

- `arc*`：以 arc 开头的词，包括 archive、arcs
- `*gpt`：以 gpt 结尾的词，包括 ChatGPT
- `*arc*`：任何位置，即现在的子串行为

只有开头和结尾的 `*` 有这个作用，中间的 `*` 按普通字符处理。中日韩关键词本来就是包含匹配，加不加 `*` 没有区别。去掉 `*` 和空白后什么都不剩的关键词（`*`、`**`）不能创建，预览和创建都会提示关键词为空。

`*` 写在关键词里，过滤规则列表上一眼就能看出这条是哪种匹配，不需要另外的开关。

**3. 预览**

创建规则时点 Preview，看到的内容和真实过滤严格一致：

- 计数（Will hide N of the last 1000 messages）按新规则算。
- 高亮只标真正命中的位置。一条消息因为提到 Arc 被命中时，同一条里的 archive 不会被标黄。
- 命中位置在长消息后部时，样本从命中处前面一点开始截取，开头加省略号，保证高亮能看见。
- 英文关键词的预览多一行提示，说明有多少条只是在更长的词里包含了这个关键词，因此不会被藏，并给出一个例子和建议写法，例如「76 more messages only contain "arc" inside a longer word, like "archives". They stay visible. Use arc*」。点建议写法会把输入框换成它，用户再点一次 Preview 看新结果。
- 没有这类消息、或者关键词两端都已放宽时，不显示这行提示。

**4. 说明文案**

创建对话框和 Filters 页面的说明，从「case-insensitive substring」改成说明新规则：英文按整词，中日韩按包含，`*` 放宽。

**5. 已有规则**

上线后所有频道的过滤结果按新规则重算一次，用户不需要做任何事。线上目前只有一条规则「起床时间」，命中数不变（113 = 113）。

### 不做的事

- 中文分词：实测排除掉的几乎都是真命中。
- 正则规则：`*` 已经覆盖实测里的需求。
- 例外词（过滤「币」但放过「硬币」）：数据里还没出现这种需求，记进 `kb/todo.md`。
- 把关键词过滤扩到 HN、X、RSS：现在只作用于 Telegram，另记 todo。
- 全角字母归一（`ＡＲＣ`）：线上 0 条。
- 搜索侧的百分号编码误命中：搜索 `ad` 也会搜到 `%AD`，另记 todo。
- 每条规则单独的「整词 / 包含」开关。

### 验收标准

- [x] 过滤 `arc` 时，预览不再出现 archive、quietsearch 这类链接；「我觉得arc是垃圾」和「拥抱 AI 的 Arc 浏览器」仍然命中。
- [x] 过滤 `arc*` 命中 archive；`*gpt` 命中 ChatGPT；`*arc*` 命中 quietsearch。
- [x] 过滤 `ad` 时，`广告ad促销` 命中，`%E8%B3%AD` 这样的链接不命中。
- [x] 过滤 `中文` 时，「中文版」「其中文件」都命中。
- [x] 预览的高亮只落在真正命中的位置，命中在长消息后部时也能看到高亮。
- [x] `arc` 的预览显示「只是包含」的条数、一个例子和建议写法 `arc*`，点建议写法会替换输入框内容。
- [x] 输入 `*` 预览或创建时，提示关键词为空，不会创建规则。
- [x] 上线后「起床时间」的过滤结果不变。

## Tech Design

### 现状

- `condenser/filters.py`：
  - `active_patterns(channel_id)` 读出全局规则加该频道的规则，并转成小写。
  - `text_is_filtered(text, patterns)` 是 `any(p in text.lower())`。
  - `_recompute` 先把范围内的 `is_filtered` 清 0，再把命中的置 1。
  - `recompute_for_rule_change(None)` 只重算 `db.enabled_channel_ids()`，也就是已启用的 Telegram 订阅。
- 调用点：
  - 入库：`condenser/tg.py` 的 `_on_new_message`、`_backfill_channel`、`fetch_older` 调 `filters.recompute_messages`。
  - 规则增删：`condenser/routers/subscriptions.py` 的 `create_filter` / `delete_filter`。
  - 预览：`preview_filter` 扫描最近 `PREVIEW_SCAN_LIMIT = 1000` 条，用 `filters.text_is_filtered(r[3], [pattern.lower()])` 判断；样本取前 20 条，`text` 截前 300 字（`PREVIEW_TEXT_TRUNCATE`）。
- 存储：`keyword_filters` 表（`db.KeywordFilter`：`id` / `channel_id`，NULL 表示全局 / `pattern` / `created_at`）。`add_filter` 按原样存 `body.pattern`，不做 strip。请求体是 `condenser/types.py` 的 `FilterScopeBody`。
- 前端：
  - `frontend/src/components/filters/HighlightedText.tsx` 用 JS `indexOf` 自己做一遍子串高亮，和后端是两套实现。
  - `FilterPreviewSample` 把 `pattern` 传给它，`FilterPreviewResult` 渲染计数和样本，`CreateFilterDialog` 持有 `pattern` 状态并调 `api.previewFilter`。
  - 说明文案在 `CreateFilterDialog.tsx`（DialogDescription）和 `frontend/src/pages/FiltersView.tsx:60`。
  - 类型在 `frontend/src/lib/types.ts` 的 `FilterPreviewSample` / `FilterPreviewResult`。
  - iOS 不调用 `/api/filters*`，只间接读取时间线里已经落库的 `is_filtered` 结果。
- 版本标记的先例：
  - `search.ensure_index()` 由 `db.init_db` 末尾调用，靠 `app_meta['search_index_version']` 判断要不要重建。
  - `_backfill_rss_excerpts` 用 `RSS_EXCERPT_VERSION`。
  - `_backfill_hn_admission` 在函数内延迟 import，避免循环依赖。
- CJK 区间定义在 `condenser/search.py:65` 的 `_CJK_RANGES = '㐀-鿿぀-ヿ가-힯'`，是私有常量。
- 现有测试在 `tests/test_backend.py`：
  - `test_timeline_excludes_filtered_and_groups_album`
  - `test_filter_is_case_insensitive_substring`（`广告ad促销` 被 `AD` 命中）
  - `test_global_filter_create_list_and_preview`
  - `test_preview_scoped_to_channel`
  - `test_backfill_persists_filters_and_marks_done`
  - `test_realtime_ingest_filtered_and_new_poll`

### 方案

把关键词编译成一个正则：

- 中间是转义后的关键词，空白换成 `\s+`。
- 两端按「端点字符是不是空格分词文字的字母数字」，决定要不要加负向环视：`(?<!W)` / `(?!W)`，其中 `W = [^\W_{CJK}]`。
- `*` 打开对应的一端。
- 一个频道的全部规则合成一个 `re.IGNORECASE` 的交替正则。

匹配前把文本里的 `%XX` 替换成等长的 `\0\0\0`。这样不会有命中落在编码内部，邻居也把它当边界，而且偏移不变。命中位置由服务端算好返回给预览，前端只负责渲染。

matcher 的语义带一个版本号。版本不一致时，启动时重算所有频道的 `is_filtered`。

关键决策：

1. **自定义边界，不用 `\b`。** Python 和 JS 都把汉字算作 `\w`，`我觉得arc是垃圾` 里的 arc 两侧不算 `\b`。线上 16% 的消息里英文贴着汉字写。`W` 排除 `_`、和 `search.py` 的切词一致，于是 `arc_browser` 命中 `arc`。
2. **CJK 保持子串，不上分词。** 依据是 jieba 对齐的实测（PRD 背景）。韩文也按子串。和搜索的现有语义一致：拉丁文整词，CJK 子串。
3. **`*` 语法，不加「匹配模式」列。** 不需要 schema 迁移，规则列表能直接显示语义，iOS 也不受影响。可发现性靠预览的 near-miss 提示弥补。被否决的是 `keyword_filters.match_mode` 列加 UI 开关：要迁移，要多一个控件，信息量和 `*` 一样。
4. **用 `re.IGNORECASE` 匹配原文，不先 `lower()`。** `lower()` 会改变某些字符的长度（`'İ'.lower()` 是 2 个码点），偏移就对不上原文了。百分号编码的遮罩也是等长替换。所以服务端返回的偏移可以直接对应原文。
5. **高亮由服务端返回码点偏移。** 前端用 `Array.from(text)` 按码点切分。被否决的方案：前端自己实现同一套正则。JS 和 Python 的 Unicode 字符类不一样，两套实现迟早会不一致，现在的 bug 有一半就出在前端高亮。
6. **版本号触发全量重算，不做迁移。** `is_filtered` 是可重建缓存（`kb/docs/database.md`）。重算在 `db.init_db` 末尾、`search.ensure_index()` 之后，用延迟 import 调用，沿用 `_backfill_hn_admission` 的先例。`filters` 在模块顶部 import 了 `db`，`db` 不能在顶部 import `filters`。marker 在全部频道重算完以后才写；中途崩溃的话下次启动重来，重算是幂等的，不需要事务。
7. **全局规则变更和版本重算，都覆盖 `messages` 里出现过的所有频道。** 现在 `recompute_for_rule_change(None)` 只算已启用的订阅，暂停中的频道会留着旧标记，重新启用后也不会重算。版本重算必须覆盖全部频道，否则旧语义的标记会残留。两条路径用同一个范围，顺带补上这个缺口。代价是扫全部 Telegram 消息：线上 5160 条，正则匹配在毫秒级。

被否决的大方向：

- 复用 FTS 索引做过滤。它能和搜索完全一致，还天然覆盖四个源；但过滤会静默隐藏内容，不该依赖一个在 FTS5 不可用时会降级的缓存，而且 FTS 做不了 `*gpt` 这样的后缀匹配。
- 正则规则：有 ReDoS 风险，而且需求不足。

### 数据变动

- 不改表结构，`SCHEMA_VERSION` 保持 21。`keyword_filters.pattern` 原样存储，`*` 是关键词文本的一部分。
- 新增 `app_meta` 键 `keyword_filter_matcher_version`，值为 `filters.MATCHER_VERSION`（本次为 `1`）。没有这个键，表示库里的 `is_filtered` 是按旧子串语义算的，启动时会全量重算。
- 新建规则时，服务端对 `pattern` 做 `strip()` 后存储。已有规则不回写。
- 在 `kb/docs/database.md` 的 rebuildable cache 段落补一句：`is_filtered` 跟着 `MATCHER_VERSION` 重算。

### 逻辑变动

**`condenser/text.py`**

- 新增公开常量 `CJK_RANGES = '㐀-鿿぀-ヿ가-힯'`。text.py 没有包内 import，放在这里 items 安全。
- `search.py` 把 `_CJK_RANGES` 改成从 `text` import，删掉本地定义。`ngram.py` 的字面量不动，它是另一个用途的正则。

**`condenser/filters.py`**（重写 matcher 部分，更新模块 docstring 说明新语义和理由）

- `MATCHER_VERSION = 1`、`MATCHER_META_KEY = 'keyword_filter_matcher_version'`，注释写明什么时候要 bump：任何改变「哪些文本命中」的修改。
- `parse_rule(pattern) -> Optional[tuple[str, bool, bool]]`：返回 `(core, open_start, open_end)`。去掉首尾空白，记录首尾有没有 `*`，再 `strip('*')` 并去空白。core 为空时返回 `None`。不抛异常，由调用方决定是返回 422 还是跳过。
- `rule_regex(core, open_start, open_end) -> str`：
  - 中间：`core.split()` 后逐个 `re.escape`，再用 `r'\s+'` 连接。
  - 头：没有放开、且 `core[0]` 是空格分词文字的字母数字时，加 `(?<![^\W_{CJK_RANGES}])`。
  - 尾：同理，加 `(?![^\W_{CJK_RANGES}])`。
- `compile_rules(patterns) -> Optional[re.Pattern]`：跳过 `parse_rule` 为 `None` 的旧数据，把剩下的拼成 `(?:…)|(?:…)` 并用 `re.IGNORECASE` 编译。全部无效或列表为空时返回 `None`。
- `prepare(text) -> str`：`re.sub(r'%[0-9A-Fa-f]{2}', '\0\0\0', text)`。docstring 写明等长替换是偏移正确的前提。
- `text_is_filtered(text, matcher) -> bool`：`text` 或 `matcher` 为空时返回 False，否则 `matcher.search(prepare(text))`。签名从 `patterns: list[str]` 改为接收编译好的 matcher。
- `match_spans(text, matcher) -> list[tuple[int, int]]`：在 `prepare(text)` 上 `finditer`，返回码点偏移。
- `active_patterns` 不再 `lower()`。`_recompute` 每个频道编译一次 matcher。
- `recompute_for_rule_change(None)` 改为遍历 `db.message_channel_ids()`。
- `ensure_materialized() -> None`：marker 等于 `MATCHER_VERSION` 就返回；否则对 `db.message_channel_ids()` 逐个 `recompute_channel`，然后 `db.set_meta`，并 log 重算了多少个频道。
- near-miss 辅助函数 `near_miss_example(text, core, open_start, open_end) -> Optional[tuple[str, str]]`：
  - 用全放开的 matcher（`*core*`）在 `prepare(text)` 上找第一个命中，向两侧扩展连续的空格分词字母数字，得到所在的词，例如 `archives`。
  - 按向哪侧扩展过，生成建议写法：原本已放开的一端保留 `*`，向左扩展过就在开头加 `*`，向右扩展过就在结尾加 `*`。
  - 返回 `(word, suggestion)`。

**`condenser/db.py`**

- 新增 `message_channel_ids() -> list[int]`：`SELECT DISTINCT channel_id FROM messages`。
- `init_db` 末尾在 `search.ensure_index()` 之后加：

  ```python
  from . import filters  # deferred: filters imports this module
  filters.ensure_materialized()
  ```

**`condenser/routers/subscriptions.py`**

- `create_filter`：先用 `filters.parse_rule(body.pattern)` 校验，`None` 时返回 422，detail 为 `keyword is empty`；然后存 `body.pattern.strip()`。
- `preview_filter`：
  - 空白关键词照旧短路返回 0。
  - `parse_rule` 为 `None` 时返回 422。
  - 用 `compile_rules([pattern])` 算 `matched`。
  - 样本新增 `highlights: [[start, end], …]`，是相对返回 `text` 的码点偏移。
  - 样本截取改为围绕第一个命中：第一个命中的结尾在 `PREVIEW_TEXT_TRUNCATE` 以内时，照旧取前 300 字；否则从 `max(0, hit_start - PREVIEW_CONTEXT)` 开始取 300 字（`PREVIEW_CONTEXT = 60`），开头加 `…`，偏移相应平移，并裁掉窗口外的部分。抽成本模块的小函数 `_excerpt(text, spans)`。
  - 响应新增 `near_misses: {count, core, example, suggestion} | null`：只有至少一端要求边界时才计算。count 是「严格 matcher 不命中、`*core*` 命中」的消息数，example 和 suggestion 取自第一条这样的消息。count 为 0 时返回 `null`。

**`frontend/src/lib/types.ts`**

- `FilterPreviewSample` 加 `highlights: [number, number][]`，注释说明是码点偏移。
- `FilterPreviewResult` 加 `near_misses: { count: number; core: string; example: string; suggestion: string } | null`。

**`frontend/src/components/filters/HighlightedText.tsx`**

- props 改为 `{ text: string; ranges: [number, number][] }`，用 `Array.from(text)` 按码点切分后渲染 `<mark>`。删除内部的 indexOf 逻辑。

**`frontend/src/components/filters/FilterPreviewSample.tsx`**

- 去掉 `pattern` prop，改为传 `sample.highlights`。

**`frontend/src/components/filters/FilterPreviewResult.tsx`**

- 去掉 `pattern` prop。
- 新增 `onUseSuggestion: (pattern: string) => void`。
- `near_misses` 非空时，在 summary 下方渲染一行 muted 文案：`{count} more messages only contain "{core}" inside a longer word, like "{example}". They stay visible.`，后面跟一个 link 样式按钮 `Use {suggestion}`。
- 文案里的 `{core}` 取自 `near_misses.core`，也就是去掉 `*` 后的关键词。用户输入的 `arc*` 不会原样出现在提示里。

**`frontend/src/components/filters/CreateFilterDialog.tsx`**

- 把 `onUseSuggestion={setPattern}` 传给 `FilterPreviewResult`。现有 effect 会在 pattern 变化时清掉预览，用户再点 Preview。
- DialogDescription 改为：`Hide messages that mention the keyword (case-insensitive). English and other spaced words match whole words only; Chinese, Japanese and Korean match anywhere. Add * to match inside words: arc* also hides archive.`
- placeholder 改为 `e.g. promo, arc*, 广告`。

**`frontend/src/pages/FiltersView.tsx`**

- 页头说明的 `(case-insensitive substring)` 改为 `(whole words; * to widen)`。

**文档**

- `AGENTS.md` 的 `filters.py` 一行补语义：英文整词、CJK 子串、`*` 放宽，以及改匹配语义要 bump `MATCHER_VERSION`。
- `frontend/AGENTS.md` 更新 `FilterPreviewResult` / `HighlightedText` 两行：服务端给偏移，前端只渲染。
- `kb/docs/database.md` 加一句（见「数据变动」）。

### 实施步骤

- [x] 写 `tests/test_filters.py`，用表驱动的方式先写行为用例（BDD，先红），覆盖 PRD 例子表、`*` 放宽、百分号编码、空格、`parse_rule` 的空值、`match_spans` 偏移（前面带 emoji）、near-miss 例子和建议写法。
- [x] `text.CJK_RANGES` 加常量，`search.py` 改为 import 它；`uv run pytest tests/test_search.py` 保持绿。
- [x] 按「逻辑变动」实现 `filters.py` 的新 matcher、`ensure_materialized` 和 `db.message_channel_ids`，`tests/test_filters.py` 转绿。
- [x] `db.init_db` 末尾接入 `ensure_materialized`。写测试：先手工把一条在新语义下不命中的消息置 `is_filtered = 1`，删掉 marker，再跑 `ensure_materialized`；断言标记被清掉、marker 已写入。再写一条：暂停中的频道在全局规则变更后也被重算。
- [x] 改 `routers/subscriptions.py` 的 create / preview。在 `tests/test_backend.py` 补 API 用例：`*` 返回 422、`highlights` 的偏移、长消息的样本窗口、`near_misses`。现有测试 `test_filter_is_case_insensitive_substring` 改名为 `test_filter_latin_keyword_matches_next_to_cjk`，断言不变。`uv run pytest` 全绿。
- [x] 前端：改 types、`HighlightedText`、`FilterPreviewSample`、`FilterPreviewResult`、`CreateFilterDialog`、`FiltersView` 的文案。补 vitest：`HighlightedText` 码点偏移（emoji 在命中前面），`FilterPreviewResult` 的 near-miss 行和点击回调。`pnpm test`、`pnpm build` 通过。
- [x] 本地实机验收，见「测试与验证」。截图归档到 `tmp/2026-10-25-keyword-filter-word-boundary/`。
- [x] 更新 `AGENTS.md`、`frontend/AGENTS.md`、`kb/docs/database.md`，然后提交。push 就是部署，先问用户。
- [x] 上线后 ssh 只读核对：`app_meta['keyword_filter_matcher_version'] = '1'`；`SELECT sum(is_filtered) FROM messages` 和上线前一样（只有「起床时间」一条规则；计划时是 113，2026-10-27 上线前只读基线是 116，本地证据在 `tmp/2026-10-25-keyword-filter-word-boundary/evidence/prod-baseline.txt`）。2026-10-27 部署 `d11597a` 后核对：marker 为 `'1'`，116 → 116。

### 测试与验证

| 验收标准 | 自动测试 | 实机 |
|---|---|---|
| `arc` 不命中 archive / quietsearch，命中贴着汉字和带空格的 arc | `test_filters.py` 表驱动用例 | 本地 dev 后端挂 `tmp/condenser.db` 的副本，预览 `arc` 并截图 |
| `arc*` / `*gpt` / `*arc*` | 同上 | 预览 `*gpt` |
| `ad` 命中 `广告ad促销`，不命中 `%AD` | 同上，加改名后的 API 用例 | — |
| `中文` 命中「其中文件」 | 同上 | — |
| 高亮只落在命中处；长消息能看到高亮 | `match_spans` / `_excerpt` 单测，`HighlightedText` vitest | 预览截图，选一条命中在 300 字以后的消息 |
| near-miss 提示和建议写法 | API 用例，`FilterPreviewResult` vitest | 预览 `arc` 后点 `Use arc*`，输入框变成 `arc*` |
| `*` 返回 422 | API 用例 | 输入 `*` 点 Preview，看到错误提示 |
| 已有规则结果不变 | `ensure_materialized` 测试 | 上线后 ssh 核对 113 |

实机用 `agent-browser`，手机宽度视口（截图里的问题出现在 iPhone Safari 上）。先 `scripts/dev-browser-login.sh` 登录，并确认 dev 后端是带 `--reload` 启动的。在 `tmp/` 下用快照的副本，不碰原快照。

可以复用的实测脚本：`tmp/filter_semantics_probe.py`（线上只读，`ssh hh-hk-01 "docker exec -i condenser-condenser-1 /app/.venv/bin/python -" < tmp/filter_semantics_probe.py`），以及 `tmp/filter_cjk_probe.py`（本地快照，需要 `--with jieba`）。上线前后各跑一次第一个脚本，可以作为对照。

### 风险与待定

- **`(?<!…)` 里的字符类加 IGNORECASE。** Python 的 lookbehind 要求定宽，单字符类满足。测试里要覆盖大写字母贴着关键词的情况（`ARChive`）。
- **CJK 区间不全。** 区间不含扩展 B 以后的生僻字（星平面）和半角片假名。这些字符会被当作空格分词文字的字母，贴着它们的英文词不会命中。影响极小，在注释里说明即可。
- **near-miss 的建议写法只看第一条例子。** 如果大部分 near miss 是前缀、而第一条恰好是后缀，建议写法会偏。可以接受，用户能在预览里看到结果后自己改。
- **全量重算在启动路径上。** 线上 5160 条消息，正则匹配是毫秒级。Telegram 消息不在留存清理范围内，会持续增长，但到十万条量级仍然是秒级。如果哪天变慢，再挪到后台线程。
- **旧的无效规则。** 如果库里存在一条 `*`，`compile_rules` 会跳过它，它就不再生效（旧语义下它命中所有含 `*` 的消息）。线上没有这类规则。
