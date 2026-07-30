---
created: 2026-07-30
tags:
  - plan
  - handoff
  - x-twitter
  - source
  - probe
  - timeline
---

# X Following 时间线接入

> **状态：六个步骤全部完成（2026-07-30），未部署。**
> 435 backend + 27 probe + 87 frontend 绿；端到端验收（真实 bird → dev backend，六个场景全过）
> 在 `tmp/2026-07-30-x-following/`，那里的 `README.md` 有逐条对照和可重跑的脚本。
> 实现与本文的偏差、以及落地后才知道的事，记在文末 §13「实施记录」。

**这是一份 handoff**：读这一篇 + 它引用的文件就能开工，不需要考古会话记录。

- 上游主计划（Phase 1–5 已全部完成）：[2026-07-24-x-source-local-probe.md](2026-07-24-x-source-local-probe.md)
- 判定相关（本计划不改判定，但去重规则会影响徽章可见性）：[2026-07-27-x-verdict-style-channels.md](2026-07-27-x-verdict-style-channels.md)
- 本次调研的原始采样与分析脚本：`tmp/2026-07-29-bird-following/`（一次性产物，不进代码库）
  - `following-1.json` / `following-2.json` — 连续两次 `-n 20`，用于重叠率
  - `following-n100.json` — `-n 100`，深度 / 组成 / 阈值分析的主样本
  - `following-full.json` — `--json-full`，用于确认 `_raw` 不带广告标记
  - `foryou-1.json` — For You 对照样本
  - `following-users-full.json` — 完整关注名单（732 个账号）
  - `analyze.py` / `depth.py` / `rate_and_ads.py` / `cutoff.py` — 产出本文所有数字的脚本

---

## 1. 一句话背景

X 源目前只采两种 feed：**For You**（算法流，firehose，默认不进聚合）和**单个关注账号**（逐个手动订阅）。
bird 0.8.0 的 `home --following` 能直接拿「正在关注」时间线——实测它**不是 firehose**，语义上等价于
「一次订阅你关注的全部账号」。本计划把它接成 X 源的第三种 feed，**全量进聚合时间线**。

## 2. 实测数据（决策依据，别跳过）

2026-07-29 用真实账号 @novoreorx 跑的采样，脚本和原始 JSON 都在 `tmp/2026-07-29-bird-following/`。

### 2.1 命令与输出格式

```bash
bird home --following -n 100 --json
```

输出格式和 `bird home`（For You）**完全一致**——同样的扁平 entry：
`id` / `text` / `createdAt` / `author{username,name}` / `authorId` / `replyCount` / `retweetCount` /
`likeCount` / `conversationId` / `media` / `quotedTweet` / `inReplyToStatusId`。

**`condenser/x.py:parse_tweet` 一行都不用改。**

### 2.2 它不是 firehose——这是本计划成立的前提

| | Following | For You |
|---|---|---|
| 连续两次调用的推文重叠 | **19/20** | 0/60（Phase 1 三次采样） |
| 与对方内容的重叠 | 0/20（完全增量） | — |
| 语义 | 稳定时间窗 | 每轮重采样 |

推论：**摄入量不再由 probe 频率决定**。For You 是「抓多少进多少」，Following 是「关注的人发了多少就是多少」。
`x_feed_items` 的 insert-only 幂等第一次真正起作用。

### 2.3 容量

单次 `-n 100`（`home` 没有 `--cursor` / `--all`，深度只能靠 `-n`，实测要 100 就真给 100）：

- 93 条有效内容，**89 条落在最新条目的 24h 内**，再往前只多 3 条 → 一次抓取基本掏空最近一天
- 分布很陡：最近 2.7h 占 73 条，之前 21h 只有 17 条（可能是 CST 早高峰，也可能 X 对 Following 本身做了截断/去重——732 个关注账号一天显然不止 90 条）

**量级判断：100–200 条/天。** 对比 TG ~50/天、For You 到达 57–136/天但只有 ~13% 判正。

### 2.4 两类特有噪音

**广告注入 7/100**——VPN、代理、谷歌 SEO、加密货币酒店/会议、hustle 网红。

