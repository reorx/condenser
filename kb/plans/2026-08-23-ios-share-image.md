---
created: 2026-08-23
tags:
  - ios
  - share
  - image-renderer
  - feature-plan
---

# iOS 详情抽屉「生成图片并分享」

在四个详情抽屉（TG / HN / X / RSS）的 `ItemActionRow` 里新增一个「分享图片」按钮：
把该条目的主体内容渲染成一张长图，通过系统分享面板（`UIActivityViewController`）
分享出去。本计划由一轮 grilling 会话敲定，决策记录见下。

## 决策记录（grilling 结论）

1. **渲染路线 = 专用 ShareCard 视图，不截屏现有抽屉。**
   原始设想是"对抽屉滚动截图并裁掉底部按钮"，被两条技术事实否掉：
   - SwiftUI `ImageRenderer` **不渲染 UIKit 桥接视图**——抽屉正文恰好是
     `SelectableTextView`（`UIViewRepresentable` 包 `UITextView`），直接渲染正文位置是空白。
   - UIKit 路线（`drawHierarchy`）只截可见视口；对 SwiftUI 托管的 ScrollView 做全内容
     离屏渲染 + 像素级裁掉滚动内容中段的按钮行，脆且丑。
   结论：每个 source 写一个**纯 SwiftUI** 的分享卡片视图（正文用 `Text`，图片用预取好的
   `UIImage`），布局复刻抽屉观感，`ImageRenderer` 一次渲出全高图。
2. **覆盖全部四个 source**（TG / HN / X / RSS），共享卡片骨架摊薄边际成本，入口全 app 一致。
3. **内容清单**（原则：接收者不打开 app 也能看懂这条信息）：

   | Source | 包含 | 排除 |
   |---|---|---|
   | TG | 频道头像+名称、转发来源、日期、正文、图片、网页预览卡 | `MessageStatsRow`、按钮 |
   | HN | HN 标识、标题、分数/评论数/域名、自文正文、链接预览卡 | 按钮 |
   | X | 作者头像+名称+handle、日期、正文、媒体图、引用推文卡、转/赞 metrics 行 | verdict 区、反馈区、info 区、按钮 |
   | RSS | 源名称、标题、日期、AI 摘要、正文全文 | 按钮 |

4. **高度不封顶**：忠实渲染全文，不截断。只设一道极端保险丝（内容高度 > 20000pt 时
   报错提示而非硬渲染，防内存峰值炸掉）。
5. **外观固定**：固定浅色（`.environment(\.colorScheme, .light)`），固定标准字号
   （**忽略** `readingFontScale`）。理由：图是给接收者看的，不该继承分享者的主题/字号。
6. **底部落款**：一行低调灰字——左 Condenser 名 + app 小图标，右侧条目日期或来源域名。
   **不放**二维码/链接（自托管实例，链接对外无意义；原文链接已在内容区）。
7. **按钮并入 `ItemActionRow`**：与现有按钮同款 `.bordered` 样式，`Label("分享图片",
   systemImage: "square.and.arrow.up")`，排在各 source 按钮行行尾。不做独立通栏按钮。
8. **点击后流程**（推荐方案，用户以「写下 plan」默认采纳，未单独确认）：
   - 点按钮才生成，按钮原地进 loading 态（转圈 + 禁用，模式类似「复制全文」的临时态）。
   - 先经 `ImageLoader` 预取卡片所需全部图片；**超时 5s**，仍缺的图渲染成灰色占位块
     （不无限等、不整体失败）。预载/渲染抛错 → toast 报错、按钮复位。
   - 产物 PNG，**宽 400pt、scale 3**（约 1200px 宽），弹 `UIActivityViewController`。
     不用 `ShareLink`（它要求初始化时持有成品数据，与按需生成相性差）。
   - Info.plist 新增 `NSPhotoLibraryAddUsageDescription`（分享面板"保存到相册"需要；
     下个 build 提审会看到这条新权限声明，正常不构成风险）。

## 现状事实（探索已核实，2026-08-23）

- 四个抽屉：`ios/Condenser/UI/{Message,Hn,X,Rss}DetailSheet.swift`，均为
  `.sheet` + `[.medium, .large]` detents，内部 `ScrollView { VStack(spacing:14).padding(16) }`。
- 底部无固定按钮栏；"最下方" = 滚动内容末尾 `Divider()` + `ItemActionRow`
  （`ios/Condenser/UI/ItemActionButtons.swift`，横向 ScrollView + HStack，`.bordered` 小按钮）。
