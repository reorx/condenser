---
created: 2026-08-08
tags:
  - search
  - fts5
  - sqlite
  - multi-source
  - frontend
---

# 全文搜索 (Full-Text Search)

> **状态：已实现（2026-08-09），schema v12。** 步骤 1–5 全部落地，529 backend +
> 121 frontend 绿；验收在 `tmp/2026-08-09-full-text-search/`（对真实 dev 库跑的，
> 那个库当时还是 schema 11，所以 v11→v12 回填也一并验了）。
> 实施中相对本文的三处改动，理由见 AGENTS.md 的「全文搜索」段：
> ① **TG 按显示单元索引**（锚点 = 相册最小 id），不是 §1 表里写的「每条原始行一条」
>    —— 意图一样（一个卡片一条结果），但查询侧不再需要去重，`total` 和翻页也跟着干净了；
>    四个 TG 写路径本来就拿到 `DisplayMessage`，反而更省。
> ② **X 清理的反连接对 `x_feed_items`**，不是 §3 写的 `x_tweets`：正文可能比 feed 行活得久
>    （还有推文引用它），而那种推文已经不是时间线条目，搜到了会点开一片空白。
> ③ 顺手补了一条 §3 没列的级联：`mark_hn_story_dead` —— 时间线的排名本来就排除 dead 故事，
>    搜索不该是唯一还在提供它们的界面。
> §4 的耗时判据实测过（`tmp/search_rebuild_timing.py`）：快照上 2630 条 80ms，
> 按线上真实行数外推 ~0.3s，所以留在 `init_db` 内联，不需要后台线程。
> §8 的非目标全部保持非目标（iOS UI、命中高亮、拼音/jieba、comments 表、末词前缀、相关度调优）。
>
> **代码评审后的修正（同日）**，两条改了本文默认的语义，值得单独记：
> * **§0「单字 CJK 用前缀匹配解决」是有洞的**：前缀只能命中「以该字开头」的 token，
>   所以一个字如果落在 CJK run 的**末尾**就完全搜不到 ——「猫」找不到「我买了一只猫」
>   （真实归档里验到的例子：「大连站日本分站」搜不到「站」）。修法是**索引侧**每个 run
>   额外发一个末字 token，**查询侧不发**（发了「中文搜索」就变成 `"中文 文搜 搜索 索"`，
>   只能匹配以它结尾的文本，「中文搜索工具」反而搜不到）。两个方向都有测试钉住。
>   `TOKENIZER_VERSION` 因此升到 2。
> * **§5「TG `is_filtered=1` 排除」按整个显示单元判，不是按锚点行**：`is_filtered` 是
>   逐行物化的，而相册的说明文字通常在 sibling 上，只看锚点会把整个相册放行，卡片还会把
>   被过滤的那段文字渲染出来——等于用被禁的关键词就能搜到它。这里比时间线更严格是有意的。

对所有 feed 条目(Telegram / Hacker News / X)做全文搜索,提供专门的搜索界面。
入口在左侧导航栏 Saved 之下,进入即为搜索页;搜索面向全部条目,支持信源 filter
(可细到单个 TG 频道 / 单个 X feed)与状态 filter(unread / saved,默认 all)。

## 0. 调研结论与已定决策

### 环境实测(2026-08-08,不是推断)

- 本地:SQLite 3.50.4,FTS5 ✓,trigram tokenizer ✓
- 生产容器(`python:3.12-slim`,ssh 实测):SQLite **3.46.1**,FTS5 ✓,trigram ✓
- peewee 3.19,playhouse 自带 FTS5Model(本计划不用它,理由见下)

即:**FTS5 引擎零安装成本,两端可用**。真正的问题是中文分词。

### 分词方案对比