- `--json-full` 的 `_raw` **不带** `promotedMetadata`（bird 只 dump tweet result 对象，不 dump timeline entry），
  实测 `promoted` / `advertiser` / `socialContext` 关键字命中 0/20 → **结构上认不出广告**
- 用 `bird following --all --json` 拿到的完整关注名单（732 个账号）做作者过滤：**7 条全中，0 误杀**
- 转推不受影响（`author` 是转推者本人，在名单里）
- 这次采样里 7 条广告的 `created_at` **全部超过 24h**（最年轻的 @kbwofficial 也有 36.6h），
  所以 §6 的 24h 规则顺手就是第一道闸。但**名单过滤不能省**——X 完全可能注入一条刚发布的广告

**线程祖先**——X 为了让你看懂上下文，会把线程里的老推一起塞进返回。实测 @zdyxry 的一个自我接龙：

| tweet id | created_at | conversationId | inReplyToStatusId |
|---|---|---|---|
| 1964259519556686186 | 2025-09-06 | 1964259…（自己） | 无 → 根帖 |
| 2048332765767291222 | 2026-04-26 | 1964259… | 1984401…（**没返回**） |
| 2082260430425358626 | 2026-07-29 00:22 | 1964259… | 2048332… |

bird 不区分「主条目」和「上下文条目」，一律平铺成独立 entry。若原样入库，前两条会按 `created_at`
插进 2025-09 和 2026-04 的时间线历史——你看不见它们，但**未读计数会 +2**。
注意中间那条的 `inReplyToStatusId` 指向的推**不在返回里**，所以这个上下文本身就是残缺的。

### 2.5 与 For You 的作者重叠

For You 一次 20 条采样里，**5 条（25%）的作者在关注名单里**（@dotey / @OpenAI / @lifesinger /
@emilkowalski / @tmr11235）。这决定了 §5 去重优先级的语义后果。

## 3. 已定的决策（用户拍板，不要重新论证）

| # | 决策 | 理由 |
|---|---|---|
| 1 | Following **进聚合时间线**，并带 `aggregate` 开关（`none`/`all`），默认 `all` | 量级只有 100–200/天，不是 firehose；开关保留是因为「暂停订阅」会连采集和训练数据一起停 |
| 2 | probe 15 分钟一轮 + 本地 seen 缓存，**只推增量** | 互动数停在首见值可接受；刷新另做详情页按需接口（§11） |
| 3 | 广告用**关注名单精确过滤**，名单由 probe 推、服务端存 | 服务端拥有归档，过滤规则事后可改；probe 端丢掉的就永远没了 |
| 4 | Following 条目 `created_at` 早于 **24h** 就不建 feed 行 | 见 §6 |
| 5 | 去重优先级：**单账号订阅 > following > foryou** | 见 §5 |
| 6 | 不做 `list-timeline`（X 列表源） | 用户当前没在用列表 |

### 3.1 一个被否掉的条件，别写回去

讨论中曾提出「早于 24h **且 tweet id 重复** 才丢弃」。**这个条件方向反了**：

- 线程祖先恰恰是**第一次见到的**（全新 id），加上「id 重复」前置条件它们会被放行，正好漏掉要治的病
- 「id 重复的老推」本来就是 no-op：`x_feed_items` 是 insert-only，重复推送既不产生新行也不改
  `first_seen_at`；何况 probe 的 seen 缓存会先把它们跳掉，根本推不上来

正确规则只有一句：**Following feed 的条目，`created_at` 早于 24h 就不建 feed 行**，不需要任何 id 条件。

## 4. 数据模型：X 消息的表结构零改动

现有拆分**已经就是**「所有 X 消息一张表 + 标注采集方式」的正解，而且比单表更强：

```
x_tweets       推文本体，一条推一行，PK = tweet_id（全局唯一）
x_feed_items   「某条推在某个 feed 里出现过」，PK = (channel_id, tweet_id)
```

`x_feed_items` 就是「采集方式」标注，只是被提成了独立的表。拆分理由（CLAUDE.md 原文）：
*一条推可以同时出现在 For You 和某个关注账号的 feed 里，而 verdict 只属于 For You 那次出现*。

