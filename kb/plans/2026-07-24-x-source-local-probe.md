---
created: 2026-07-24
tags:
  - plan
  - multi-source
  - x-twitter
  - local-probe
  - feedback-ranking
---

# X 信息源：local probe + 反馈判定

通过运行在用户本地电脑上的 **local probe**（调用 [bird cli](https://github.com/) 读取已登录账号的数据）接入 X (Twitter) 信息源。两种订阅形态：**For You** 算法流（对标 HN front page）和**关注的人**（对标 TG 频道）。For You 叠加一层用户反馈驱动的判定：用户对推文 thumb up/down，服务端据此对新推文计算 verdict（positive / neutral / negative）。

这是项目第一个**推模式**的源（TG/HN 都是服务端主动拉；X 的数据只存在于本地 bird 的 cookie 会话里，由 probe 推给服务端），也是第一个同时具备「feed 型 + 账号型」两种订阅的源。

## 决策记录

与用户讨论后确定（2026-07-24）：

| 决策点 | 结论 | 理由 |
|---|---|---|
| For You 的 timeline 排序时间 | **`first_seen_at`**（probe 首次推送入库时刻），非推文 `created_at` | 与 HN front page 决策完全一致：算法会捞出几天前的旧推，按 `created_at` 排会插进 timeline 历史中间，破坏 append-only 与 cursor 语义。卡片上仍展示推文原始发布时间。关注人 feed 则用 `created_at`（本来就是时序流，同 TG） |
| negative 判定的呈现 | **先只打标不隐藏**：verdict 以徽标形式展示，观察准确率；人工确认靠谱后再启用折叠/过滤（后续迭代） | 算法会误杀，不可见的误杀永远发现不了；先攒信任再放权 |
| 判定算法选型 | **Embedding 分类**：标注推文取 embedding，新推文按相似度（kNN / 逻辑回归）判定 | 效果与成本的平衡点；语义泛化优于作者/关键词统计，运行成本远低于每轮 LLM judge |
| Embedding 模型 | **DashScope `text-embedding-v4`**，走 OpenAI 兼容接口（base URL 由 env 注入，无供应商专用代码） | 用户指定（2026-07-24）；参考 `../tenderbuddy` 的既有接法，见 Phase 4 示例代码 |
| up/down 反馈范围 | **全部 X 推文**（For You + 关注人 feed 都可标注），但 verdict 计算与未来的隐藏动作**只作用于 For You** | 扩大标注数据量（正好补 embedding 方案的训练数据短板）；关注人的噪音用退订解决，不需要算法介入 |
| 收藏作为反馈信号 | **收藏（save）是比 thumb up 更高级别的肯定**：`saved_items` 中的 X 推文自动进入训练集作强正样本，权重高于 up | 用户补充（2026-07-24）。零额外操作成本的高置信标注；不新建表，训练时直接读 `saved_items` |
| probe 配置来源 | **服务端下发**：probe 每轮先拉 probe-config，按当前 enabled 的 X 订阅决定抓什么 | 订阅管理保持在 web，probe 零本地配置；与「订阅驱动采样」的既有语义一致（HN 先例） |
| probe 状态 | **无状态**：每轮全量推最近 N 条，服务端按 tweet id 幂等去重 | probe 崩溃/休眠/重装零恢复成本 |
| probe 鉴权 | **复用 device token**（`devices` 表 + web `/authorize` 流程） | probe 本质是一种 device，服务端零新增鉴权代码 |

技术要点（实现侧）：

- item key：`x:{tweet_id}`（snowflake int64，`ref1` 放得下，`ref2=0`）。`read_items` / `saved_items` / `hidden_items` / envelope / federated merge 全部零改动复用。
- 订阅：`(source='x', channel_id='foryou')` 为 For You；`(source='x', channel_id=<numeric_user_id>)` 为关注人（数字 id 存 `channel_id`，`@handle` 与显示名存 `name`/`config` —— handle 可改名，数字 id 稳定）。`BareField channel_id` 当初就是为混型留的。
- **raw JSON 必须留底**：bird 的输出跟着 X 内部 API 走，不是稳定 contract；解析层容错，raw 供格式漂移后重 parse 回填。

## 数据模型（Phase 1 = SCHEMA_VERSION 7；向量表在 Phase 4 = SCHEMA_VERSION 8）

同一条推文可能同时出现在 For You 和某个关注人的 feed 里，且 verdict 只挂在 For You 的出现上 —— 所以推文本体与「出现在哪个 feed」分开：

```
# SCHEMA_VERSION 7（Phase 1）
x_tweets       id (PK, tweet id), author_id, author_handle, author_name,
               text, created_at, media (JSON), metrics (JSON),
               quote_of (自引用 tweet id, 可空), rt_of_handle (TEXT, 可空, 见实测⑤),
               reply_to_id (可空), article (JSON, 可空), raw (JSON), fetched_at
x_feed_items   (channel_id TEXT, tweet_id INT) PK, first_seen_at,
               verdict (positive/neutral/negative, 可空; 仅 foryou 行计算),
               verdict_meta (JSON: score, 近邻样本, 算法版本)
item_feedback  (source, ref1, ref2) PK, verdict ('up'/'down'), created_at

# SCHEMA_VERSION 8（Phase 4 —— 维度等参数届时才冻结，不提前建表）
x_embeddings   tweet_id (PK), vector (BLOB float32, L2-normalized), model, created_at
x_vec_labeled  vec0 虚拟表（KNN 索引，仅训练集），见 Phase 4「向量存储」
```

- `item_feedback` 是**源通用**表（与 `hidden_items` 同款三元组形态），将来 HN 想做同样的事零迁移。
- 引用推展示为内嵌卡片，被引原推入 `x_tweets` 自引用行；转推展示为转发卡（复用 TG forward 的 UI 语言），但**只能靠文本启发式**（见实测⑤）。**thread 合并 v1 不做**。
- 索引：`x_feed_items(channel_id, first_seen_at)`、`x_tweets(author_id)`。

### bird 输出实测结论（2026-07-24，bird 0.8.0，样本 `tmp/2026-07-24-bird-samples/`）

实跑 `bird home -n 50 --json` / `bird user-tweets <handle> -n 10 --json`（Chrome cookie，`bird check`/`whoami` 验证凭据）得到的事实，数据模型据此定案：

1. **顶层是纯 JSON 数组**，条目扁平（bird 已消化过 GraphQL 原始结构）。这加重了 raw 留底的必要性——上游 X API **和** bird 自身的转换逻辑都是漂移源。
2. **`id` / `authorId` / `conversationId` 是字符串**（JS 大整数安全），入库转 int64。
3. **`createdAt` 是 legacy 格式** `Thu Jul 23 14:46:20 +0000 2026` → `strptime('%a %b %d %H:%M:%S %z %Y')`。
4. **metrics 只有 `replyCount` / `retweetCount` / `likeCount`**，无 views/bookmarks。
5. **转推没有结构化字段**：被压平为 `RT @orig: <text>` 文本前缀，author = 转推者，无 retweetedTweet 对象。→ schema 用 `rt_of_handle`（从前缀 parse 出原作者 handle，可空）替代原设想的 `rt_of` id 自引用；legacy RT 格式有截断风险（样本未观察到，未证实）。可考虑给 bird 提上游 issue。
6. **`quotedTweet` 是完整内嵌对象**（默认 depth=1，media 齐全）→ 自引用行设计可行，从内嵌 payload 直接建被引推的行。
7. **media**：`type` 见到 photo/video（animated_gif 待观察），photo 有 `url/width/height/previewUrl`，video 加 `videoUrl/durationMs`。**宽高齐全**——前端图片占位（对齐 TG 的 media_width/height 实践）无忧。
8. **`author` 只有 `username`/`name`，无头像 URL**。头像方案：unavatar.io 代理、或 v1 字母头像（对齐 ChannelAvatar 的 fallback）。
9. **X 长文（article）只有 `title` + `previewText`（~200 字符截断）**，`text` 字段即标题——判定文本需拼 `title + previewText`，全文拿不到。
10. **For You 混有回复**（`inReplyToStatusId`，2/50）和**疑似无标记的广告**（推广文案账号出现在 50 条中，无任何 promoted 标记——推测 bird 不过滤/不标注 ads）。广告识别恰好是判定算法（作者先验 + 文风通道）的用武之地。
11. **50 条里 46 个不同作者**——作者先验通道冷启动会慢（单作者样本极少），佐证多通道集成的必要性（见算法讨论笔记）。
12. bird 另有 **`following`**（关注列表自动同步可行，「后续方向」升级为已验证）、**`likes` / `bookmarks`**（自己的喜欢/书签列表——潜在的**免费隐式正样本**，强度介于 up 与 save 之间，留给算法 Phase 评估）。

## Phase 1 — probe + ingest + 存档（最先上线，开始攒数据）⏰

与 HN Phase 1 同理：**存档和标注数据越早开始攒越好**，本 phase 不含 breaking change，独立部署。

### 服务端

- 上述四张表 + 迁移（`item_feedback` / `x_embeddings` 建表即可，无数据迁移）。
- `POST /api/sources/x/subscriptions` `{channel_id: "foryou"}` 或 `{channel_id: <user_id>, name: "@someone"}`；PATCH / DELETE 同 HN 端点形态。订阅驱动：无 enabled X 订阅时 probe-config 返回空清单。
- `GET /api/sources/x/probe-config`（Bearer）→ `{feeds: [{channel_id, kind: "home"|"user", handle?, n}]}`。
- `POST /api/sources/x/ingest`（Bearer）→ `{channel_id, tweets: [<bird 原始 JSON>]}`。服务端 parse + 按 id upsert `x_tweets`（metrics 快照可覆盖更新），`x_feed_items` 不存在才插入（**`first_seen_at` 不重置**，同 HN 去重语义）；parse 失败的条目计数入 status、raw 照存。
- `GET /api/sources/x/status` → `{subscribed, last_push_at, last_push_counts, parse_errors, tweets_total}`。
- web 订阅页最小入口：X 区块（添加 foryou / 关注人订阅 + 状态展示）。

### probe（monorepo `probe/` 目录，独立 uv 包）

- 每轮：拉 probe-config → 逐 feed 跑 `bird home -n 50 --json` / `bird user-tweets @handle -n 10 --json` → POST ingest。单 feed 失败不影响其余；结果 log 到本地。
- launchd/cron 定时（建议 For You 30–60min、关注人 1h；频率写进 probe-config 由服务端统一控制亦可，v1 先本地定时）。
- 配置仅两项：服务端 URL + device token（env / 单文件）。

### 测试（BDD 先行，bird 输出用真实 JSON fixture）

- 无 enabled X 订阅 → probe-config 空清单；添加后出现对应 feed 条目。
- ingest 幂等：重复推送同批推文不产生重复行、不重置 `first_seen_at`。
- RT/quote 的原推入库为自引用行。
- 畸形 tweet JSON：raw 留底 + parse_errors 计数 + 不毁整批。
- 鉴权：cookie 不可用于 ingest（Bearer only 或两者皆可——与 device token 既有语义对齐）、无 token 401。

## Phase 2 — timeline 接入

多源框架现成，这一步比 HN 当时便宜得多：

- `sources/x.py` provider：`x_feed_items JOIN x_tweets`，For You 按 `first_seen_at DESC`、关注人按 `created_at DESC` 分页，anti-join `hidden_items`，挂进 k-way merge。
- `items.py`：`x_key` / parse / `x_envelope`（payload 含 author、text、media、metrics、rt/quote 嵌套、`first_seen_at`、feed 来源、verdict）。
- web `XCard`：作者头像/名/handle、文本（linkify）、媒体、RT/quote 嵌套卡、metrics 行；时间入口进 `ItemDetailPane`（"Open on X" 链接自拼 `x.com/{handle}/status/{id}`）。
- 侧边栏/订阅页/`GET /api/sources` 出现 X 分组（框架自动，验证即可）。

## Phase 3 — 反馈闭环（web + iOS）

- `POST /api/feedback {key, verdict: "up"|"down"}` / `DELETE /api/feedback/{key}`（撤销）。
- web：X 卡片上 thumb up/down（**所有 X 推文均可标注**，高亮已选态，可撤销）；iOS 同步。
- 反馈只是写 `item_feedback`，本 phase 不做任何判定。

## Phase 4 — Embedding 判定

- **训练信号三档**：save（强正，权重最高）> up（正）> down（负）。训练集 = `item_feedback`（source='x'）∪ `saved_items`（source='x'）联合，训练时实时读表——取消收藏即自动退出训练集，无需同步逻辑。同一推文 save + down 并存属矛盾样本，从训练集剔除（预期极罕见）。kNN 的权重体现为投票加权；逻辑回归为样本权重。
- 标注推文（up/down/save）入库时算 embedding 存 `x_embeddings`；embedding 后端做成可插拔接口，本地模型留为替代实现。Phase 4 上线时对存量已收藏/已标注推文做一次 embedding 回填。

### 向量存储：sqlite-vec（SCHEMA_VERSION → 8）

SQLite 原生无向量能力，选 [sqlite-vec](https://alexgarcia.xyz/sqlite-vec/python.html)（PyPI 包自带预编译 loadable extension）。设计为**两层存储、职责分离**：

**1. `x_embeddings` —— storage of record（普通 peewee 表，BLOB）**

所有算过的向量都存这里：float32 BLOB（`sqlite_vec.serialize_float32()`，写入前 L2 normalize），`model` 列记 `text-embedding-v4@256`。定位是**可重建缓存**（对齐 `is_filtered` 的精神）——文本都在 `x_tweets.text`，任何时候可重嵌；换模型/维度 = 按 `model` 列筛选重算，不做原地迁移。

**2. `x_vec_labeled` —— KNN 索引（vec0 虚拟表，只装训练集）**

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS x_vec_labeled USING vec0(
  embedding float[256] distance_metric=cosine
);
-- rowid = tweet_id（snowflake int64，vec0 rowid 放得下）
```

**为什么不把全量向量都进 vec0、用 metadata 列过滤出训练集**：判定查询永远只搜「已标注的推文」，训练集规模是百~千级，全量表是十万~百万级；小表 KNN 天然快，且「在/不在索引里」的 presence 同步远比「label 值」同步简单——label 的真值只存在于 `item_feedback` / `saved_items`，vec0 表不复制它，查询时 join 回去取。

**同步规则**（vec0 的 shadow table 在同一 SQLite 文件内、参与事务，与 label 写入同事务提交，不会漂移）：

- 标注产生（feedback POST / save）→ 确保 `x_embeddings` 有向量（关注人 feed 的推文此时才 lazy 嵌入）→ `INSERT INTO x_vec_labeled(rowid, embedding)`。
- 标注消失（feedback DELETE / unsave 且无其他标注）→ `DELETE FROM x_vec_labeled WHERE rowid = ?`。
- 兜底提供 `rebuild_labeled_index()`：truncate 后从 `x_embeddings` ∩ (`item_feedback` ∪ `saved_items`) 全量重灌——升级 sqlite-vec、换模型、怀疑漂移时用。

**判定查询**（ingest 时对每条 For You 新推文）：

```sql
SELECT rowid AS tweet_id, distance
FROM x_vec_labeled
WHERE embedding MATCH :query_vec AND k = 15
```

结果在 Python 里 join label（save=强正/up=正/down=负）做距离加权投票 → verdict + `verdict_meta`（分数、命中的近邻 tweet_id 列表、`model@dims` 版本）。`k = ?` 是 sqlite-vec 的推荐语法（`LIMIT` 形态要求 SQLite ≥ 3.41）；具体权重与 positive/negative 阈值留给回测定。

**扩展加载（关键工程点）**：peewee 连接是**线程本地**的（conftest 每 case 关连接的既有 gotcha 同源），扩展必须对**每个新连接**加载。telememo 的 `db = SqliteDatabase(None)` 不用改类——peewee `SqliteDatabase` 原生支持 `db.load_extension(path)`，注册后每次建连自动 `enable_load_extension` + load，condenser 在 `init_db` 里调用 `db.load_extension(sqlite_vec.loadable_path())` 即可（实现时验证 peewee 版本行为；兜底方案是包一层 `_add_conn_hooks`）。vec0 虚拟表不建 peewee model，`init_db` 里原生 SQL 建表——**必须在扩展加载之后**。运行环境：Docker/Linux 与 uv 管理的 CPython 都支持扩展加载；macOS **系统自带** Python 不支持（sqlite-vec 文档明示），本项目不受影响但写进 README 提醒。

**维度与容量**（嵌入范围 = For You 全部 + 被标注的关注人推文）：

| dims | 单条 | For You 一年（~500 条/天） |
|---|---|---|
| 1024 | 4 KB | ~750 MB |
| **256（默认）** | 1 KB | ~190 MB |

SQLite 文件是生产环境 bind-mount 的单文件，1024 维一年近 GB 不可接受。text-embedding-v4 支持 64~2048 可变维度（MRL 式训练，低维截断质量衰减平缓——推测，回测时用留一验证对比 256 vs 1024 再定案）。另一个杠杆是 **retention**：未标注推文的向量只在判定时刻用一次，保留 90 天供回测后 prune（可随时重嵌）；标注向量永久保留。两个杠杆叠加后存储进入稳态，不随时间线性膨胀。

### 判定算法流程

```
新 For You 推文（ingest 批次内逐条）
   │
   ▼
 ① 取判定文本
     普通推  → text
     纯转推  → 原推的 text（转推本体没有文字）
     引用推  → 本推 text + 被引推 text 拼接
   │
   ▼
 ② embedding（text-embedding-v4@256 → L2 normalize）→ qvec
   │
   ▼
 ③ 冷启动闸门
     训练集正样本 < P 或 负样本 < N ────────────────▶ neutral（不装懂）
   │ 通过
   ▼
 ④ KNN 检索
     SELECT rowid, distance FROM x_vec_labeled
     WHERE embedding MATCH qvec AND k = 15
   │
   ▼
 ⑤ 有效邻居过滤（OOD 闸门）
     只保留 distance ≤ D_MAX 的邻居；
     有效邻居 < M 个 ──「离所有标注都太远」──────────▶ neutral
   │ 通过
   ▼
 ⑥ join 标签并赋权（label 真值从 item_feedback / saved_items 取）
     label:  up   → +1
             save → +1，且样本权重 ×2（比 up 更高级别的肯定）
             down → −1
     相似度权: sim = 1 − distance（cosine 距离）
   │
   ▼
 ⑦ 加权打分
     score = Σ(simᵢ × wᵢ × labelᵢ) / Σ(simᵢ × wᵢ)     ∈ [−1, +1]
   │
   ▼
 ⑧ 三段阈值（刻意不对称）
     score ≥ +0.35                      ────▶ positive（推荐）
     score ≤ −0.55 且 down 邻居 ≥ 2 个   ────▶ negative（隐藏候选）
     其余                                ────▶ neutral
   │
   ▼
 ⑨ 落库
     x_feed_items.verdict + verdict_meta =
     {score, neighbors: [{tweet_id, distance, label}], model@dims, algo_ver}
```

设计意图：

- **默认答案是 neutral**。③（数据不足不装懂）和 ⑤（OOD：离所有标注都太远不硬判）两道闸保证只在有真实证据时才表态；⑤ 是最重要的一道——没有它，kNN 永远返回 k 个邻居，每条推文都会被强行打分。
- **⑧ 不对称是成本决定的**：误推荐 = 多看一眼，误隐藏 = 永远看不到。negative 阈值更严，且要求 ≥2 个不同的 down 邻居佐证——单条误标的 down 不能独自拉黑一片语义邻域。
- **save 的权重放在样本权重（×2）而非 label 值 +2**：score 保持在 [−1, +1]，阈值可解释、跨算法版本可比较。
- **verdict_meta 存命中邻居**是「先打标不隐藏」的配套：UI 可解释「因为它像你 down 过的这几条」，对误判的纠错点击回流成训练样本。
- 所有常量（P、N、k、D_MAX、M、±阈值）为占位值，Phase 1–3 攒下标注后**留一法回测定案**。
- verdict 只在 ingest 时算一次，标注变化不回溯已判定推文（For You 流式消费，回溯价值低；回测阶段可评估是否对最近 48h 重算）。
- **本节的 dense kNN 定位是 v1 baseline / 回测对照组**。算法演进方向（多通道弱信号集成：作者先验 + dense kNN + LLM 属性提取 + n-gram 贝叶斯，及 down-reason chips）见讨论笔记 `kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md`，通道取舍由留一法回测定。

### Embedding 接入：DashScope text-embedding-v4（OpenAI compatible）

选型确定（2026-07-24）：**DashScope `text-embedding-v4`**，走 OpenAI 兼容接口。参考实现 `../tenderbuddy/app/src/lib/openai.ts` + `utils/embedding.ts` —— 标准 OpenAI SDK + env 注入 base URL，不写任何 DashScope 专用代码，将来换供应商只改 env。

配置（复用 tenderbuddy 的 env 形态）：

```bash
CONDENSER_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
CONDENSER_EMBEDDING_API_KEY=sk-...
CONDENSER_EMBEDDING_MODEL=text-embedding-v4
CONDENSER_EMBEDDING_DIMENSIONS=256    # v4 支持 64~2048；容量考量见「向量存储」，回测后定案
```

最基本的调用（condenser 是 async httpx 栈，直接 POST 兼容端点，零新增依赖）：

```python
# condenser/embedding.py
import httpx

from condenser.config import settings


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. DashScope caps batch size at 10 — caller chunks."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f'{settings.embedding_base_url}/embeddings',
            headers={'Authorization': f'Bearer {settings.embedding_api_key}'},
            json={
                'model': settings.embedding_model,        # text-embedding-v4
                'input': texts,                           # len ≤ 10
                'dimensions': settings.embedding_dimensions,
            },
        )
        resp.raise_for_status()
        data = resp.json()['data']
        # order is not guaranteed by the contract — sort by index
        return [item['embedding'] for item in sorted(data, key=lambda x: x['index'])]
```

注意点（继承 tenderbuddy 的 Qwen 实践）：

- **批量上限 10 条/请求**（tenderbuddy `embedLargeTexts` 的 Qwen config：`maxTextsPerRequest=10`、每请求 ~8192 token 留 90% 余量）。推文短文本不会碰 token 上限，按 10 条一批切分即可；ingest 每轮 ~50 条 = ~5 个请求。
- 返回的向量先 L2 normalize，再经 `sqlite_vec.serialize_float32()` 落 `x_embeddings.vector`；`model` 列记 `text-embedding-v4@256`——换模型或维度时旧向量不可比，按 model 列筛选重算（存储细节见上节「向量存储」）。
- 失败重试简单指数退避（1s/2s），整批失败不阻塞 ingest（verdict 留空 = neutral，下轮补算）。
- ingest 收到 For You 新推文 → 算 embedding → 对标注集做 kNN（或标注量足够后逻辑回归）→ 写 `x_feed_items.verdict` + `verdict_meta`（分数、命中的近邻样本 id、算法版本——供徽标 tooltip 展示「为什么」）。
- 冷启动：标注量 < 阈值（如各 20 条）→ 全部 neutral，不装懂。
- UI：**verdict 徽标 only**（决策：先打标不隐藏）。negative 折叠/服务端过滤、positive 高亮/置顶，作为观察准确率之后的后续迭代，届时的纠错动作（对误判推文点 up/down）天然反哺标注集。
- 回测脚本：拿 Phase 1-3 攒下的标注做留一验证，上线前先看准确率数字。

## Phase 5 — iOS 完整适配

- Kit：`XTweet` payload model + fixture、envelope 分发、feedback API。
- App：`XCard` / detail sheet、up/down 按钮、源切换菜单与订阅页出现 X、verdict 徽标。

## 风险

- **账号风险是 MTProto 灰色地带的加强版**：X 对第三方抓取的封号执法比 Telegram 激进得多。缓解：低频率、单点单账号、自担风险的自托管功能定位。
- **数据有空洞**：probe 依赖本地电脑开机在线。For You 本是采样性质影响小；关注人 feed 长时间离线会漏，n 可调大兜底。
- **bird 输出格式漂移**：raw 留底 + 解析容错 + status 暴露 parse_errors，格式崩了能及时发现并重 parse 回填。
- embedding API 依赖：判定是异步增强，API 挂了推文照常入库展示（verdict 留空 = neutral），不阻塞 ingest。
- **sqlite-vec 是 pre-1.0**（0.1.x）：vec0 shadow table 的磁盘格式可能随版本变。缓解：uv.lock pin 版本；升级视为「重建事件」——跑 `rebuild_labeled_index()` 即可，因为向量真值在 `x_embeddings`、label 真值在 `item_feedback`/`saved_items`，vec0 表整体可抛弃重灌。

## 后续方向（本计划不含）

- negative 折叠（「已折叠 N 条」可展开）与服务端过滤；positive 的高亮/单独视图。
- thread 合并展示。
- `item_feedback` 泛化到 HN（表已就位）。
- 关注人列表从 bird 自动同步（`bird following` 已实测存在）而非手动逐个订阅。
- `bird likes` / `bird bookmarks` 作为隐式正样本通道（强度介于 up 与 save 之间），probe 顺带采集。
