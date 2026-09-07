# iOS：启动恢复阅读现场 + 蓝色可关闭「N 条新内容」胶囊 + 只返回计数的接口

日期：2026-09-07　状态：**已完成**（后端 817 / Kit 298 测试全绿，模拟器走查 8 张图在 `tmp/2026-09-07-ios-state-restore/`；总结见 `kb/docs/ios.md` 末节）

## 0. 现状与问题

- 冷启动：`TimelineStore.loadInitial` 先渲染快照，再网络拉首页**整页替换**，相对快照多出的条数
  用灰色不可点 toast 事后告知（2026-07-22 决定，`kb/docs/ios.md`「Silent refresh + gray toast」）。
  代价：每次打开 app 都回到顶部、内容在眼前换掉，上次读到哪、开着哪个抽屉全丢。
- 回前台（后台 ≥5 分钟）：`NewContentChecker.check()` 打 `GET /api/timeline/new?limit=100`
  拿 `count`——它同时把最多 100 条 envelope 也拉回来，只为读一个数字。有新内容就**强制回顶 +
  刷新**，同样打断阅读位置。
- 「哪个时间线」（信源过滤 / 未读开关 / 订阅 tab 推入的单 feed）、tab、滚动位置、打开的详情
  sheet 全部不持久化。

## 1. 目标

1. 启动时恢复上次的：tab、主 timeline 的信源过滤 + 未读开关、订阅 tab 推入的单 feed 视图、
   列表滚动位置（以顶部可见条目 key 为锚）、打开的详情 sheet（条目 key）。
2. 保留「打开 / 回前台检查新内容」的机制，但**只**在列表上方浮一个胶囊「↑ N 条新内容」，
   不回顶、不刷新、不动内容。
3. 胶囊为**蓝色**（可点 = 会有动作：回顶 + 刷新），带醒目的关闭按钮；点关闭只消失，不做任何事。
4. 检查用**专门只返回条数的接口** `GET /api/timeline/new/count`，各源走 `COUNT` SQL，不构造 envelope。

## 2. 后端

- `sources/*.count_new(after, …, unread_only) -> int`：与各自 `fetch_new` 同一份 WHERE，
  投影换成 `COUNT`。Telegram 数的是**显示单元**（`COUNT(DISTINCT COALESCE(m.grouped_id, m.id))`，
  与 `days` 同款），否则一个 5 图相册会报 5 条。
- `timeline.query_new_count(...) -> {'count': n}`：按 `_active_sources` 遍历、锚点缺席的源跳过
  （与 `query_new` 同规则）。
- `GET /api/timeline/new/count`，参数同 `/timeline/new` 去掉 `limit`；坏游标 422。
  `/timeline/new` 原样保留（web 仍用它取 items）。

## 3. iOS Kit

- `CondenserAPI.timelineNewCount(after:channelID:unreadOnly:source:feed:) -> Int`；
  `NewContentChecker.check()` 改用它。
- `TimelineStore.loadInitial(preferSnapshot:)`：`preferSnapshot = true` 且有快照 → 只渲染快照、
  **不打网络**、返回 true（这就是「上次的现场」）；否则老路径（快照→网络替换）。
  `persistSnapshot()`：把当前已加载的条目（含本地已读标记，最多 300 条）+ 游标写回快照，
  `loadMore` 成功后与退后台时各调一次，深处的滚动位置才有东西可锚。
  `scopeKey`：一个列表的身份（`channel-<id>` / `<source>[-<feed>]-<unread|all>`），列表状态按它落。
- `ReadingState`（Codable）+ `ReadingStateStore`（UserDefaults，可注入）：
  `tab`、`source`、`unreadOnly`、`pushed`（订阅 tab 推入的目标：kind + `SourceSub`）、
  `lists: [scopeKey: {topItemKey, openItemKey, updatedAt}]`（容量 32，淘汰最旧）。
- `ForegroundRefreshPolicy` 默认阈值 300s → 60s：原来的 5 分钟是因为刷新会打断阅读位置，
  现在胶囊不打断，唯一成本是一次 COUNT 请求。

## 4. iOS App

- `MessageListView`：`ScrollView` 改用 `.scrollPosition(id:)` + `scrollTargetLayout()`（顶部
  哨兵进 LazyVStack）；`scrolledID` / `selectedItem` 变化即写 `ReadingState.lists[scopeKey]`；
  `loadInitial` 后恢复滚动（key 在列表里才滚）与 sheet。
  首个 store（启动）走 `preferSnapshot`，随后 `checker.check()` → 计数 > 0 弹胶囊；
  回前台按 policy 检查 → 弹/更新胶囊；下拉刷新 / 点胶囊主体 → 回顶 + 刷新 + 收胶囊；
  点 ✕ → 只收。信源 / 未读切换重建的 store 沿用旧路径（快照→网络替换，无 toast）。
- `ReaderSession`：从 `ReadingState` 恢复 `selectedSource` / `unreadOnly`，setter 回写。
- `MainView`：`selectedTab` 与 `subscriptionsPath`（改成 `[SubDestination]`）恢复 + 回写。
- 退后台落盘放在 `MessageListView` 自己的 scenePhase 回调里（先 `markLocallyRead(readReporter.readKeys)` 再 `persistSnapshot()`，无 cache 的 store 是 no-op），`TimelineScreen` 只留已读冲刷。

## 5. 不做 / 已知边界

- 推入的单 feed 视图不落快照（沿用「临时态」决定，RSS 200 个 feed 各存一份不划算）：
  恢复它只恢复「进到哪个 feed」+ 首页里找得到锚点就滚过去，找不到从顶部开始。
- 恢复的滚动锚点不在快照 300 条里 → 从顶部开始。
- 胶囊不自动消失：它是可操作的提示，用户已给了关闭按钮。

## 6. 验收

Kit `swift test` 全绿；后端 `uv run pytest` 全绿；模拟器走查：启动恢复到深处 + 抽屉、胶囊出现 /
点 ✕ 消失不动列表 / 点主体回顶刷新。截图归档 `tmp/2026-09-07-ios-state-restore/`。