如果做成「一张表 + `source_kind` 字段」，同一条推被两种方式采到只有两条路，都很糟：

- **存两行** → 正文、media、metrics、embedding、attributes 全部翻倍，判定要判两次，`item_feedback` 挂哪行说不清
- **覆盖成一行** → 丢掉「它也在 Following 出现过」这个事实，而这个事实恰恰决定了它按哪种规则进聚合

**Following 只是 `x_feed_items.channel_id` 的第三种取值。`x_tweets` / `x_feed_items` 一列都不加。**

唯一的新表是关注名单（§7），它和 X 消息无关。

### 4.1 新常量

```python
# condenser/x.py
FOLLOWING_FEED = 'following'
FOLLOWING_NAME = 'X Following'
```

`normalize_channel_id` 要像 `FORYOU_FEED` 一样特判它（`HANDLE_RE` 恰好也能匹配 `following` 这个字符串，
但必须显式早退，否则它会被当成一个叫 @following 的账号）。

## 5. 去重优先级

`condenser/sources/x.py` 已有去重，一条推在多个 feed 出现只保留 rank 1：

```sql
-- 现状
ROW_NUMBER() OVER (
  PARTITION BY f.tweet_id
  ORDER BY (f.channel_id = 'foryou') ASC, f.first_seen_at ASC
)
```

窗口函数跑在**已经套了 scope 过滤和准入谓词的子查询里**（`_visible` / `_scope_where` 的注释解释了为什么
必须在里面：否则一条推的 For You 副本被准入规则过滤掉后，它拿到 rank 2 然后整条消失）。所以
「点击 X 信源聚合看 For You + Following」这个场景，去重是自动生效的。

**要改的是破平规则。** 现状「同类按 `first_seen_at` 先到先得」在三 feed 下会出问题：若既订阅了
`@scavin` 又开了 Following，@scavin 的推在两个 feed 都有行，谁赢取决于哪个 feed 先采到——
**这条推的未读数会随机漂到 following 或 @scavin 名下**。改成显式三级：

```sql
ROW_NUMBER() OVER (
  PARTITION BY f.tweet_id
  ORDER BY CASE f.channel_id
             WHEN 'foryou'    THEN 2
             WHEN 'following' THEN 1
             ELSE 0 END ASC,
           f.first_seen_at ASC
)
```

胜出行决定三件事，所以顺序不是美学问题：

| 决定什么 | 代码位置 |
|---|---|
| 排序时间戳（foryou → `first_seen_at`，其它 → `created_at`） | `SORT_AT_SQL` |
| 聚合准入（`channel_id <> 'foryou' OR verdict = 'positive'`） | `_scope_where` |
| 卡片判定徽章、未读归属 | `_COLS` / `_unread_counts` |

**`SORT_AT_SQL` 不用改**——Following 走 `ELSE` 分支用 `created_at`，正是我们要的（配合 §6 的 24h 截断）。

### 5.1 必须知道的语义后果

Following 全量进聚合 + 在去重里压过 For You ⇒ **verdict 对「你关注的作者」失效**。实测 For You 里
25% 的推文作者在关注名单里（§2.5），这些推以后会通过 Following 进聚合，不再过 `verdict = 'positive'` 那道闸。

**这是对的**：Following 的含义就是「我关注的人说的话我都要看」，判定是用来筛算法推给我的陌生人的。

两个副作用，都是好的：

- 聚合总量**不是**简单相加（TG 50 + Following ~100 + For You 13%）——For You 那部分有相当比例被
  Following 吸收，去重后总量更小
- 这些推在聚合里以 Following 身份出现，**不带判定徽章**。而 `prospective.py` 的已知局限之一正是
  「徽章可能影响一条推是否被阅读和打标」——无徽章呈现下产生的标签，是前瞻验证目前拿不到的无偏样本

## 6. 24h 截断规则

**规则**：Following feed 的条目，`created_at` 早于 `CONDENSER_X_FOLLOWING_MAX_AGE_HOURS`（默认 24）
就**不建 feed 行**。

### 6.1 实测阈值影响（100 条采样）

