---
created: 2026-07-30
tags:
  - x-source
  - bird
  - frontend
  - ios
  - plan
---

# X 推文短链展开 —— bird `urls` 字段落地 plan

## 0. 前置条件与现状

**这个 plan 依赖上游**:bird 需要先在简化 JSON(`--json`)里输出 `urls` 数组
(feature request 全文:`kb/notes/2026-07-30-bird-expanded-urls-feature-request.md`)。
在 bird 发布该功能之前,本 plan 不可开工;发布之后,**第一步永远是用真实 bird 输出
重新生成 fixtures 并核对实际字段名**——我们请求的形状是
`urls: [{url, expandedUrl, displayUrl, indices}]`,但作者最终采用的命名/大小写可能
不同(snake_case 也完全可能),下文所有字段名以实测为准调整。

问题成因(已查证,2026-07-30):X 服务端把推文正文里的所有链接改写成 t.co,原始
链接只在 API 响应的 `entities.urls[]` 元数据里;bird 0.8.0 的简化 JSON 丢掉了这份
元数据,`--json-full` 有但单条 20.6KB(57×)太重。所以走上游加字段的路。

**验收基准推文**:`https://x.com/JustZht/status/2082693056269029651` —— text 为
`https://t.co/qzYxwreb9x`,应展开为 `https://haotianzheng.com/?t=202607291001`
(display: `haotianzheng.com/?t=202607291001`)。

## 1. 目标

推文正文里的 t.co 短链,在所有阅读表面(web 卡片、iOS 卡片、详情 pane、link
preview)显示为原始链接的样子:**锚文本用 `display_url`,href 用 `expanded_url`**
——即 X 官方 UI 的行为。数据侧把 urls 元数据入库存档,老数据不受影响、优雅降级。

## 2. 数据层(schema v12 + parse + ingest)

- `x_tweets` 加 `urls` TEXT 列(JSON list),**SCHEMA_VERSION 11 → 12**,
  shape-based `ALTER TABLE ADD COLUMN`(v5/v9 的老模式)。历史行 NULL。
- 这是一个**可重建的派生列**(`is_filtered` / `x_embeddings` 精神):`raw` 原样
  存档,所以任何 raw 里带 urls 的行都能重新抽取——bird 升级之后、本功能部署之前
  ingest 的行,可以用一次性脚本补齐(§7)。
- `x.parse_tweet` 抽取:isinstance 容错(照 `media` 的写法),**在解析边界归一化
  成我们自己的稳定形状** `[{url, expanded_url, display_url, indices}]`(snake_case,
  缺失字段置 None)。与 `media` 的 bird-shape passthrough 不同,这里做归一化,理由:
  bird 的命名在它发布前是未知数,且 web + iOS 两个客户端都要消费这个字段——在唯一
  的解析入口吸收上游命名,好过两个客户端各自兼容两套大小写。`quotedTweet` 嵌套里的
  urls 同样抽取(引文推的正文一样有 t.co)。
- `ingest_tweets`:urls 随 tweet 行写入/刷新(它属于推文本体,走 refresh 路径,
  和 media/metrics 一致;feed 行不涉及)。
- **probe 零改动**:仍用 `--json`,新字段随 bird 升级自然出现在输出里,`raw`
  存档自动带上。probe 机器上 `npm i -g @steipete/bird@<新版本>` 即完成升级。

## 3. Envelope(`items.py` + `sources/x.py`)

- `sources/x.py` 的 SELECT 投影加 `t.urls AS urls, q.urls AS q_urls`。
- `items.x_envelope` 的 x payload 与嵌套 quote 各加 `urls` 字段(`_json_field`
  解析,None 安全)。**纯增量**——shipped iOS builds 的 decoder 忽略未知字段,
  不破坏任何已装客户端。
- saved records 无需专门处理:X 快照存的就是 envelope payload,urls 自动随行,
  `records.py` 回放时原样带出(`_json_field` 已接受 already-parsed 值)。

## 4. Web 渲染

- **替换策略:按 t.co 字符串精确匹配,不用 indices。** indices 基于 X 原始 text
  的码位偏移,而 `bodyText` 会剥 `RT @orig:` 前缀、长文推还会剥标题——偏移会错位;
  t.co URL 本身是全局唯一 token,直接字符串匹配既稳又简单。indices 只存不用。
