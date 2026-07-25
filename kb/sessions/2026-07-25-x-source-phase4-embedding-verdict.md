---
created: 2026-07-25
tags:
  - session
  - x-twitter
  - embedding
  - sqlite-vec
  - feedback-ranking
  - schema-migration
---

# X 信息源 Phase 4：Embedding 判定上线（管线完成，分类质量待回测）

## 概要

按 `kb/plans/2026-07-24-x-source-local-probe.md` 推进 Phase 4：把 Phase 3 攒下的 up/down/收藏
标注变成对**新 For You 推文**的判定。

动手前先和用户复议了计划里的向量存储选型。用户质疑「暴力 kNN 是重复造轮子、可维护性差」，并提出
换 Chroma。实测后维持原计划的 sqlite-vec，但理由比原计划更硬：`uv pip compile` 显示 chromadb
解析出 **79 个传递依赖**（含 `kubernetes` / `onnxruntime` / `grpcio` / 整套 opentelemetry /
`uvicorn`+`uvloop`），sqlite-vec 只有 1 个；更关键的是 Chroma 会让标签和向量变成**两个存储引擎、
无共同事务**，而 condenser 的整个运维故事就是「一个 SQLite 文件」。走 peewee 的 smoke test
确认了四条性质：扩展能加载、线程本地新连接会自动重载、snowflake int64 作 rowid 往返无损、
**vec0 与普通表同事务回滚**。最后一条是 Chroma 和暴力方案都给不了的，也是选型的真正依据。
对「造轮子」的回应是把库关进 `vectors.py` 的四个函数后面。

实现按 BDD：先写 32 个行为场景（用可注入的假 embedder，向量手工摆在正交主题轴上，所以每个距离
都是选定的），再实现。测试过程中逼出两个真实设计缺陷（见「注意事项」）。

最终 255 backend + 64 frontend + 11 probe 绿；用 `.env` 里真实的 DashScope key 对本地 dev
后端跑了完整端到端（真实嵌入 → vec0 kNN → verdict → UI 徽标），截图与可复跑脚本归档在
`tmp/2026-07-25-x-phase4-verdict/`。

**但分类质量这次证明不了**：Phase 3 当天才上线，真实标注量 ≈ 0，生产闸门（20/20）会让所有
verdict 保持 null。为了让徽标显示出来，两张截图用的是仅供演示的阈值——默认阈值下 4 条判定
全是 neutral，包括一条 score −1.00 因缺第二个 down 佐证而未判负（不对称闸门生效）。

## 修改的文件

### 新增（后端）

| 文件 | 说明 |
|---|---|
| `condenser/vectors.py` | 唯一知道 sqlite-vec 存在的模块：`setup(dims)`（把扩展注册到 peewee **database** 上，使每个线程本地连接自动重放，再建 vec0 表）、`pack`/`unpack`（float32 BLOB，刻意不依赖扩展，使得扩展加载不了的宿主仍能存向量）、`upsert`/`delete`/`clear`/`labeled_ids`/`knn`。扩展不可用时全部降级为 no-op |
| `condenser/embedding.py` | OpenAI 兼容嵌入（默认 DashScope `text-embedding-v4@256`）：批 ≤10、两次退避重试、L2 normalize、按回传 `index` 重排。无 key → `available()` false → 整套判定 inert。`model_tag` = `name@dims`，是向量的可比性身份 |
| `condenser/verdict.py` | 判定管线 + `VerdictManager`（挂 `app.state.verdict`，由 ingest kick）。`run_once` = 撤销对账 → 冷启动闸门 → 补索引 → 判定 → prune。含 `judge_text`（剥 RT 前缀 / 拼引用推 / 长文取 title+preview）、`score_neighbours`（距离加权投票 + 三段不对称阈值）、`rebuild_labeled_index()` |
| `scripts/x_verdict_backtest.py` | 留一法回测（每折重建索引，避免样本给自己投票）+ `--sweep` 网格 + `--embed-missing`。读数顺序：coverage → negative precision → positive precision |
| `tests/test_x_verdict.py` | 32 个行为场景 |

### 新增（前端）