| 阈值 | 丢弃 | 其中广告 | 其中正常内容 |
|---|---|---|---|
| 12h | 11 | 7 | 4 |
| **24h** | **11** | **7** | **4** |
| 48h | 8 | 6 | 2 |
| 7d | 7 | 5 | 2 |

12h 和 24h 丢的完全一样——feed 内容在 12h 内密集、之后断档，**24h 这条线画在空隙里**。

被丢的 4 条「正常内容」里 2 条是 @zdyxry 的线程祖先（本来就是要治的病），真误杀只有 2 条：
`@ekzhang1 age=26.5h`、`@vicch age=27.8h`，都刚过线。而这是**冷启动单次采样**的数字——实际运行
每 15 分钟采一次，一条推只要在发布后 24h 内任意一轮出现在 feed 里就已入库。真被误杀的只有
「发布超 24h 后才首次出现在 feed 里」的推，罕见。唯一会吃到这 2% 的场景是首次部署或长时间停机后的第一轮。

### 6.2 「不建 feed 行」≠「什么都不存」

现有代码里已有一条完全相同的路径：**被引用的推（`quotedTweet`）就是只写 `x_tweets` 本体、
不写 `x_feed_items`**（`ingest_tweets` 里的 `_embedded_quotes` → `db.insert_x_tweet_if_absent`）。

线程祖先直接复用这条路径：本体存下（几百字节），feed 行不建。效果和「丢弃」完全一样——不进时间线、
不计未读、不占位置——但今天那条新推的 `reply_to_id` 链是完整的，将来真要渲染线程时数据现成。
**零新机制、零 schema 改动。**

广告是纯噪音，本体也不必存，**整条丢**。

### 6.3 两条规则的作用顺序

```
parse → ① 作者不在关注名单？→ 整条丢弃（不存本体、不建 feed 行）
       → ② created_at 早于 24h？→ 只存本体（走 insert_x_tweet_if_absent），不建 feed 行
       → ③ 正常 → upsert 本体 + 建 feed 行
```

两条规则**只作用于 feed 层条目（`parsed`）**，不作用于 `_embedded_quotes`——被引用的推作者通常不在
关注名单里，但它走的本来就是「存本体不建 feed 行」的路径。

## 7. 关注名单

### 7.1 新表（SCHEMA_VERSION 11，纯新增，`create_tables` 即可，无迁移）

```python
class XFollowing(BaseModel):
    handle = CharField(primary_key=True)      # 小写存储
    user_id = CharField(null=True)            # 数字 id，改名后仍可追踪
    name = CharField(null=True)               # 显示名
    synced_at = DateTimeField()
```

为什么是表而不是 `app_meta` 里一个 JSON blob：(a) 每次 ingest 都要查，732 条的 JSON 反复解析不划算；
(b) 要记 `synced_at` 判断陈旧；(c) 它是 **channel A（作者先验）一直缺的输入**——「作者是否被我关注」
是零成本的强特征，对 For You 判定直接可用（见 §11）。

### 7.2 端点

```
POST /api/sources/x/following   {users: [{username, id, name}, ...]}
```

**全量替换语义**（事务内 delete + insert）——取关了的人要能从名单里消失，增量合并做不到这点。

### 7.3 probe 怎么知道该同步

probe 保持无状态，**决定权在服务端**：`GET /api/sources/x/probe-config` 的响应增加一个标志

```json
{"feeds": [...], "sync_following": true}
```

服务端根据 `max(synced_at)` 是否超过 24h 决定。probe 看到 `true` 就跑
`bird following --all --json` 并 POST 上去。

⚠️ **bird 的形状漂移坑**：`bird following` 不加 `--all` 时每页封顶 50 条（`-n 200` 也只给 50）；
加了 `--all` 之后**输出从裸数组变成 `{users: [...], nextCursor: ...}`**。probe 侧必须兼容两种形状。
实测 `--all --max-pages 40` 拿到 732 个账号、`nextCursor` 为 null（约 15 个请求）。

### 7.4 名单为空时的失败模式（必须有保护）

如果名单还没同步（空表），§6.3 的规则 ① 会把**所有**条目当广告丢掉——一条都不入库，而且悄无声息。

