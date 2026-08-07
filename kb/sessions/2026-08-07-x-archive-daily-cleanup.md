---
created: 2026-08-07
tags:
  - x-source
  - cleanup
  - retention
  - sqlite
  - vacuum
  - scheduling
  - bdd
---

# X 归档每日清理：断点在库里，不在计时器里

## 概要

X 是唯一增长成问题的信源。生产实测（2026-08-07 快照，21.4 MB）：`x_tweets` 6147 行占
**10.3 MB —— 全库的 48%**，1.68 KB/行；近 5 天日增约 700 条 feed 行（following ~600 /
foryou ~100）加约 60 条内嵌引用正文，**≈1.2 MB/天 ≈ 440 MB/年**。而 `read_items` 里 X 只有
447 行对 5596 个 feed 行 —— **92% 的推文从来没被打开过**。这个 session 加了每日一轮的清理，
删掉过期且从未被读过的 X 数据。

**调度用手写 asyncio 循环 + `app_meta` 断点，而不是引入调度库。** 服务端至今没有任何调度
依赖（APScheduler 只在独立包 `probe/` 里），三个 manager 都是手写 `asyncio.create_task`。但
日频任务和 HN 的 600 秒不是一回事：`git push` 到 master 就是部署，session 开始时线上容器
刚因为一条 docs commit 重启 5 分钟 —— **纯内存计时器的日级任务可能永远不触发**。所以循环
每小时醒一次，真正的「今天跑过没有」存在 `app_meta.cleanup_last_run_at`。状态一旦落库，换不换
调度库就没有区别了，这也是不引入 APScheduler 的理由。

删除规则：feed 行按 `first_seen_at` 过 15 天、且 `read_items` / `hidden_items` /
`item_feedback` / `saved_items` 四项标记全无 → 删；然后循环删除「无存活 feed 行 + 无存活引用者
+ 未标注」的正文，直到无行可删；再级联清掉 `x_embeddings` / `x_attributes`。顺带把
`verdict._prune` 整个搬了过来 —— 它原先在冷启动闸门**里面**，标注不够的实例上从来没执行过。

方法上，这次的判断几乎都是先测再定，推翻了三条看起来合理的设计：

- **引用链必须循环到收敛。** 两份架构方案都建议「单趟 + 逐日自愈」，其中一份还打算写测试把
  这个行为钉死。实测 3 天窗口下单趟少删 494 条正文（**17.5%**）—— 把测出来的缺陷固化成测试
  是反过来了。X 的引用必然指向更早的推文，图无环，`while` 天然终止（实测 3~5 趟）。
- **WAL 下读 `freelist_count` 不需要先 checkpoint。** 方案里有这么一步，实测不成立：删完
  立刻就是准确值（0% → 34.4%），换连接一样，checkpoint 前后一页不差。去掉。
- **`fetched_at` 是「最后一次见到」不是「首次入库」**（评审发现）—— 见「注意事项」。

验收走真实代码跑生产快照副本（`tmp/2026-08-07-x-cleanup/`，可重跑）：3 天窗口删 7272 行、
文件 21.4 → 13.2 MB、VACUUM 在 32.7% freelist 处触发，**11 条结果不变式全过**；15 天窗口
（生产默认）删 0 行且连 freelist 都没测。480 个后端测试绿（原 435 + 新增 45）。

## 修改的文件

**新增**

- `condenser/cleanup.py` — `CleanupManager`（照 `HNManager` 的生命周期写法：`startup` /
  `shutdown` / `_loop` / `_now` 测试缝 / `_tasks`）、鸭子类型的规则契约
  （`name` / `enabled(settings)` / `run(now, settings)`）、`CleanupReport` + `CleanupRun`
  （一个形状同时喂日志行、`app_meta` 和状态端点）、`XRetentionRule`、`DEFAULT_RULES` 单元组。
- `condenser/routers/cleanup.py` — `GET /api/cleanup/status`。
- `tests/test_cleanup.py` — 45 个行为场景：断点（含「新建 manager 仍读得到」这条真正证明
  重启存活的用例）、逐规则隔离、四种豁免、多 feed 存活、引用链一轮收敛、缓存孤儿自愈、
  VACUUM 阈值/失败/真实执行、worker 线程交还连接。

**修改**

- `condenser/db.py` — 新增 `# --- daily cleanup ---` 块：`_x_untouched()`（四个豁免的 SQL
  片段）、`_DELETE_X_FEED_ITEMS`、`_DELETE_X_TWEETS`、`sweep_x_retention()`（一个事务，
  正文循环到收敛）、`sqlite_freelist_ratio()`、`vacuum()`。
- `condenser/config.py` — 6 项新设置（`condenser_cleanup_*`），并更新
  `condenser_embedding_retention_days` 的注释说明读者已经换人。
- `condenser/app.py` — lifespan 里接线（startup 排在 verdict 之后，shutdown 排在最前，逆序）
  + `include_router`。
- `condenser/verdict.py` — 删除 `_prune` / `RunResult.pruned` / 调用点 / 日志参数。
- `tests/test_x_verdict.py` — 原来钉住 `_prune` 的测试换成钉住「verdict 轮次不再清理向量」。

## 注意事项

