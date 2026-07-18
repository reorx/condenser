---
created: 2026-07-18
tags:
  - ios
  - swiftui
  - bugfix
  - tdd
  - performance
---

# 修复 AutoHideBars 自激振荡导致的整机卡死：显隐决策纯逻辑化 + 用户滚动门控与切换冷却

## 概要

上一个 session（阅读体验 polish）上线后真机复现严重 bug：打开 app 在未读/timeline
顶部附近轻轻上划，界面彻底无响应必须强退。定位到 `AutoHideBars` 形成了自激振荡的布局
死循环：它监听 `contentOffset.y + contentInsets.top` 按位移方向切换 bars 显隐，但
bars 的隐藏/显示本身会改变 ScrollView 的 safe-area insets——insets 恰是被监听值的一部分。
上划 >8pt → 隐藏导航栏 → insets 动画期间被监听值骤降 ~100pt → 命中"向下滑"分支 →
恢复 bars → insets 回涨 → 又命中"向上滑"分支，永不收敛；顶部附近还有第二条回路
（insets 骤降把值打成负数 → 命中 `newOffset <= 0` 强制显示规则）。每次切换引发整个
LazyVStack 全量重排，且每张可见卡片每次 body 求值都新建一个 NSDataDetector（毫秒级
构造）放大成本，主线程被钉死在 100%。修复按 TDD：先把显隐决策抽成 CondenserKit 纯逻辑
`BarsVisibilityModel` 并写出振荡复现回归测试（红灯），再实现双重防线——方向判定只在
用户真正滚动时生效（scroll phase 门控）+ 每次切换后 400ms 冷却窗口吞掉 bars 动画期间
的虚假位移（含顶部规则）；`AutoHideBars` 退化为薄接线层，未切换时完全不写 `@State`；
`linkified` 的 NSDataDetector 改为全局缓存。`make build` 通过、72 个 Kit 测试全绿
（63 + 新增 9），`make device` 已装机验证。

## 修改的文件

- `ios/CondenserKit/Sources/CondenserKit/BarsVisibilityModel.swift` — 新文件：bars 显隐
  决策纯逻辑。`handleScroll(from:to:now:)` 返回是否切换；冷却期内一律忽略（含顶部规则），
  非用户滚动只响应"回到顶部"（保程序滚回顶时 bars 恢复），方向判定带 8pt 阈值。
- `ios/CondenserKit/Tests/CondenserKitTests/BarsVisibilityModelTests.swift` — 新文件：
  9 个行为测试，核心是"冷却期内忽略 insets 动画造成的反向位移"（卡死 bug 的最小复现
  序列：隐藏 → 值骤降 → 变负，断言不弹回）；时间用注入的 `ContinuousClock.Instant`。
- `ios/Condenser/UI/AutoHideBars.swift` — 重写为接线层：`onScrollPhaseChange` 维护
  `isUserScrolling`（tracking/interacting/decelerating 为真，`.animating` 程序滚动不算），
  `onScrollGeometryChange` 喂位移给模型，仅在模型确认切换时 `withAnimation` 写状态。
- `ios/Condenser/UI/Linkify.swift` — `NSDataDetector` 从每次调用新建改为文件级 `let`
  全局缓存（构造成本高，matching 线程安全）。
- `AGENTS.md` — iOS 段落更新 AutoHideBars 机制描述，注明反馈回路风险与防护设计。

## 注意事项

- **SwiftUI 几何监听的反馈回路**：凡是 `onScrollGeometryChange` 的被监听值包含会被
  自己触发的状态改变的量（bars 显隐 ↔ safe-area insets），就存在自激振荡风险。防护要
  结构性：判定门控在用户输入相位上（`onScrollPhaseChange`），再加状态切换后的冷却窗口
  （要大于切换动画时长，这里 400ms > 0.2s）双保险；只靠阈值挡不住 insets 动画的 ~100pt
  逐帧位移。
- **决策逻辑下沉到 Kit 纯 struct 的收益**：UI 死循环这类 bug 本体无法直接单测，但把
  "输入位移序列 → 显隐决策"抽成纯函数后，振荡序列就是一组普通测试输入；时钟以
  `ContinuousClock.Instant` 参数注入，测试不用 sleep。
- **`@State` 写入纪律**：滚动几何回调每帧触发，未发生决策变化时不要写 `@State`
  （包括"赋回相同值"），否则每个滚动 tick 都可能触发 modifier 子树重渲染。
- **Swift Testing 宏限制**：`#expect(...)` 展开后闭包参数不可变，不能直接内联调用
  mutating 方法，先 `let changed = model.handleScroll(...)` 再断言。
- **NSDataDetector 构造毫秒级**：出现在每帧重复执行的路径（body 求值、布局回调）时
  必须缓存；matching 线程安全，全局单例即可。
- **教训（上一 session 的验证盲区）**：模拟器走查只覆盖了静态渲染截图，没有真实持续
  滚动手势，这类交互反馈型 bug 只在真机/真手势下暴露；涉及滚动驱动的状态机改动应
  `make device` 实滑验证。

## 相关文档

- [上一次 session：阅读体验 polish](2026-07-18-ios-reading-ux-polish.md) — 本次修复的 bug 由该 session 的 `AutoHideBars` 引入
- [iOS reader app 计划](../plans/2026-07-16-ios-reader-app.md) — 项目背景计划
