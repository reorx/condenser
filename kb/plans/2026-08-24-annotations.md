---
created: 2026-08-24
tags:
  - ios
  - backend
  - annotations
  - feature-plan
---

# 标注功能：条目 note + 正文高亮 annotation（iOS 先行）

> **进度**（2026-08-24）：Phase 1 后端已完成 ✅（schema 落地为 **v18** —— v17 被同日合并的
> forward-records 占用；note/annotations 下发未加 provider 列，沿用 `forwards.stamp` 的
> 后置盖章模式，见 `records.stamp_notes`；`kb/docs/database.md` v18 changelog 有全部决策）。
> Phase 2 Kit 已完成 ✅（`ItemAnnotation` + envelope 字段、`Annotations.swift`
> 重定位纯函数——精确搜 → 空白折叠兜底 → prefix/suffix 打分、block 提示只当
> tie-break；API 四调用走具体 `APIClient` 不进协议，`rssEntry` 先例）。
> Phase 3 iOS UI 未动。

作为 `2026-08-23-ios-share-image.md` 的后续：对任意信息源的条目可以写一条整体 note，
或对正文选中文字加一条或多条 annotation（高亮 + 可选评论）。数据在服务端，v1 只在
iOS 实现 UI。本计划由一轮 grilling 会话敲定，决策记录见下。

## 决策记录（grilling 结论）

1. **服务端存储，iOS 只是第一个做 UI 的端。** 本项目的一贯形态是「服务端是唯一事实
   源，客户端无状态」（已读/收藏/反馈全在服务端 SQLite，iOS 无本地数据库）；标注是
   最核心的用户创作数据，不能成为唯一一份不进服务端备份的东西。
2. **落在 `saved_items` 上，语义升格**（schema v17）：这张表从「收藏表」升格为
   「用户操作过、需要永久保存的条目表」，`is_saved` 只是其中一种状态。加三列：
   - `is_saved BOOLEAN DEFAULT true` —— 存量行迁移后语义自动对齐；
   - `note TEXT NULL` —— 条目级评论；
   - `annotations TEXT NULL` —— JSON 数组，一行一条高亮。
   选它而不是独立表，是因为这张表的核心承诺（`raw_data` 快照 = 内容脱离源表也能
   渲染）恰好是标注需要的同一个承诺。其余 reader-state 表（`read_items` 等）是可再生
   的临时数据，语义不同。
3. **行生命周期不变式：行存在 ⟺ `is_saved` 或 note 非空 或 annotations 非空。**
   - 取消收藏带标注的条目 → 只翻 `is_saved=false`，标注保留（web 的 unsave 也走这条，
     否则 web 点一下取消收藏就把标注连坐删了——web UI 本轮不动，但后端语义必须先改）；
   - 删到三者皆空 → 删行，不留空壳；
   - 对无行条目首次加 note/annotation → 建行 `is_saved=false` **并照常拍
     `records.py` 快照**。这步不能省：X/RSS 源表有 retention 清扫，快照是标注几个月后
     不悬空的唯一保障。
   - ⚠️ `annotations` JSON 列的增删改是读-改-写，所有写路径必须
     `atomic(lock_type='IMMEDIATE')` 且不嵌套（`tests/test_db_locking.py` 钉死的规矩）。
4. **v1 标注范围 = 条目正文**：TG 消息正文 / HN self-post 正文（外链 story 无可标注
   文字）/ X 推文正文（**不含**引用推文卡——那是别人的条目）/ RSS 正文文本块（**不含
   AI 摘要**——生成物，模型一换就重写，且不在快照的正文承诺里）。排除项兜底 = 条目级
   note。
