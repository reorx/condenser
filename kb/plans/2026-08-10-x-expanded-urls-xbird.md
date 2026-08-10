---
created: 2026-08-10
tags:
  - x-source
  - xbird
  - frontend
  - ios
  - plan
---

# X 推文短链展开 —— xbird `urls` 字段实施计划

> **取代** [2026-07-30 针对 bird 上游的旧 plan](2026-07-30-x-expanded-urls.md)。旧 plan 的
> 前置条件是"等 bird 作者响应 feature request"；2026-08-07 probe 已迁移到自家的 xbird 库,
> 上游依赖不复存在——加字段就是本仓库的一次普通提交。condenser 侧的设计(归一化、渲染
> 策略、降级路径)大体沿用旧 plan,但**schema 版本号、上线顺序、xbird 侧步骤全部重写**,
> 以本文为准。

## 0. 问题与现状(不变的部分)

X 服务端把推文正文里所有链接改写成 t.co,原始链接只在 API 响应的
`legacy.entities.urls[]` 元数据里(X 官方 UI 靠它做替换渲染)。xbird 的简化输出
(即 probe 推给 condenser 的 wire shape,`to_json(tweet)`)继承了 bird 的形状,同样
丢掉这份元数据——`map_tweet_result` 根本没读它。

**验收基准推文**(沿用):`https://x.com/JustZht/status/2082693056269029651` —— text 为
`https://t.co/qzYxwreb9x`,应展开为 `https://haotianzheng.com/?t=202607291001`
(display: `haotianzheng.com/?t=202607291001`)。

## 1. 目标

推文正文里的 t.co 短链,在所有阅读表面(web 卡片、iOS 卡片、详情 pane、link
preview)显示为原始链接:**锚文本用 `display_url`,href 用 `expanded_url`**——即 X
官方 UI 的行为。数据侧把 urls 元数据入库存档,老数据不受影响、优雅降级。

## 2. xbird 侧(第一步,独立发版)

照 `lang` 字段的先例做(commit `097d53b`,1.1.0):增量扩展、缺失时不输出键、
COMPATIBILITY.md 记录、golden 全绿即兼容性证明。

- `types.py`:新增 `TweetUrl(BirdModel)` —— `url: str`、`expanded_url: str | None`、
  `display_url: str | None`、`indices: list[int] | None`。`BirdModel` 的
  `alias_generator=to_camel` 让 wire shape 自动是 `{url, expandedUrl, displayUrl,
  indices}` —— 恰好是当年 feature request 草稿请求的形状,不用再"以实测为准猜命名"。
  `TweetData` 加 `urls: list[TweetUrl] | None = None`(None → 键省略,老输出字节不变)。
- `parsing/tweets.py`:新增 `extract_urls(result)`,合并两个来源:
  `legacy.entities.urls`(普通推)+ `note_tweet.note_tweet_results.result.entity_set.urls`
  (长文推——`extract_note_tweet_text` 已经在读同一层,路径现成)。isinstance 容错,
  空列表 → None。`map_tweet_result` 加一行 `urls=extract_urls(result)`;
  **quoted tweet 免费获得**——`map_tweet_result` 对 `quoted_status_result` 递归,
  不需要单独处理。
- 测试:`test_parsing_tweets.py` 照 lang 的两条模式(有 → 映射正确且出现在 dump;
  无 → None 且键不在 dump),另加长文推 entity_set 合并、条目缺字段容错。
  跑 golden 套件:lang 那次零改动全绿(golden 的合成节点不带该字段);若某个 golden
  的 raw fixture 恰好带 `entities.urls`,diff 就是本功能本身——按 COMPATIBILITY.md
  的增量条款处理,不算破坏。
- COMPATIBILITY.md 增量条目 + CHANGELOG,版本 **1.2.0**。
- 实测验收:`xbird read 2082693056269029651 --json` 输出 urls 数组,形状核对。

**可选,不建议现在做**:media 尾部 t.co 的精确 indices(`legacy.entities.media[].indices`)。
condenser 侧的启发式(§5)已够用,xbird 保持最小改动;若启发式日后出错再回来加。