**日频任务的断点必须落库。** 这个项目 `git push` 即部署，进程重启比一天频繁得多。任何
`asyncio.sleep(24h)` 或没有持久 jobstore 的 cron trigger 都会在重启时归零/错过。项目里已有
这个模式（`hn_last_poll_at`、`x_verdict_last_run_at`），照抄即可。**一旦状态落库，调度库买不到
任何额外的耐久性** —— 这是这次没引入 APScheduler 的完整理由。

**`x_tweets.fetched_at` 语义是「最后一次见到」。** `upsert_x_tweet` 每次重推都刷新它（为了让
metrics 变动）。实测漂移：>0 天 569 行、>1 天 195 行、>3 天 19 行，最大 **following 1.92 天 /
foryou 11.87 天**。由此有一条复活路径：feed 行按 `first_seen_at` 被删，但探针还在推这条推文
→ 下一轮 `insert_x_feed_items` 用**新的** `first_seen_at` 重建 → 一条被忽略了半个月的推文跳回
未读列表顶部。11.87 < 15 今天还够不着，但只差 3 天，而且**订阅具体账号后必然触发**（账号 feed
每轮固定拉最近 N 条，低频账号的推文会长期留在窗口里）。因此 feed 行删除多了一条「探针已经不再
推它」的条件，实测代价：15 天默认值下豁免 0 行，3~7 天窗口下 1.1~3.3%。

**这个 schema 里一个外键都没有**，所以漏掉豁免不会报错，只会静默销毁。最贵的是标注集：通道 D
每轮从 `x_tweets.text` **重新拟合** n-gram 计数、通道 A 统计 `author_handle`，删掉一条被标注
推文的正文不会抛异常，只会让它悄悄不再教任何东西。验收脚本因此检查的是**结果不变式**
（「没有被标注的推文丢了正文」「没有悬空的 quote_of」「没有无主的 feed 行」），而不是代码自报的
计数。

**VACUUM 的事务边界由引擎强制**，不靠代码评审：SQLite 直接拒绝
`cannot VACUUM from within a transaction`。所以留了一个不 mock 的真实 VACUUM 测试 —— 写错位置
的话它必然失败。另外生产是 `auto_vacuum=0`，没有 `PRAGMA incremental_vacuum` 这条路。

**VACUUM 阈值在稳态下大概率不触发，这是对的。** 删掉的页进 freelist 后被第二天的写入复用，
文件停止增长（目标已达成），freelist 稳态很低。注意 15 天那次实测：freelist=0% 但 VACUUM 仍能
收回 1.6 MB —— 那是常规读写的碎片，`freelist_count` 看不见。所以这条阈值的实际语义是
「只在发生了异常积压时才整理」。

**清理轮跑在 `asyncio.to_thread` 上。** FastAPI、TG 实时监听、HN 采样、判定共用一个事件循环，
VACUUM 拿排他锁，同步跑就是卡住实时入库。peewee 连接是 thread-local（sync 路由本来就这么用），
但 worker 是池化复用的，所以 `_run_in_thread` 在 `finally` 里把连接交还，避免多钉一个 SQLite
句柄。

**`kick()` 不是每个 manager 都该有。** HN 的 kick 是「订阅后立刻采样」，verdict 的是「推送后立刻
判定」—— 清理没有对应的触发事件，没有哪个用户动作能让昨天的保留期扫描提前到期。评审指出它
零调用方后删掉了，`_loop` 用回 `asyncio.sleep`。照抄 pattern 时要问一句「这个部件在这里有意义吗」。

**全部规则失败时不推进断点。** 有任何一条规则拿到结果就推进；全灭则不推进，下一个小时重试 ——
一次瞬时的 `database is locked`（实时 TG 入库持写锁）不该白丢一天。单条失败但另一条成功仍然
推进，重跑健康的那条没有意义。

## 遗留问题

- **还没部署。** 按项目约定 `git push` 到 master 即上线。
- **上线后头一周日志会一直是 `deleted=0`** —— 快照里最老的 Following 行是 8 天前（07-30），
  For You 是 13 天前（07-25），没有任何 15 天前的数据。这是预期行为，不是故障；`/api/cleanup/status`
  就是为了让「删了 0 条」和「压根没跑过」能分辨才加的。
- **`/api/x/status` 的 `judged` 计数和 `x_verdict_label_coverage` 的分母会变成 15 天滚动窗口**
  —— 用户选择「全删」时明确接受的代价。`x_prospective_rows` 不受影响（它只取已标注行，那些永久
  豁免），所以通道准入的证据链是完整的，只是累计口径的覆盖率统计会偏高。
- **只有 X 一条规则。** `hn_stories`（2538 行 / 2.6 MB，约 130 故事/天）和 `link_previews`
  （2473 行 / 1.2 MB，TTL 只在读取时判断、行从不删除）都在只增不减地长，量级比 X 小一个数量级。
  框架已经是通用的，加规则是加一个对象，不动循环。
- **`x_attributes` 没有独立的保留期清理**，只有「正文没了就级联删」。它和 `x_embeddings` 同构
  （都是可重建缓存），但用户这次没选那一项。

## 相关文档

- [X 信源本地探针计划](../plans/2026-07-24-x-source-local-probe.md) — 该计划 §「存储」一节
  就把 retention 列为 Phase 4 的前置条件（未标注向量保留 90 天后 prune），本次 session 兑现了
  这条，并把范围从向量扩大到整个归档。