5. **锚点 = 引文三元组 `{quote, prefix, suffix}`**（W3C TextQuoteSelector 模型）。
   调研结论（2026-08-23）：无现成 Swift 库——Readium swift-toolkit 的高亮锚在它自己
   的 Publication Locator 上且渲染走 WebView，不可搬；TextQuoteSelector 的实现全在
   JS 生态（Hypothesis / Apache Annotator）；但 Hypothesis 与 Readium 殊途同归都收敛
   到引文兜底，侧面验证了 offset 不可靠。**offset 是锚在流沙上**：四个源屏幕上的正文
   都是 Kit 派生的（X 经 t.co→display_url 替换，HN/RSS 经 HTML→纯文本管线，且
   `hnPlainText` 昨天刚因实体解码整体变过一次），app 升级 = 派生管线可能变，快照冻结
   的是 payload 不是派生文本。Kit 自实现重定位纯函数：搜 `quote` 的所有出现位置，多处
   命中用 prefix/suffix 挑最像；找不到 = **孤儿高亮**，正文不亮但引文与评论保留可见，
   不静默丢数据。锚在**屏幕显示的派生文本**上；RSS 另存 `block` 索引仅作搜索提示，
   真值是引文（选区在单个 UITextView 内完成，quote 天然不跨块）。
6. **可见性**：Records/Saved 列出全部行（收藏的 + 只标注的），行上图标区分——星 =
   收藏，批注角标 = 有标注。找回标注是记笔记功能的基本诉求。
7. **下发走 envelope**：`note` / `annotations` 与 `feedback` 同级进 envelope
   （`items.py` 拼装时本来就查 `saved_items`）。抽屉一打开即可渲染，无额外请求。
   旧 iOS build 的 Codable 忽略未知字段，安全（`feedback_reason` 的先例：新字段只加
   不改）。
8. **写入 API**（沿 feedback 端点惯例，key 走 `parse_key_or_422`）：
   ```
   POST   /api/note            {key, note}        # 覆盖语义；空串 → 清除
   POST   /api/annotations     {key, quote, prefix, suffix, block?, comment?}
                                                  # 服务端分配条目内自增 id + created_at
   PATCH  /api/annotations/{key}/{id}  {comment}  # 改/清评论
   DELETE /api/annotations/{key}/{id}             # 删高亮
   ```
   不做批量端点；不做改 quote（改高亮范围 = 删了重画，UI 交互也如此）。
9. **条目评论抽屉**（入口在 `ItemActionRow` 新增「评论」按钮）：
   - 重开即编辑：预填现有 note；清空保存 = 删除（对应空串清除语义），无单独删除按钮；
   - **「转发」= 先落库再转发**：`POST /api/note` 成功后关本抽屉、开现有
     `ForwardDialog` 并预填 comment（用户打了字只进 TG 没进笔记的惊讶感必须避免）；
   - 转发弹窗里继续改文本只影响发出的消息，**不回写 note**。
10. **高亮交互全走系统编辑菜单**（UIEditMenuInteraction），不自绘 popover：
    - 选中文字 → delegate `textView(_:editMenuForTextIn:suggestedActions:)` 插入
      「高亮」项 → 浅黄底 + 深黄下划线；
    - 点已有高亮 → tap 手势 + TextKit 坐标→字符索引 → `presentEditMenu` 程序化弹出
      「评论」「删除」；
    - 高亮评论镜像 note 语义（预填、清空确认 = 删评论留高亮）；有无评论外观相同；
    - 允许重叠不合并，重叠处点击命中**范围最短**那条。
11. **v1 明确不做**：分享图片渲染高亮（v2 再议——技术可行，但「发给别人的图带不带
    私人标记」本身存疑）；note/评论进 FTS 搜索（新增文档源要动 `TOKENIZER_VERSION`
    全量重建，等笔记有量再做）。

## 现状事实（探索已核实，2026-08-23）

- 四个详情抽屉的正文**全部**走 `SelectableTextView`（`UIViewRepresentable` 包
  `UITextView`，`ios/Condenser/UI/SelectableTextView.swift`）：TG `message.text` 原样、
  HN `hnPlainText(fromHTML:)` 渲染时现算、X `tweet.bodyText`、RSS 每个文本块一个
  （`RssDetailSheet.swift`，块数组 `id: \.offset`；全文未到手时回落单个 excerpt 视图）。
  AI 摘要块也是 `SelectableTextView`（但不在标注范围）。
- `SelectableTextView` 目前**零** editMenu 定制；attributedText 由
  `Linkify.swift:linkifiedNS` 构造（NSDataDetector 加 `.link`；X 按 `urlEntities` 把
  t.co 原地替换成 display_url——**屏幕字符串 ≠ payload 原文**）。