- `lib/linkify.tsx` 增强(或前置一个 `expandTco(text, urls)` 变换):遇到与某个
  `urls[].url` 匹配的 t.co,渲染成锚文本 `display_url` + href `expanded_url`;
  不匹配任何 urls 条目的 t.co 维持现状(老数据、bird 未升级时的降级路径)。
- `XCard.tsx` / `XQuoteCard.tsx` 把 payload 的 urls 传进渲染;detail pane /
  `extractUrls` 处理 X 文本的地方先做展开替换,让 link preview 直接抓原始 URL
  (更好的元数据,也不必跟着 t.co 跳转)。
- **尾部 media t.co(可选子步骤,单独测试)**:带图/视频推文正文尾部有一个指向
  推文自身的 t.co(media 永久链接,如 fixture 里 `SLOP COP https://t.co/…`)。
  保守启发式:text 末尾的 t.co + 不在 urls[] 里 + 推文有 media → 隐藏,X 官方
  UI 就是这么处理的。若 bird 顺手输出了 media indices 则改用精确判定。

## 5. iOS

- Kit `Models.swift`:`XTweet` / `XQuote` 加 `urls: [XUrlEntity]?`(容错 decode,
  字段缺失 → nil,老服务器不影响新客户端)。
- `bodyText` 保持不动(它管剥前缀);渲染侧(app target 的 `Linkify.swift` /
  `TruncatableText` 路径)按 §4 同样的字符串匹配策略替换 attributed string 里的
  t.co 为 display 文本 + expanded href。detail sheet 同样生效。
- 尾部 media t.co 的隐藏逻辑放 Kit(纯逻辑可测),与 web 同一条启发式。

## 6. 明确的非目标 / 可选项

- **通道 C 的 prompt 喂展开后的链接**(t.co 把商家域名藏起来了,promo 判定其实
  受害)——真实收益但动了抽取输入,等于换了抽取器语料;若做,单独决定是否伴随
  `TAXONOMY_VERSION` bump,**不在本 plan 内**。通道 D 的 tokenizer 本来就丢 URL,
  不受影响。
- **bird 升级前的历史行**(raw 里没有 urls):不救。方案 B(服务端 HTTP 解 t.co
  重定向)可做一次性 backfill,但不属于本 plan。
- `forward.py` 的 X 转发是纯链接(fixupx),不涉及正文渲染,零改动。

## 7. 一次性补齐脚本

`tmp/backfill_x_urls.py`(uv script):扫 `x_tweets` 中 `urls IS NULL AND raw`
带 urls 字段的行,重跑 `parse_tweet` 抽取并 UPDATE。覆盖"bird 已升级、本功能未
部署"窗口期的行。幂等,只写 `urls` 一列(extension-column 纪律)。

## 8. BDD 测试清单(先写测试)

1. `parse_tweet`:urls 存在 → 归一化形状;缺失/非 list/条目缺字段 → None 或跳过
   该条目,不 raise;quotedTweet 里的 urls 同样抽取。
2. `ingest_tweets`:urls 入库;re-push 刷新;老 fixture(无 urls)行为不变。
3. envelope:x payload + quote 带 urls;saved record 回放带 urls;NULL → 字段为
   null 不炸。
4. web:`linkify`/`expandTco` 单测(匹配替换、无匹配降级、锚文本与 href 正确);
   XCard 快照;尾部 media t.co 隐藏的三个分支(有 media 且不在 urls / 在 urls /
   无 media)。
5. iOS Kit:decode 容错;替换逻辑;media t.co 启发式。
6. fixtures:用升级后的真实 bird 输出经 `tmp/make_x_fixtures.py` 重新生成,新旧
   形状各留样本(降级路径要有真数据钉住)。

## 9. 上线顺序

1. probe 机器升级 bird,`bird read <验收推文> --json` 确认 urls 形状,重生成
   fixtures,按实测形状校准 §2 的字段名。
2. 后端 + web(同一 image):纯增量,**push master 即部署**(v12 迁移自动跑,
   老 iOS 不受影响)。部署后按惯例 ssh 实测 schema_version 与一条新推的 urls 列。
3. 跑 §7 补齐脚本(如有窗口期数据)。
4. iOS rebuild + 重装,随时。

## 相关文档

- [bird feature request 草稿](../notes/2026-07-30-bird-expanded-urls-feature-request.md) — 上游依赖,含问题查证全过程与回退方案 A/B
- [X source local probe 方案](../plans/2026-07-24-x-source-local-probe.md) — probe/ingest 链路与 `raw` 存档契约的出处