- 全 app 目前**零**分享（`ShareLink` / `UIActivityViewController`）与**零**截图
  （`ImageRenderer` / `drawHierarchy`）代码。`SnapshotCache.swift` 是 JSON 时间线缓存，与截图无关。
- 图片全走后端代理 + Bearer 头：`APIClient` 的 `mediaURL` / `xAvatarURL` /
  `proxiedImageURL` / `avatarURL`，`ImageLoader.shared`（64MB 内存 / 512MB 磁盘 URLCache）。
- 部署目标 iOS 18，iPhone 竖屏 only。`ImageRenderer` iOS 16+，无版本顾虑。
- ⚠️ RSS 列表 payload 自 2026-08-23 起只带 `content_excerpt`；全文走
  `GET /api/rss/entries/{id}`（详情抽屉同源）。RSS 卡片的"正文全文"必须取自详情数据，
  不能拿列表 excerpt 渲染。若 `2026-08-23-ios-rss-article-images.md` 落地（RSS 正文图片），
  这些图片同样进入预载集合。

## 实现方案

### 新增文件（`ios/Condenser/`，除注明外）

| 文件 | 职责 |
|---|---|
| `Share/ShareCard.swift` | 卡片骨架：`ShareCardFrame { header; content; footer }` —— 固定宽 400pt、白底、统一 padding、底部落款行。`.environment(\.colorScheme, .light)` + 固定 `dynamicTypeSize` 在这里统一施加 |
| `Share/TgShareCard.swift` 等四个 | 各 source 的内容视图。**纯 SwiftUI**：正文 `Text`（可用 `AttributedString` 做 linkify 高亮，但不可引入任何 `UIViewRepresentable`）；图片一律 `Image(uiImage:)` 接受注入的成品 `UIImage` |
| `Share/ShareImageGenerator.swift` | 流程编排：收集卡片所需图片 URL → `ImageLoader` 并发预取（5s 超时，缺图记为占位）→ 构造卡片视图 → `ImageRenderer`（`proposedSize` 宽 400、`scale = 3`）→ 高度保险丝（>20000pt 抛错）→ 产出 PNG `Data` / 临时文件 URL |
| `Share/ShareImageButton.swift` | `ItemActionRow` 里的按钮：idle / loading（`ProgressView` + 禁用）/ 失败 toast；成功后弹分享面板 |
| `Share/ActivityShareSheet.swift` | `UIActivityViewController` 的 `UIViewControllerRepresentable` 包装（分享 PNG 临时文件 URL，带文件名如 `condenser-<key>.png`，让接收端显示体面） |

### 改动文件

- 四个 `*DetailSheet.swift`：`ItemActionRow` 行尾加 `ShareImageButton(item:...)`。
- `RssDetailSheet` 相关：分享入口复用抽屉已取到的全文数据（不重复请求）。
- `project.yml` / Info.plist：`NSPhotoLibraryAddUsageDescription`（中文文案，说明仅在
  用户选择"保存图片"时写入相册）。
- App 图标小图用于落款（bundle 内已有 AppIcon，取 60pt 版本或内置一份小 PNG）。

### 关键实现注意

- **`ImageRenderer` 必须在主线程**创建与渲染（它持有 SwiftUI 视图）；图片预取在
  `Task` 里并发做，渲染回主 actor。
- 预取的 `UIImage` 经模型注入卡片（如 `struct ShareImages { var byURL: [URL: UIImage] }`），
  卡片视图内**不得**出现异步加载路径——`ImageRenderer` 是同步一帧，async 图渲不进去。
- 图片占位块：灰底 + `photo` SF Symbol，尺寸沿用后端给的 `media_width/height` 比例
  （无尺寸则 4:3），与前端 skeleton 的比例约定一致。
- 头像取不到（404 → 字母头像）时，直接画字母头像（`ChannelAvatarView` 的 fallback 逻辑
  在纯 SwiftUI 里复刻即可，本来就不是 UIKit）。
- 渲染 PNG 落到 `FileManager.temporaryDirectory`，分享面板关闭后删除。

## 测试与验收（BDD）

先写测试再实现：

1. **CondenserKit / 纯逻辑**（Swift Testing）：
   - 卡片内容模型构建：给定各 source 的 item/payload，断言进卡片的字段集合与排除项
     （metrics 行在、verdict 区不在；RSS 用全文非 excerpt）。
   - 图片 URL 收集器：TG 照片 + 预览图 / X 媒体 + 头像 + 引用卡 / RSS 正文图，去重、上限。