| 方案 | 结论 |
|---|---|
| FTS5 内置 `trigram` | 淘汰 — 查询词必须 ≥3 字符,中文双字词(「模型」「编程」)搜不到 |
| [wangfenjin/simple](https://github.com/wangfenjin/simple) C++ 扩展 | 淘汰 — 中文体验最好(含拼音),但不在 PyPI,要为 macOS arm64 + linux x86_64 编译分发二进制,CI 也要带;与 sqlite-vec「一个包」的依赖节俭先例冲突 |
| **Python 侧预分词 + FTS5 标准表**(选定) | 入库前把文本变成「拉丁词 + CJK 字符 bigram」空格连接;查询同预处理,CJK 段作 phrase 查询。零依赖,双字词可搜,与 `ngram.py` 的 CJK bigram 先例同构(那里已论证过不引入 jieba) |

方案要点:`"中文搜索"` 索引为 `中文 文搜 搜索` 三个 token(unicode61 下 CJK
字符属 Lo 类别,bigram 不会被再切);查询 `中文搜索` 构建为 phrase
`"中文 文搜 搜索"`,位置连续性保证匹配语义 = 子串匹配。**单字 CJK 查询**用前缀
匹配解决:`猫` → `"猫" *`(prefix query),命中所有以该字开头的 bigram 和
单字 run 的 unigram,无需额外索引 unigram。

已知取舍:FTS5 的 `snippet()`/`highlight()` 返回分词后文本 — 无所谓,搜索结果
直接复用现有卡片整条渲染,不用 snippet。

### 用户已定决策(2026-08-08)

1. 分词:**Python 预分词**(方案 ③)
2. 排序:**时间倒序 / bm25 相关度,界面可切换**(默认时间倒序)
3. 范围:**排除** hidden_items 与 is_filtered(与所有 timeline 面一致;隐藏 = 永不再见)
4. **v1 仅 Web**,iOS 后续(API 是通用的,iOS 只差 UI)

## 1. 数据层 — `search.py` + `search_index` 表(SCHEMA_VERSION 12)

仿 `vectors.py` 先例:**只有 `condenser/search.py` 知道 FTS5 存在**,其余模块只调
它的函数;FTS5 不可用时(理论上不会,但降级成本低)全部退化为 no-op,
`/api/search` 返回 503 带说明。

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
  text,                -- 预分词后的空格连接文本(唯一被索引列)
  source UNINDEXED,    -- 'telegram' | 'hn' | 'x'
  ref1   UNINDEXED,    -- items.py 三元组
  ref2   UNINDEXED,
  ts     UNINDEXED     -- norm_ts 形式的排序时间戳
);
```

- 在 `db.init_db` 的表创建之后用原生 SQL 建(vec0 先例);不用 playhouse
  FTS5Model — UNINDEXED 列 + 自定义 upsert 语义下原生 SQL 更直白。
- 这是**可重建缓存**(`is_filtered` / `x_embeddings` 精神):原文都在源表里,
  `search.rebuild()` 是逃生舱,taxonomy 类变更(分词器改动)靠重建而非迁移。
- SCHEMA_VERSION 11 → **12**:升级即 `create_tables` + 全量回填(见 §4)。

### `search.py` 接口

| 函数 | 职责 |
|---|---|
| `setup()` | 建表;失败置 `available=False`(init_db 调用) |
| `tokenize(text) -> list[str]` | 搜索专用分词:lowercase,拉丁/数字词整词保留,CJK run → 字符 bigram(单字 run → unigram)。**与 `ngram.py.tokenize` 是两个函数**:那边为分类服务(丢 URL/@mention/停用词、加词对 bigram),搜索要的是召回 — URL 域名、@handle、停用词都必须可搜,所以不丢任何东西 |
| `build_match(q) -> str \| None` | 查询构建:同一分词,拉丁词 → `"word"`,CJK run ≥2 字 → bigram phrase `"b1 b2 …"`,单字 → `"字" *`;组间隐式 AND;双引号转义防 FTS5 语法注入;无有效 token → None |
| `index_item(source, ref1, ref2, text, ts)` | upsert(先 DELETE 三元组再 INSERT;空文本 = 只 DELETE) |
| `delete_item(s, r1, r2)` / `sweep_orphans()` | 删除级联用(§3) |
| `search(match, source?, channel_id?, feed?, status?, sort, offset, limit)` | MATCH + 状态/范围 join,返回 `(triple, ts)` 页 + total |
| `rebuild()` | 清空重建:扫 messages / hn_stories / x_feed_items⋈x_tweets 全量重灌 |

### 每个源索引什么文本

| 源 | key | 索引文本 | ts |
|---|---|---|---|
| TG | `tg:{cid}:{mid}` 每条原始行一条 | `messages.text`(空文本跳过);相册每个 sibling 各自索引,查询时按显示单元去重 | message date |
| HN | `hn:{sid}` | title + self-post text(先剥 HTML 标签) | first_seen_at(与 timeline 排序一致) |
| X | `x:{tid}` 仅有 feed row 的 tweet | 自身 text + article title + **被引推文的 text**(卡片显示什么就能搜什么);纯 embedded quote(无 feed row)不索引 — 它不是可渲染的 timeline 条目 | 按 dedup 优先级(account > following > For You)所在 feed 的排序时间,每次 re-push 时随 upsert 刷新 |

## 2. 写路径挂钩(`is_filtered` 的写侧物化先例)

| 路径 | 挂钩点 |
|---|---|
| TG 实时 ingest + **编辑**(`MessageEdited` 重派发) | `tg.py:_on_new_message` — 与 is_filtered 重算同一钩子;编辑天然覆盖(upsert) |
| TG backfill / fetch-older | backfill 存储路径,同样调 `index_item` |
| HN poll / backfill / snapshot refresh | `hn.py` 写 `hn_stories` 处;refresh 也 upsert(标题偶有编辑) |
| X ingest | `x.py:ingest_tweets` — 对产生/已有 feed row 的 tweet upsert;tweet 行刷新时文本可能变(编辑过的转推),一并覆盖 |

注意 telememo 的扩展列契约不受影响:`search_index` 是独立表,telememo 写路径
不碰它,由 condenser 的钩子负责。

## 3. 删除级联

| 删除路径 | 处理 |
|---|---|
| X 日常清理(`cleanup.py` XRetentionRule) | 在既有 step 3 反连接扫尾处增加:`DELETE FROM search_index WHERE source='x' AND ref1 NOT IN (SELECT id FROM x_tweets)` — 与 x_embeddings/x_attributes 同模式,自愈非本轮产生的孤儿 |
| TG 退订清档(`delete_channel_messages`) | 同函数内级联 `DELETE … WHERE source='telegram' AND ref1=?`;遵守该函数 docstring 惯例,写明**有意保留**什么(其它频道的行) |
| HN | 永不删除,无需处理 |

推论(写进测试):15 天保留期下,X 的搜索覆盖 = 最近 15 天 + 已读/已标注/已收藏
的全部历史 — 这是保留策略的固有属性,不是搜索的缺陷。

## 4. 回填与重建

- 升级到 v12 时(以及 `search_index` 为空但源表非空时)在 `init_db` 内联执行
  `rebuild()`。先在生产快照副本上**实测耗时**:预计语料 ~3-5 万行,分词 + 灌库
  应在秒级;若实测 >10s,改为启动后后台线程(cleanup 的 `asyncio.to_thread` 模式),
  期间 `/api/search` 返回「索引构建中」。
- `rebuild()` 同时是分词器变更后的升级手段:改 `tokenize` → bump 一个
  `SEARCH_TOKENIZER_VERSION` 常量存 `app_meta`,不匹配即重建(`model_tag` 契约的
  简化版)。

## 5. API — `GET /api/search`

```
GET /api/search?q=...&source=telegram&channel_id=123&feed=foryou
               &status=unread|saved&sort=recent|relevance&offset=0&limit=20