**保护：名单为空 ⇒ 完全不做作者过滤。** 这条要有独立的行为测试。

## 8. probe 增量推送

### 8.1 缓存结构

`~/.cache/condenser-probe/seen/<channel_id>.json`，内容 `{tweet_id: first_seen_iso}`，
**按 24h 裁剪**。几百个整数、几十 KB，天然有界。

为什么不用别的方案：

- **只记 `max_id`**（snowflake 单调递增，只推更大的）看着最省，但实测 feed 顺序**不是严格时间序**，会漏
- **全量 id 集合不裁剪** → 无界增长

对所有 feed 统一启用：For You 每轮全新（命中率 0，无害），单账号 feed 重复率高（有收益）。

### 8.2 代价（已被决策 2 接受）

`ingest_tweets` 现在的语义是 **tweet 行 refresh（metrics 更新）、feed 行 insert-only**。只推增量意味着
**一条推的互动数永远停在首见值**。15 分钟采样下，一条推刚发出就被采到，metrics 基本等于 0。
判定不受影响（embedding 用正文），UI 受影响 → §11 的详情页刷新接口。

这也打破了 probe 的 "stateless and configless" 设计（README 明确写了「crashed or slept 的 probe
没有任何东西要恢复」）。要接受并写进 README：

- 缓存丢失 = 全量重推（服务端幂等，无害）
- 提供 `condenser-probe run --no-cache` 强制全推
- 服务端数据被清空/回滚时，缓存还在会导致漏推 → 用 `--no-cache` 跑一轮

### 8.3 频率与 `-n`

Following 约 100–200 条/天，15 分钟一轮平均新增 1–2 条，早高峰实测密度约每 15 分钟 7 条。
`CONDENSER_X_FOLLOWING_COUNT` 默认 **50**（约 7 倍余量）。配合缓存，绝大多数轮次推 0–3 条。

launchd 示例（`probe/com.condenser.probe.plist.example`）的 interval 改成 900。

## 9. 实施步骤（BDD，每步独立可交付、可回滚）

每步先写行为测试再实现。测试放 `tests/test_x_following.py`（服务端）和 `probe/tests/test_probe.py`（probe 侧）。

### 步骤 1：关注名单（必须先于步骤 2，因为过滤依赖它）

- schema v11 + `XFollowing` 模型 + `db.replace_x_following` / `db.x_following_handles` / `db.x_following_synced_at`
- `POST /api/sources/x/following`（`types.py` 加 `XFollowingBody`）
- `probe_config` 响应加 `sync_following` 标志
- probe：`bird.fetch_following_users()`（兼容两种输出形状）+ `client.push_following()` + runner 接线

**行为测试**：全量替换语义（取关的人消失）／ 两种 bird 输出形状都能解析 ／ `sync_following`
在 24h 内为 false、超过为 true ／ 名单为空时 `x_following_handles()` 返回空集

### 步骤 2：Following feed 接入

- `FOLLOWING_FEED` 常量 + `normalize_channel_id` / `default_config` / `feed_count` /
  `probe_config` / `describe_subscription` 的二分改三分
- `_learn_user_identity` 加显式早退（现在靠「没有作者叫 @following」侥幸安全）
- `ingest_tweets` 的两条过滤规则（§6.3），只作用于 `parsed`
- `CONDENSER_X_FOLLOWING_COUNT` / `CONDENSER_X_FOLLOWING_MAX_AGE_HOURS` 配置项
- probe：`bird.build_command` 新 kind → `['bird', 'home', '-n', n, '--following', '--json']`

**行为测试**：订阅 CRUD ／ probe-config 产出正确命令 ／ 广告条目被整条丢弃 ／
**名单为空时不过滤**（§7.4）／ 25h 前的条目只存本体不建 feed 行 ／ 被引用的推不受两条规则影响 ／
`_learn_user_identity` 对 following 早退

### 步骤 3：时间线

- `_DEDUP_RANK` 三级优先级（§5）
- `aggregate_mode()` 泛化成 `aggregate_mode(feed)`；`scope()` 改成「聚合视图排除 aggregate 为 none 的 feed」，
  取代 `enabled_x_feeds` 里硬编码的 `c != FORYOU_FEED`
