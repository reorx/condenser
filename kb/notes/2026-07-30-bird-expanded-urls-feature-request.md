---
created: 2026-07-30
tags:
  - x-source
  - bird
  - upstream
  - feature-request
---

# bird feature request：简化 JSON 输出携带展开后的链接（expanded URLs）

## 背景（内部）

condenser 的 X 信源经由 probe 调用 `bird … --json` 拿数据。推文正文里的链接全部是
t.co 短链——这不是 bird 或我们的解析弄坏的：**X 服务端本来就把正文里所有链接改写成
t.co**，原始链接只存在于 API 响应的 `entities.urls[]` 元数据里（X 官方 UI 靠它做替换
渲染）。bird 的简化 JSON（`--json`）没有输出这份元数据；`--json-full` 的 `_raw` 里有，
但单条推从 ~363B 涨到 ~20.6KB（约 57×），作为常规采集路径太重。

三个方案（A: probe 切 `--json-full` + 服务端摘取；B: 服务端 HTTP 解短链；C: 上游加字段）
中选了 **C——请 bird 作者在简化 JSON 里加一个 `urls` 数组**（bird 对 `media` 已经是这么
做的，模式现成）。本文档就是准备递给作者（steipete，npm `@steipete/bird`）的 issue 草稿。

实测环境：bird 0.8.0（npm 最新版，2026-01-19 发布）。GitHub 仓库 `steipete/bird` 当前
404（可能私有），所以走 issue 还是别的渠道由 Reorx 联系时再定。

若上游不响应，回退方案 A 的要点记录在案：probe 三条 feed 命令都支持 `--json-full`；
服务端 `parse_tweet` 从 `_raw.legacy.entities.urls` 摘取（长文推另看 `note_tweet` 的
entity set，被引推文在 `quoted_status_result` 里有同样一份）；`raw` 存档前剥掉 `_raw`
控制体积；历史行救不回（已存 raw 里没有 entities），可用方案 B 一次性 backfill。

---

## Issue draft（可直接粘贴）

**Title: Include expanded URLs (`entities.urls`) in simplified `--json` output**

### Problem

Tweet text as returned by X's API always contains t.co-wrapped links — the
original URLs only exist in the `entities.urls[]` metadata. bird's simplified
`--json` output drops that metadata, so consumers are left with bare t.co links
they cannot resolve without an extra HTTP round-trip per link:

```console
$ bird read 2082693056269029651 --json
{
  "id": "2082693056269029651",
  "text": "https://t.co/qzYxwreb9x",
  ...
}
```

The information is present in the raw API response — `--json-full` shows it under
`_raw.legacy.entities.urls`:

```json
{
  "url": "https://t.co/qzYxwreb9x",
  "expanded_url": "https://haotianzheng.com/?t=202607291001",
  "display_url": "haotianzheng.com/?t=202607291001",
  "indices": [0, 23]
}
```

But `--json-full` is a heavy answer for feed consumers: for this tweet the output
grows from 363 bytes to 20.6 KB (~57×), since `_raw` carries the entire GraphQL
response. Anyone building a reader/archiver on top of `bird home` / `user-tweets
--json` currently has to choose between broken links and a 57× payload.

### Proposal

Add a `urls` array to the simplified tweet JSON, populated from
`legacy.entities.urls` — the same pattern the simplified output already uses for
`media`:

```json
{
  "id": "2082693056269029651",
  "text": "https://t.co/qzYxwreb9x",
  "urls": [
    {
      "url": "https://t.co/qzYxwreb9x",
      "expandedUrl": "https://haotianzheng.com/?t=202607291001",
      "displayUrl": "haotianzheng.com/?t=202607291001",
      "indices": [0, 23]
    }
  ],
  ...
}
```

(Field naming/casing entirely up to you — camelCase shown to match the existing
output; keeping X's snake_case as-is would be just as useful.)

With `url` + `indices`, consumers can do exactly what X's own UI does: replace
the t.co span in `text` with `displayUrl` as label and `expandedUrl` as href.

### Details worth covering

- **Long-form posts (articles / notes)**: their link entities live in
  `note_tweet.note_tweet_results.result.entity_set.urls` rather than
  `legacy.entities`; ideally the `urls` array merges both so consumers don't
  need to know the distinction.
- **Quoted tweets**: the nested `quotedTweet` object would benefit from the same
  `urls` array (its entities are under `quoted_status_result` in the raw
  response).
- **Media t.co links**: `legacy.entities.media[].indices` identifies the
  trailing t.co that points at the tweet's own media. Exposing those indices
  (e.g. on the existing `media` items, or as a top-level hint) would let
  consumers strip that dangling t.co from `text` the way X's UI hides it. Nice
  to have, separable from the main ask.
- **Omit-when-empty** keeps the output byte-identical for tweets without links,
  so existing consumers are unaffected.

### Why not just follow the redirects?

Resolving t.co server-side costs one HTTP request per link, is rate-limited, and
loses `display_url`/`indices` (needed for faithful in-text replacement). The
data is already in every response bird receives — it just gets dropped during
simplification.

Happy to test a build. Thanks for bird — it's the backbone of a self-hosted
X reader I run, and this is the only gap we've hit in the simplified output.

---

## 相关文档

- [urls 字段落地 plan](../plans/2026-07-30-x-expanded-urls.md) — bird 发布该功能后 condenser 侧的接入实施计划
- [X source local probe 方案](../plans/2026-07-24-x-source-local-probe.md) — probe/bird 采集链路的出处
- [X Following feed 方案](../plans/2026-07-30-x-following-feed.md) — 最近一次 bird 输出形态的实测记录
