---
created: 2026-09-16
tags:
  - rss
  - backend
  - frontend
  - plan
---

# RSS 坏源指数退避 + 「异常 feed」标记 + 手动 Refresh

> **状态：已实现（2026-09-16，同日提交）。** 后端 schema v20、前端订阅页、测试全绿。
> 本计划**推翻** `2026-08-22-rss-post-launch-fixes.md` §3 的决策（"不做退避，读者手动关"）。

## 0. 起因

生产发布验证：77 个 feed 里 **11 个每轮都失败**——halfrost.com 证书过期、blog.extrawurst.org
域名已无解析、xdash.one 403、另几个 404。存量坏源，不是回归。§3 当时押的是「读者注意到 →
手动关掉」这个回路够短，三周过去一个也没关：11 × 48 轮/天 ≈ **528 次/天**注定失败的请求。
§3 自己写了退路——「如果实际使用中发现回路太长，再回来重议退避」——现在有证据了。

## 1. 决策

1. **指数退避**：第 n 次连续失败后等 `poll_minutes × 2^(n-1)`（30m → 1h → 2h → … ），封顶
   **7 天**（`CONDENSER_RSS_BACKOFF_MAX_DAYS`）。第一次等待 = 轮询间隔，所以偶发一次失败**零成本**
   （下一轮照常重试），只有连败才拉开间隔。
2. **「异常 feed」**：连续失败 ≥ 5 次（`CONDENSER_RSS_ABNORMAL_FAILURES`）服务端标 `abnormal`。
   5 次 ≈ 15 小时——一夜宕机拿不到这个标，真死的源一天内必得。成功即清。阈值在服务端，
   订阅行的徽标与 status 的 `feeds_abnormal` 不可能对不上。
3. **仍然不自动退订、不自动暂停**——§3 的原则「判断谁是死源是读者的事」保留，服务器只是不再
   替坏源白烧请求。
4. **手动 Refresh**（参考 Miniflux）：`POST /api/sources/rss/subscriptions/refresh?url=`，
   先清退避再立即抓这一条，**无视暂停开关**（读者点它是在问「回来了吗」，答案决定要不要重新
   打开），响应带抓取结果 + 新状态。恢复（PATCH enabled=true）与重新订阅也清退避，但**不清**
   `error_count`——连败次数是证据，读者豁免的只是等待。

## 2. 落点

- `db.py`：`rss_feeds.checked_at`（每次尝试，成功失败都记；Miniflux 的 Last check）+
  `next_attempt_at`（NULL = 下轮就到期，健康源与 v20 前的老行都是 NULL）。
  `_migrate_rss_backoff_v20` 形状式 ADD COLUMN，`create_tables` 之前。`clear_rss_feed_backoff`、
  `rss_feed_abnormal_count`。
- `rss.py`：`backoff_delay()` 纯函数；`poll_once` 经 `_due()` 过滤，轮次统计多一项 `deferred`；
  `_poll_feed` 失败分支按 `feed.error_count + 1` 算等待；`refresh_feed()`；
  `describe_subscription` 多 `checked_at` / `next_attempt_at` / `abnormal`。
- `routers/rss.py`：refresh 端点（`async def`，在 app loop 上跑，与轮次共用 ingest 锁）；
  订阅 / 恢复时清退避。
- 前端 `RssSubscriptionRow`：异常行黄底 + 「异常」徽标；第二行 `last check … · last seen … ·
  next check …`（`rssFeedStatusParts`，可注入 now 以钉住文案）；第三行 `N errors – 错误原文`；
  Refresh 按钮。`RssSection`：三档排序（异常 → 失败 → 其余），refresh mutation 的 toast 把结果
  说成话（成功 + 新增数 / 仍然失败 + 原因），状态行 `N 个异常 feed 已退避` + `N deferred`。
- iOS 不动：客户端不渲染 feed 抓取状态，API 只增字段。

## 3. 验收

- 后端 `tests/test_rss.py` 新增 9 例（退避表、到期前不抓、成功清退避、deferred 不拖累他人、
  异常阈值、恢复/重订清退避、refresh 成功/失败/暂停源、v20 迁移）；旧的连败测试改为拨快时钟。
  全量 889 通过。前端 `RssSection.test.ts` +5（三档排序、状态行四种文案），296 通过，tsc 通过。
- 本地走查（scratch DB，真实网络）：`tmp/2026-09-16-rss-backoff/`——01 三种状态并列；02 正常源
  Refresh 学到标题、新增 51 条；03 halfrost Refresh 真触发证书过期，7 → 8 errors、next check
  3 天；04 暗色。

## 4. 明确不做

- 退避不按错误类型区分（NXDOMAIN 与 503 同一条曲线）：封顶一周之后差别不值一个分支。
- 不做「异常 feed 自动暂停 N 天后退订」：还是 §3 那条线。
- 订阅页不加筛选/分组：排序 + 黄底已经够找。