- 转发链路已有 comment：iOS `ForwardDialog(itemKey:isTelegram:)` →
  `POST /api/forward {key, comment?}` → `forward.render` 把 comment 作为 escaped 前缀。
  `ForwardDialog` 目前无初始文本参数（要加）。
- 后端无任何 note/annotation/highlight 表或字段。`saved_items` 现结构：
  `(source, ref1, ref2)` 复合 PK + `raw_data` + `created_at`。
- iOS 无本地数据库（只有 JSON 快照缓存 / Keychain / UserDefaults）；Kit 里 key 是裸
  String（`TimelineItem.key`），抽屉签名 = `(item: TimelineItem, 具体 payload, 回调…)`。
- RSS 全文来自 `GET /api/rss/entries/{id}`（详情抽屉 `.task` 拉取）；切块管线
  `RssBlocks.swift:rssBlocks(fromHTML:baseURL:)` 确定性派生。

## 实现方案

### Phase 1 — 后端（schema v17 + API + envelope）

- `db.py`：迁移 v17（shape-based `ADD COLUMN` ×3，注意 `init_db` 的两条 ordering
  constraint）；`SCHEMA_VERSION = 17`；CRUD 函数（`set_note` / `add_annotation` /
  `update_annotation_comment` / `delete_annotation`），全部 IMMEDIATE、内含建行拍快照
  与删空壳逻辑；unsave 改按不变式。
- `items.py`：envelope 加 `note` / `annotations` 字段（仅行存在时非 null）；`is_saved`
  改为 `row exists AND is_saved`。
- `records.py`：列表查询覆盖全部行；快照构建复用现有 per-source 逻辑（RSS 快照含正文，
  2026-08-23 已落地）。
- `routers/reading.py`（或新 router）：四个端点 + pydantic body。
- `kb/docs/database.md` 补 v17 changelog。
- 测试（TDD/BDD 先行）：不变式全路径（建行拍快照 / unsave 保留标注 / 删空壳）、
  迁移幂等、envelope 字段、四端点含 404/422、IMMEDIATE 锁行为。

### Phase 2 — Kit（模型 + 锚点重定位）

- `Models.swift`：`ItemAnnotation { id, quote, prefix, suffix, block?, comment?,
  createdAt }`；`TimelineItem` 加 `note` / `annotations`（可选，旧服务器兼容）。
- 新 `Annotations.swift`：重定位纯函数
  `locate(_ annotation: ItemAnnotation, in blocks: [String]) -> (block: Int, range: Range<String.Index>)?`
  —— 全量命中 + prefix/suffix 打分挑最像，nil = 孤儿。
- `APIClient`：四个调用。
- Swift Testing：唯一命中 / 多处命中靠上下文区分 / 管线漂移仍命中（空白差异）/
  孤儿返回 nil / RSS block 提示失效时全文搜兜底。

### Phase 3 — iOS UI

- `SelectableTextView` 扩展：`highlights: [NSRange]` 属性（浅黄 `backgroundColor` +
  深黄 `.underlineStyle/.underlineColor`，叠在 `linkifiedNS` 之上）；delegate 插
  「高亮」编辑菜单项（回调带选区文本 + 前后 30 字上下文）；tap 手势 → 字符索引 →
  命中最短高亮 → `presentEditMenu`「评论」「删除」。
- 高亮评论抽屉（新 sheet）：顶部引文展示 + 输入框 + 确认。
- 条目评论抽屉（新 sheet）：`TextEditor` 预填 note + 「保存」「转发」；转发 = 先
  `POST /api/note` 再开 `ForwardDialog(initialComment:)`（加参数）。
- `ItemActionButtons` 加「评论」按钮（`text.bubble`，有 note 时 filled 变体）。
- 四个抽屉接线：把 item 的 annotations 经重定位映射成各正文视图的 `highlights`；
  RSS excerpt 回落态禁用高亮入口；孤儿高亮在抽屉尾部列出（引文 + 评论）。
- Saved 列表行加批注角标。

### 验收

模拟器 DEBUG deep-link 走查：四个源各做「选中→高亮→点高亮→评论→删除」、条目评论
「保存 / 转发预填」、杀 app 重开高亮恢复、unsave 后标注仍在 Saved 可见。截图归档
`tmp/<date>-ios-annotations/`，完事 `mac-dev-cleanup --only sim`。每个 phase 完成后
commit。