- `x._aggregate_mode` 让 following 也能读自己的 config（For You 默认 `none`，Following 默认 `all`，
  单账号 feed 恒 `all`）

**行为测试**：同一条推在三个 feed → 单账号订阅胜出 ／ Following 进聚合、For You 仍按 verdict 准入 ／
Following `aggregate=none` 时不进聚合但自己的视图照常 ／ 未读归属不漂移 ／
`bulk_read_scope` 与页面展示一致（「全部已读」不能烧掉 For You 的标注 backlog）

### 步骤 4：probe 增量缓存

- `probe/condenser_probe/cache.py`（load / prune / filter / update）
- runner 接线 + `--no-cache` 开关
- README 更新 stateless 的措辞

**行为测试**：已见推文被跳过 ／ 24h 外的缓存条目被裁剪 ／ 缓存丢失时全量推送 ／
`--no-cache` 绕过缓存 ／ 缓存写入失败不影响本轮推送

### 步骤 5：前端

- `XSection.tsx` 加 Following 订阅入口
- `XAggregateMenu` 现在只对 For You 显示 → 对 Following 也显示，但选项集是 `none`/`all`（没有 `positive`，
  Following 不判定）
- 侧边栏 `SidebarXFeedLink` 自动从 `/api/sources` 拿到，无需改动

**iOS 无需改动**——envelope 通用，X 卡片已支持，subs tab 的 X 分组会自动多一行。

### 步骤 6：验收

真实 bird → dev backend 端到端跑一轮，截图归档到 `tmp/2026-07-30-x-following/`：

1. 订阅 Following → probe 跑一轮 → 时间线出现关注账号的推
2. 广告不出现（对照 `bird home --following` 的原始输出确认哪几条该被切）
3. 线程祖先不出现在历史日期（翻日历确认）
4. 同一条推不在聚合里出现两次（找一条同时在 For You 和 Following 的推验证）
5. `aggregate=none` 切换生效
6. probe 第二轮推送数接近 0（缓存生效）

## 10. 验收标准

- 全部行为测试绿（服务端 + probe + 前端）
- `tmp/2026-07-30-x-following/` 有覆盖 §9 步骤 6 六个场景的截图
- 生产部署后观察一天：`/api/x/status` 的 following push 统计、每日入库量落在 100–200 区间
- 聚合时间线没有重复条目

## 11. 遗留 / future work

| 项 | 说明 |
|---|---|
| **互动数刷新接口** | 详情页打开时按需请求并刷新 metrics（决策 2 的配套）。这是「打开时才需要准确」的数据，塞进采集链路只会让每轮 ingest 变成全量写 |
| **关注名单喂给 channel A** | `authors.py` 的作者先验目前只认「你打过标的账号」，对没标过的账号完全盲。「是否被关注」是零成本的先验，能直接补上这个盲区——尤其对 For You 里的陌生账号 |
| **线程渲染** | 祖先本体已经存下来了（§6.2），`reply_to_id` 链完整，将来要做不用补数据 |
| **`list-timeline`** | 唯一支持 `--cursor` / `--all` 真分页的时间线源，没有算法注入和广告。用户当前没在用 X 列表，暂不做 |
| **24h 阈值复核** | §6.1 的数字来自单次冷启动采样。上线后用真实数据复核一次被截断的条目里有多少是正常内容 |

## 12. 开发约定（本项目的，别踩）

- **BDD**：新功能先写行为测试再实现；bug 修复先写复现测试
- **extension-column 契约**：telememo 写路径只碰原生列，别用整行 `INSERT OR REPLACE`
- peewee 连接是 thread-local，测试间要关主线程连接（见 `tests/conftest.py`）
- PostToolUse 格式化钩子会把文件改写成单引号风格，别和它打架
- **`git push` 到 master 就是生产部署**（`.github/workflows/deploy.yml` → ghcr.io → hookploy）。
  部署前确认，别把 push 当成同步远端
- compose 环境变量在 ansible role 模板里，不在 `.env`；模板改了需要跑 ansible，hookploy 只重钉镜像