```

- 返回 `{items: [envelope...], total, has_more}` — envelope 即 `items.py` 现有信封,
  前端零新类型。
- 组装:FTS 命中三元组分页后,按源批量取行 → 复用现成构建器:TG 取相册 siblings
  经 `sources/telegram._serialize_unit`(相册多 sibling 命中先按
  `COALESCE(grouped_id,id)` 去重到单元锚点);HN 行 → `hn_envelope`;X 经
  `sources/x.get_row` → `x_envelope`。read/saved/feedback join 与 timeline 相同。
- 服务端强制排除:`hidden_items` 反连接、TG `is_filtered=1`。**不**按订阅
  enabled/aggregate 模式过滤 — 搜索面向整个归档(For You 全量可搜,暂停频道可搜);
  hidden/filtered 除外,因为那是对条目本身的判断。
- 排序:`recent` = `ts DESC`(默认);`relevance` = FTS5 `rank`(bm25)。
- 分页:offset/limit(语料量下无性能问题;搜索场景可接受结果漂移)。
- 校验:q 空白或无有效 token → 422;未知 source/status → 422;FTS 不可用 → 503。
- 认证:`require_auth`(cookie 或 device Bearer — API 即为将来 iOS 备好)。
- 路由放 `routers/search.py`。

## 6. Web UI

- **Sidebar**:Saved 之下、Filters 之上加 `Search` NavLink(lucide `Search` 图标)
  → `/search` 路由。更新 `frontend/CLAUDE.md` 组件清单(维护规则)。
- **`SearchView`**(`pages/`):`PageHeader`(IconBadge Search + 标题)+ 搜索输入框
  (自动聚焦,300ms debounce 触发)+ filter 行 + 结果列表。**查询与 filter 状态写入
  URL search params**(`?q=&source=&sub=&status=&sort=`),后退/分享/刷新可复现。
- **filter 行**(新组件,进 `components/` 清单):
  - 信源:两级选择,数据来自现成 `useSources` — All sources / 某源整体 / 某源下的
    订阅(TG 频道、X feed;HN 只有 front)。展示复用 `TgGlyph`/`HnGlyph`/`XGlyph`/
    `ChannelAvatar`/`XAvatar`。
  - 状态:segmented `All | Unread | Saved`(单选,默认 All)。
  - 排序:`最新 | 相关度` 切换。
- **结果列表**:`SavedMessageItem` 同构的行(完整日期行 + 按源分发的
  `MessageCard`/`HnCard`/`XCard`),`useInfiniteQuery` offset 翻页,底部
  「加载更多」/自动加载。顶部显示 `total` 条数。
- **不挂 scroll-to-read**(有意):搜索是翻档,不是刷 timeline,滚过不应标已读。
  卡片上的收藏、详情 pane、反馈等一切既有交互照常(它们不依赖 timeline query cache
  的部分即可用;优化 mutation 对 `['search']` cache 的同步在实现时按 `useFeedback`
  的既有模式加一个 queryKey)。
- 状态:未输入(提示文案)/ 加载 / 无结果 / 错误,四态齐全。

## 7. 实施步骤(BDD:每步先写行为测试)

1. **`search.py` 核心**:tokenize / build_match / setup / index_item / search /
   rebuild + SCHEMA_VERSION 12 + init_db 接线 + 回填。
   测试:CJK bigram 与 phrase 语义(双字词命中、跨词边界子串语义、单字前缀)、
   拉丁大小写、混排、FTS 语法注入(引号/`AND`/`*` 作为内容)、空文本 upsert 即删除、
   重建幂等、v11→v12 升级回填。**在生产快照副本上实测回填耗时**,决定内联/后台。
2. **写路径 + 删除级联**:四个 ingest 钩子 + TG 编辑覆盖 + cleanup 扫尾 +
   delete_channel_messages 级联。
   测试:每源 ingest 后可搜;TG 编辑后旧文本不可搜、新文本可搜;X 清理后未读旧推
   不可搜而已读/已藏仍可搜;退订清档后该频道不可搜。
3. **`GET /api/search`**:filter 组合、状态语义、hidden/filtered 排除、相册去重
   (命中任一 sibling 返回一个单元信封)、For You 全量可搜(不受 aggregate 模式限制)、
   两种排序、分页 has_more/total、422/503。
4. **Web UI**:Sidebar 入口、SearchView、filter 组件、结果列表、URL 状态。
   vitest 覆盖 filter 交互与查询状态;`frontend/CLAUDE.md` 清单同步更新。
5. **验收**:`scripts/dev-browser-login.sh` 登录真实 dev 后端,中文双字词、英文、
   混排、单字、各 filter 组合、排序切换逐项走查;截图归档
   `tmp/2026-08-08-full-text-search/`(或实际执行日期)。

## 8. 非目标(v1 明确不做)

- iOS UI(API 已通用,后续单独一步)
- 卡片内命中高亮(要侵入三种卡片组件;后续 polish,可基于查询词客户端做)
- 拼音搜索、jieba 词典分词(simple 扩展的领地;先验证 bigram 够不够用)
- telememo `comments` 表(条目正文之外的内容)
- search-as-you-type 的末词前缀匹配(可选 polish,`build_match` 留好口子)
- 相关度调优(bm25 默认参数;bigram 下相关度本就偏弱,默认排序是时间)

## 9. 风险与备忘

- **bigram 的子串语义**是特性也是噪音:「中文」会命中「其**中文**件」。与 simple
  扩展的字符级匹配同性质,接受;不接受时的出路是 jieba_query(见非目标)。
- FTS5 表体积 ≈ 再存一份分词文本 + 倒排,预计与源文本同量级(~10-20MB),
  纳入 cleanup 的 VACUUM 观察即可,不需要新机制。
- X 的 ts 随 dedup 优先级在 re-push 时可能变(新 feed 出现),搜索排序位置随之
  微调 — 与 timeline 行为一致,可接受。
- 部署顺序无约束:纯新增(新表 + 新端点 + 新页面),旧 iOS/web 客户端不受影响。