2. **渲染冒烟**（app target 单测或 DEBUG 工具）：`ShareImageGenerator` 对固定 fixture
   渲出非空 PNG，尺寸 = 1200 × (h×3)；超高 fixture 触发保险丝错误。
3. **模拟器验收**：DEBUG deep-link 打开各 source 详情 → 点「分享图片」→ 截图分享面板 +
   把生成的 PNG 从 tmp 拷出人工检查（浅色、无按钮、落款在）。截图归档
   `tmp/<date>-ios-share-image/`，完事跑 `mac-dev-cleanup --only sim`。

## 阶段划分

1. **Phase 1 — 骨架与 TG**：ShareCardFrame + 生成器 + 按钮 + TG 卡片，全流程打通（含
   Info.plist、分享面板、临时文件清理），模拟器验收。
2. **Phase 2 — 其余三源**：HN / X / RSS 卡片（RSS 注意全文来源），各自验收。
3. **Phase 3 — 打磨**：占位块、保险丝、错误 toast、落款细节、测试补齐，提交。

每个 phase 完成后 commit。

---

## 落地记录（2026-08-23，三个 phase 全部完成）

三处与计划不同，都是实现时撞出来的：

1. **一个渲染器，不是四个卡片视图。** 四个源的骨架完全相同，差别只在「有哪些块、什么
   顺序」，于是内容取舍做成 Kit 的纯数据模型（`ShareCard` + `ShareBlock` 块序列，
   26 个测试），app 侧只留一个 `ShareCardView`。好处是取舍有测试盯着——「X 的判定不进图」
   写成了「同一条推文带不带 verdict，卡片一模一样」（`ShareCard` 是 `Equatable`）——
   而四个源的观感不会各自漂移。元信息行是**块**不是卡片字段，因为它的位置四个源不一样
   （HN 紧跟标题、X 在正文与引用推之后）。
2. ⚠️ **高度封顶在 8192px，不是 20000pt——这是平台限制。** 位图高度超过 8192px 时渲染
   **不报错**，安静地给一张全黑图（逐级实测：800×6526px 正常，1200×9789px 全黑；
   `uiImage` 照样返回 UIImage，`pngData()` 返回 nil，JPEG 给出一张黑的）。所以流程是
   **先量后画**：`render` 只量尺寸不给绘制回调，量到的高度决定 scale（≤2730pt 走 scale 3
   ≈ 1200px 宽，再长按 8192px 反推，下限 1x），装不下就报「这条内容太长了（约 N 屏）」。
   一篇阮一峰周刊量出来 17555pt ≈ 21 屏，就是被挡住的那类内容——**拒绝而不是切成多张**
   是当场拍的板（切片技术上可行：`render` 的回调里平移上下文分片画）。
   计划里「高度不封顶」这条因此只在 8192px 以内成立。
3. **PNG 分两路。** ≤4096px 走 PNG，更长走 JPEG q0.9——PNG 对照片几乎不压缩，一篇图多的
   长文能到十几 MB，而这些图是要发给人的。实测：TG 1200×1428 PNG 532KB、
   X 1200×3134 PNG 1.6MB、云风博客全文 1005×8191 JPEG 3.1MB。
   文件名带 item key（`condenser-tg-1853633861-2828.png`），扩展名由编码那步定。

另外三点小差异：分享面板直接从最上层 VC present（不做 `UIViewControllerRepresentable`
包装——包成 sheet 根视图会先弹一张空白 sheet）；文件放在 `Condenser/UI/Share/` 而不是
`Condenser/Share/`（跟着 `App/ UI/ Services/` 的既有分层）；落款小图是新加的
`ShareMark.imageset`（AppIcon 缩到 96px），因为 appiconset 不能当普通 `Image` 用。

顺带修掉一个抽屉里一直存在、被分享图照出来的老问题：`hnPlainText` 只认几个命名实体，
而 HN 的 href 本身是转义的（`&#x2F;`），链接那条规则又刚把锚文本换成 href——正文里印的
就是一串 `&#x2F;`。改用与 RSS 共用的实体解码（含数字实体），先写复现测试再改。

验收：268 Kit 全绿；四个源逐个在模拟器上出图（DEBUG 入口 `CONDENSER_DEBUG_SHARE=1`），
外加深色模拟器下确认图仍是浅色、占位块（预载超时）版面不塌、超长文章的报错文案。
截图与产物 `tmp/2026-08-23-ios-share-image/`。