## 3. probe:零代码改动

lang 先例原样重演:`uv lock --upgrade-package xbird` + `launchctl kickstart -k
gui/$(id -u)/com.condenser.probe`。新字段随 `to_json` 自然出现在 push 里,`raw`
存档自动带上。注意 probe 的 launchd 部署陷阱(AGENTS 概览有记):kickstart 之后
再改代码是不生效的,升级顺序是先 lock 后 kickstart。

## 4. condenser 数据层(schema v13 + parse + ingest)

- `x_tweets` 加 `urls` TEXT 列(JSON list),**SCHEMA_VERSION 12 → 13**,shape-based
  `ALTER TABLE ADD COLUMN`(v5/v9 的老模式)。历史行 NULL。
  ⚠️ 旧 plan 写的是 v11 → 12,但 **v12 已被全文搜索(2026-08-09)占用**,不要照抄。
- 这是一个**可重建的派生列**(`is_filtered` / `x_embeddings` 精神):`raw` 原样存档,
  所以任何 raw 里带 urls 的行都能重新抽取(§8 的补齐脚本)。
- `x.parse_tweet` 抽取:isinstance 容错(照 `media` 的写法),**在解析边界归一化成
  snake_case** `[{url, expanded_url, display_url, indices}]`(缺失字段置 None)。
  与 media 的 passthrough 不同仍要归一化,理由更新过但结论没变:wire 是 camelCase
  (xbird 的 to_camel),而 condenser 的 DB 列、envelope、两个客户端全是 snake_case
  ——在唯一的解析入口转一次,好过下游各转各的。`quotedTweet` 嵌套里的 urls 同样抽取。
- `ingest_tweets`:urls 随 tweet 行写入/刷新(推文本体,走 refresh 路径,和
  media/metrics 一致;feed 行不涉及)。

## 5. Envelope 与渲染(沿用旧 plan,要点重述)

**Envelope**(`items.py` + `sources/x.py`):SELECT 投影加 `t.urls, q.urls AS q_urls`;
x payload 与嵌套 quote 各加 `urls`(`_json_field` 解析,None 安全)。纯增量,shipped
iOS builds 忽略未知字段。saved records 免费获得(X 快照存的就是 envelope payload)。

**Web**:
- **替换策略:按 t.co 字符串精确匹配,不用 indices。** indices 基于 X 原始 text 的
  码位偏移,`bodyText` 剥 `RT @orig:` 前缀、长文推剥标题后会错位;t.co URL 是全局
  唯一 token,字符串匹配既稳又简单。indices 只存不用。
- `lib/linkify.tsx` 增强(或前置 `expandTco(text, urls)` 变换):匹配到 `urls[].url`
  的 t.co → 锚文本 `display_url` + href `expanded_url`;不匹配的 t.co 维持现状
  (老数据、probe 未升级时的降级路径)。
- `XCard.tsx` / `XQuoteCard.tsx` 传入 urls;detail pane / `extractUrls` 先做展开替换,
  link preview 直接抓原始 URL(更好的元数据,也不必跟着 t.co 跳转)。
- **尾部 media t.co(可选子步骤,单独测试)**:text 末尾的 t.co + 不在 urls[] 里 +
  推文有 media → 隐藏(X 官方 UI 的行为)。

**iOS**:
- Kit `Models.swift`:`XTweet` / `XQuote` 加 `urls: [XUrlEntity]?`(容错 decode,
  缺失 → nil)。
- `bodyText` 不动;渲染侧(`Linkify.swift` / `TruncatableText` 路径)按同一条字符串
  匹配策略替换 attributed string。detail sheet 同样生效。尾部 media t.co 启发式放
  Kit(纯逻辑可测)。

## 6. 搜索(新增,旧 plan 没有——2026-08-09 全文搜索是它之后才有的)