| 文件 | 说明 |
|---|---|
| `frontend/src/components/timeline/XVerdictBadge.tsx` | 底栏左侧徽标，与 `XFeedbackButtons` 对望。`neutral`/`null` **不渲染**；点击打开详情面板；hover title 一句话概括依据 |
| `frontend/src/components/timeline/XVerdictDetail.tsx` | 详情面板的「判定」行：verdict + score + 投票的近邻（作者 handle + 距离，链到原推）+ `model@dims / algo` |
| `frontend/src/components/timeline/XVerdictBadge.test.tsx` | 6 个用例 |

### 修改

| 文件 | 说明 |
|---|---|
| `condenser/db.py` | `SCHEMA_VERSION` 7→8；`XEmbedding` 模型；`init_db(db_path, vector_dims)` 末尾调 `vectors.setup()`；新增 `x_labeled_samples`（训练集实时读表 + 矛盾样本剔除）/ `x_embedding_ids` / `x_embedding_vectors` / `x_author_handles` / `upsert_x_embedding` / `prune_x_embeddings` / `x_tweet_judge_rows` / `x_pending_verdict_rows` / `set_x_verdict` / `x_verdict_counts` |
| `condenser/config.py` | `CONDENSER_EMBEDDING_*` 四项 + retention + `CONDENSER_VERDICT_*` 十一项 |
| `condenser/app.py` | lifespan 挂 `VerdictManager`；`init_db` 传维度 |
| `condenser/routers/x.py` | ingest 后 `_kick_verdict`（kick 失败不影响 ingest 返回） |
| `condenser/x.py` | `status()` 增加 `verdict` 块（延迟 import 避开循环依赖） |
| `frontend/src/lib/types.ts` | `XVerdict` / `XVerdictNeighbor` / `XVerdictMeta` / `XVerdictStatus`，`XStatus.verdict` |
| `frontend/src/components/timeline/XCard.tsx` | 底栏加 `XVerdictBadge` |
| `frontend/src/components/timeline/ItemDetailInfo.tsx` | 「判定」行改用 `XVerdictDetail` |
| `frontend/src/components/subscriptions/XSection.tsx` | 状态区加 `XVerdictLine`：区分「未配置 / 无扩展 / 攒标注中还差几个 / 已在判定」 |
| `tests/conftest.py` | `env` fixture 默认清空 `CONDENSER_EMBEDDING_API_KEY` —— `Settings` 会读真实 `.env`，不清空的话任何测试都可能误打真实 API 花钱 |
| `tests/test_hn.py` / `tests/test_x_source.py` | 版本号断言 7→8；`/api/x/status` 的整字典比较改为子集比较 |
| `pyproject.toml` / `uv.lock` | `sqlite-vec>=0.1.9`（lock 内含 macOS + manylinux x86_64/aarch64 wheel） |
| `.env.example` / `README.md` / `AGENTS.md` / `frontend/AGENTS.md` | 配置说明、sqlite-vec 的宿主要求、v8 schema、模块表、组件清单 |
| `kb/plans/2026-07-24-x-source-local-probe.md` | Phase 4 标记完成 + 实现纪要 + 选型复议记录 + 实测数据 |

## 注意事项

### 被测试逼出来的两个设计缺陷

1. **撤销标注不能受冷启动闸门限制**。最初的实现是「闸门关着就直接返回」，导致撤销一个标注后
   （负样本从 2 掉到 1、闸门关上）被撤销的向量滞留在索引里。删索引不花钱，所以「你收回的标注
   不该还在索引里」应当无条件成立。现在 `_drop_retracted` 在闸门检查**之前**执行。
2. **已标注的推文不能再被判定**。它自己在索引里，会以距离 0 命中自己，判定结果就是标签本身——
   循环论证，而且发生在唯一不需要判定的条目上。`x_pending_verdict_rows` 现在用两个
   `NOT EXISTS` 排掉有 feedback 或已收藏的推文。

### 两处刻意偏离计划