## 13. 实施记录（2026-07-30）

本节只记「本文没写、或写了但落地时改了」的部分。没提到的，就是按计划做的。

### 13.1 与计划的偏差

| 处 | 计划 | 实际 | 为什么 |
|---|---|---|---|
| 名单同步时间戳 | `XFollowing.synced_at` 的 `max()` | 权威值放 `app_meta.x_following_synced_at`，列保留 | 一次「同步出 0 行」也是同步。读行的话空名单会显示为永远陈旧，每轮重爬 |
| 空名单推送 | 未提 | 名单非空时拒收空推送（422） | bird 偶发返回 `[]` 会静默关掉广告过滤一整个同步周期。§7.4 的保护是给「从没同步过」的，不是给「同步坏了」的 |
| `sync_following` 触发条件 | 只看 `synced_at` 陈旧 | 再加「至少有一个启用的 feed」 | 没订阅时 probe 本来就空转，为它爬 15 页纯浪费 |
| `feed_kind` 常量位置 | `condenser/x.py` | 挪到 `condenser/items.py`（`FORYOU_FEED` 本来就在那儿，x.py 是第二份拷贝），x.py 改成 import | 加第三个 feed key 时正好把重复消掉；`items.py` 是所有人都能 import 的底层 |
| `useBulkRead.coversSub` | 未提 | 不再硬编码「跳过 For You」，改成比较 `aggregate_unread === unread` | 服务端规则已经是逐 feed 的开关，前端乐观更新得跟上；两个数相等就说明聚合展示了这个 feed 的全部，可以就地清零，否则交给 refetch |
| 抓取计数 | 只说服务端过滤 | `IngestResult` 加 `filtered_ads` / `filtered_old`，一路透到订阅行 | 「广告没出现」和「整个 feed 没进来」在界面上长得一样，得能分辨 |
| launchd 间隔 | 改成 900 | 改成 `StartCalendarInterval` 四个整刻 | 原文件注释已经解释过为什么不用 `StartInterval`（跨睡眠会卡死），15 分钟同理 |

### 13.2 实测确认的（都在 `tmp/2026-07-30-x-following/`）

- **广告过滤**：实时样本 4/4、录制样本 7/7 全部整条丢弃，0 误杀。名单 732 个账号
- **24h 规则**：录制样本 4 条超期条目全部「存本体、不建 feed 行」，含 @zdyxry 的 2249h / 7817h 两条祖先；
  Following 的日历只有 7/28、7/29 两天 —— 祖先一天历史都没造出来
- **去重**：一条推同时在 following / foryou / jaywcjlove，聚合和 X 视图各只显示 1 次，归属账号订阅。
  聚合 128 + 归到账号名下的 7 = 自己视图的 135，对得上
- **缓存**：第二轮 `following` 50 条跳过 41，`novoreorx` 10 条全跳过（整轮没发请求），
  `foryou` 跳过 0 —— 火喉流每次重采样，正好是对照组
- **迁移**：dev DB 从 v10 起来，`x_following` 建好，既有 X 数据一条没动

### 13.3 计划里没预料到的一件事

**实时窗口里一条线程祖先都没有。** §2.4 那条 @zdyxry 接龙是 7/29 抓到的，7/30 再抓 50 条，
超期条目为 0。所以「祖先规则」这条最不可见的规则，光靠实时验收根本触发不到 —— 用 §2.4 的录制样本
补推了一轮才验上（`push_recorded.sh`）。这也顺带印证了 §6.1 的数字：录制样本推进去，
服务端报的正是 `filtered_ads: 7, filtered_old: 4`。

推论：**这条规则的日常触发率很低**，§11 说的「上线后复核 24h 阈值」得看几天的累计计数
（订阅行上的「N 条超期」），不能看一轮。

### 13.4 仍然待办

- **部署**（`git push` 到 master 即部署，见 §12）
- §11 的四项 future work 一项没动：互动数刷新接口、关注名单喂给 channel A、线程渲染、`list-timeline`
- 关注名单现在只有 Following 的广告过滤在用。`authors.py` 拿它当先验是**最便宜的一个补丁**，
  数据已经在库里了