`search.py` 的 X 文档目前只喂 text,里面是 t.co——搜 `haotianzheng` 找不到那条验收
推文。把 `expanded_url` + `display_url` 拼进 X 的 per-item 文档(tokenizer 本来就
"只丢无法输入进搜索框的东西",URL 保留是它的立场),**`TOKENIZER_VERSION` +1**,
下次启动自动重建索引(v12 的既有机制,80ms 级,无迁移)。建议做——改动是几行,
且这是"存档优先"原则的自然延伸;若想砍范围,单独成一小步不阻塞主线。

## 7. 明确的非目标(沿用)

- **通道 C 的 prompt 喂展开后的链接**(t.co 把商家域名藏起来,promo 判定受害)——
  真实收益但等于换抽取器语料,若做需单独决定是否伴随 `TAXONOMY_VERSION` bump,
  不在本 plan 内。通道 D 的 tokenizer 本来就丢 URL,不受影响。
- **xbird 升级前的历史行**(raw 里没有 entities):不救。HTTP 解重定向的 backfill
  是独立决定。
- `forward.py` 的 X 转发是纯链接(fixupx),零改动。

## 8. 一次性补齐脚本(沿用)

`tmp/backfill_x_urls.py`(uv script):扫 `x_tweets` 中 `urls IS NULL AND raw` 带
urls 字段的行,重跑 `parse_tweet` 抽取并 UPDATE。覆盖"probe 已升级、本功能未部署"
窗口期的行。幂等,只写 `urls` 一列(extension-column 纪律)。

## 9. BDD 测试清单(先写测试)

1. xbird:§2 的清单(两条 lang 模式 + entity_set 合并 + 容错 + golden)。
2. `parse_tweet`:urls 存在 → 归一化 snake_case;缺失/非 list/条目缺字段 → None 或
   跳过,不 raise;quotedTweet 里的 urls 同样抽取。
3. `ingest_tweets`:urls 入库;re-push 刷新;老 fixture(无 urls)行为不变。
4. envelope:x payload + quote 带 urls;saved record 回放带 urls;NULL → null 不炸。
5. web:`expandTco`/linkify 单测(匹配替换、无匹配降级、锚文本与 href);XCard;
   尾部 media t.co 三分支(有 media 且不在 urls / 在 urls / 无 media)。
6. iOS Kit:decode 容错;替换逻辑;media t.co 启发式。
7. 搜索(若做 §6):expanded URL 可被查到;TOKENIZER_VERSION bump 触发重建。
8. fixtures:用升级后的真实 xbird 输出经 `tmp/make_x_fixtures.py` 重新生成,新旧
   形状各留样本(降级路径要有真数据钉住)。

## 10. 上线顺序

1. xbird:实现 + 测试 + 版本 1.2.0,merge 到 master(xbird 不发 PyPI,probe 依赖
   git branch master + uv.lock pin)。
2. probe 机器:`uv lock --upgrade-package xbird` → kickstart → 下一轮 push 的 raw
   开始携带 urls(条 §3 的顺序陷阱)。用 `xbird read <验收推文> --json` 实测形状,
   重生成 condenser fixtures。
3. condenser 后端 + web(同一 image):纯增量,**push master 即部署**(v13 迁移自动
   跑,老 iOS 不受影响)。部署后按惯例 ssh 实测 schema_version 与一条新推的 urls 列。
4. 跑 §8 补齐脚本(如有窗口期数据)。
5. iOS rebuild + 重装,随时。

## 相关文档

- [针对 bird 上游的旧 plan](2026-07-30-x-expanded-urls.md) — 被本文取代;condenser 侧设计的出处
- [bird feature request 草稿](../notes/2026-07-30-bird-expanded-urls-feature-request.md) — 问题查证全过程(t.co 成因、`--json-full` 57× 体积、方案 A/B/C 取舍);wire shape 的形状请求最终由 xbird 原样实现
- [probe 从 bird CLI 迁移到 xbird 的 session](../sessions/2026-08-07-probe-bird-cli-to-xbird-library.md) — 本 plan 前置条件消失的原因
- [X source local probe 方案](2026-07-24-x-source-local-probe.md) — probe/ingest 链路与 `raw` 存档契约的出处