- **冷启动闸门提前到 embedding 之前**（计划流程是 ②嵌入 → ③闸门）。闸门关着时嵌入纯属浪费，
  一个刚装好的实例不该为了输出一堆 neutral 而花钱。同理，闸门关着时不给 For You 推文算 embedding。
- **`verdict_meta` 的近邻截断到 5 条并带上作者 handle**。截断是因为这行每天写 ~1000 次，不限量
  会让解释比被解释的推文还占地方；带 handle 是因为一串裸 tweet id 无法「解释」任何事——而可解释性
  正是「只打标不隐藏」的全部依据。

### 可复用的 pattern

- **对账（reconcile）而非写穿（write-through）**：标注端点保持同步（嵌入要联网），索引由后台轮次
  对账到标签表。重启 / API 挂掉 / 换模型都能在下一轮自愈，且端点上没有任何同步代码。
- **降级而非崩溃**：扩展加载不了 / 没有 API key / 标注不够，三种情况都让功能安静地不存在，
  应用其余部分照常。`/api/x/status` 负责把「哪一种」告诉用户——「没有徽标」有三种完全不同的原因，
  只有一种是用户能动手解决的。
- **测试隔离要防真实凭据泄进来**：`Settings` 的 `env_file='.env'` 意味着测试会读到真实 key。
  在 conftest 里默认清空是必须的，否则一次 `pytest` 就可能产生真实 API 调用。

### 实测数据（值得记住）

`text-embedding-v4@256` 真实调用：同主题跨语言（中/英 Rust borrow checker）cosine 距离 **0.18**，
跨主题（Rust vs crypto 推广）**0.80**。`CONDENSER_VERDICT_MAX_DISTANCE=0.6` 正好落在两者之间，
占位值意外地合理。跨语种召回也说明中英混杂的 For You 流不需要分语言建模。

真机 4 标注下所有近邻距离都在 0.43–0.60，即「什么都不太像什么」——这正是冷启动闸门存在的理由，
也说明 20/20 的默认下限不算保守。

## 遗留问题

- **分类质量完全未验证**。回测脚本已就位但现在跑不出有意义的数字（4 个标注 → coverage 0–25%）。
  所有阈值常量（P、N、k、D_MAX、M、±阈值）仍是占位值。真实标注积累后跑
  `uv run python scripts/x_verdict_backtest.py --sweep` 定案。
- **一个部署假设没验证**：`python:3.12-slim` 是否启用了 SQLite 扩展加载。官方镜像应当启用，
  manylinux wheel 也在 lock 里，且失败模式可见且非致命（只丢判定）。部署后看
  `/api/x/status` 的 `verdict.index_available` 即可确认。本地按项目规则未跑 docker。
- **dev 数据库被写入了演示标注**：`tmp/condenser.db` 含 4 个本次为验证而编的标注（例如把一条讲
  终端外观的推标成 👎），非用户真实偏好。Phase 4 前的备份在 `tmp/condenser.db.bak-phase4`。
- **iOS 仍空窗**：Phase 3 的反馈按钮 + Phase 4 的徽标都并到 Phase 5 一起做；在那之前
  关注人 feed 的 X 条目在 iOS 上仍渲染为空白行。
- **judge_text 的 RT 剥离用的是 `partition(':')`**：文本里首个冒号之前若不是 RT 前缀会误伤，
  但只在 `rt_of_handle` 非空时才走这条路径，风险受限。
- 计划中更早的遗留项仍在：旧 raw 的重 parse 回填工具、订阅「删除并清档」（`?purge=1`）、
  backfill 批次间隔 sleep。

## 相关文档

- [X 信息源：local probe + 反馈判定](../plans/2026-07-24-x-source-local-probe.md) — 本次 session 按此计划实现 Phase 4，并更新了进展表、决策记录与实现纪要
- [X 判定算法讨论：从单通道 dense kNN 到多通道弱信号集成](../notes/2026-07-24-x-verdict-multi-channel-discussion.md) — 参考；本次实现的是其中定位为 v1 baseline / 回测对照组的 dense kNN
- [X 信息源 Phase 1 session](../sessions/2026-07-24-x-source-phase1-probe-ingest.md) — 前序 session，v7 schema 与 probe/ingest 的来源
