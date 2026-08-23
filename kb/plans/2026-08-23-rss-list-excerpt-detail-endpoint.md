# RSS 列表载荷瘦身：摘录进列表、全文按需取

状态：待实施（本文档即移交 prompt，新会话从这里开工）
前情：iOS RSS 加载慢的排查结论（2026-08-23，commit `20af16d` 之后）

## 背景与已确认的事实（不必重新调查）

RSS 条目的 timeline envelope 目前携带整篇 `content` HTML：

- `condenser/sources/rss.py` 的 `_SELECT` 是 `SELECT e.*`，`condenser/items.py:rss_payload`
  把 `content` 原样放进 envelope。聚合 timeline、`/s/rss`、单 feed 视图都在传全文，
  iOS（`TimelineStore`）与 web 每页 30 条。
- 生产实测（`ssh hh-hk-01`，`sqlite3 /opt/apps/condenser/data/condenser.db`）：
  1583 条归档，content 平均 13.9KB，**20 条 >100KB，最大一条 7.1MB**；RSS 视图前
  8 页每页净 HTML 50–150KB（JSON 转义后更大）。翻页碰上 7MB 那条就是一次 7MB+ 下载。
- iOS 端 `RssEntry.contentText`（`ios/CondenserKit/Sources/CondenserKit/Models.swift`）
  是计算属性，每次访问对全文跑一遍 `rssPlainText`，SwiftUI 每次重渲染都重算，无缓存。
  有摘要的卡片会短路到 `summary`，无摘要的卡片全额付这个解析成本。
- web 端 `frontend/src/components/timeline/RssCard.tsx` 的 `RssBody` 渲染 sanitize 后的
  全文 HTML（line-clamp-5 + 内联 more 展开）——**今天依赖列表 payload 里有全文**。
- `records.py` 对 RSS 存的快照就是 envelope payload 本身（含 content），回放不查源表。
- `db.py:sweep_rss_retention`：**已读/已藏/已隐藏的条目行永久保留**，只清没碰过的旧条目
  ——所以已收藏条目的 `rss_entries` 行不会消失，这是快照策略权衡的关键事实。
- 搜索（`search.py`）从 `sources/rss.py:rows_by_id` 读源表行、不走 envelope，理论上不受
  影响，但要跑测试确认。

## 目标设计（方案已定，细节自行落实并写清理由）

1. **列表 payload 不再带全文**：`rss` payload 的 `content` 换成 `content_excerpt`——
   纯文本摘录（约 500 字符，标签剥净；复用/参照后端已有的文本抽取逻辑，别在客户端剥）。
   `summary` 字段不动。excerpt 建议 **ingest 时算好存列**（新列 + `SCHEMA_VERSION` 16
   迁移 + 回填存量行）；查询时现算也可接受——权衡后自己定。
   ⚠️ 动 schema 前必读 `kb/docs/database.md`（迁移约定、`init_db` 两个 load-bearing
   顺序陷阱），payload 规则的注释约定见 `items.py` 各函数。
2. **新详情接口**：`GET /api/rss/entries/{id}` 返回带全文的完整 envelope
   （`routers/rss.py`，照该文件已有的 HN/X router 形状；`require_auth`；未知 id 404）。
3. **web**：无摘要卡片渲染 excerpt（纯文本，不再 sanitize HTML）；点 more 才懒加载
   详情接口取全文，取到后走现有 sanitize + 渲染路径。收藏视图（`DatedItemRow` →
   `RssCard`）同样生效，注意快照回放的条目也要能展开。
4. **iOS**：`RssEntry` 增加 excerpt 字段；**`content` 保留为 optional**——旧收藏快照的
   payload 里仍有它，decode 不能炸（`SnapshotCache` 的契约版本号机制在
   `ios/AGENTS.md`）。卡片直接用 excerpt（不再解析 HTML）；注意 2026-08-23 起卡片
   布局是「正文开头 3 行在上 + AiSummaryBlock 摘要块在下」（commit `76150c5`），
   即**有摘要的卡片也要正文摘录**，excerpt 两种卡都用；`RssDetailSheet` 打开时拉
   详情接口取全文（loading 态；失败降级显示 excerpt）。顺手把 sheet 里的 plainText
   解析挪出渲染路径（task 里算一次存 state，别在 body 里反复算）。
5. **收藏快照是本任务最容易想岔的地方**，两条路都成立，选一条并把理由写进注释：
   - (a) 保存时按 id 重取完整 payload 写进快照——维持「快照回放不依赖源表」的既有
     设计原则（`records.py` 模块文档）；
   - (b) 依赖 retention 永不清已藏条目的事实，快照只存 excerpt、全文永远走详情接口
     ——快照变薄，但「source-decoupled」原则被打破，且回放从此依赖网络。
   倾向 (a)：原则已有、代价只是保存瞬间多一次查询。
6. **搜索**：确认索引文档仍从源表行取 content（跑 `tests/` 里 search 相关测试）；
   `TOKENIZER_VERSION` 不应需要动。

## 兼容性注意

- TestFlight 上已有 iOS 1.1.0 (3) 在解列表里的 `content`；服务端先改会让该 build 的
  无摘要卡片没正文（decode 不会炸，字段是 optional）。单用户项目、可接受，但要在
  commit message 与 `kb/docs/status-and-gaps.md` 里记一笔。
- **push master 即生产部署**——后端与 web 改完、全部测试过再 push；iOS 改动不影响部署。
- 开发方法遵循根 CLAUDE.md：新功能 BDD，先写行为测试再实现。

## 验收

- 后端：`uv run pytest` 全绿；新测试至少覆盖——列表 envelope 形状（有 excerpt、无
  content）、详情接口（全文、404）、快照含全文且回放正常、retention 清扫后收藏条目
  仍能取到全文。
- web：`pnpm test` / `pnpm build`；走查 more 展开与收藏视图（登录态浏览器走查用
  `scripts/dev-browser-login.sh`，见根 CLAUDE.md scripts 表）。
- iOS：Kit 测试 + `make test`、`make build`；模拟器截图验收。现成的 dev 环境：
  `tmp/rss-fixes-dev.db` 已插好 `devtoken-ios-sim` 的 device 行，条目 169/171 有
  伪造中文摘要且时间戳已顶到最前（起法见 `ios/AGENTS.md`「跳过授权直连本地后端」+
  「CLI 驱动的界面走查」，路由 `rss` / `detail/rss/<id>`）。截图归档
  `tmp/<date>-<task>/`，测完 `mac-dev-cleanup --only sim`。
- 量化：改造前后各测一次 `GET /api/timeline?source=rss&limit=30` 的响应字节数，
  写进最终报告（before 数据可直接在生产复测）。
- 文档同步：根 `CLAUDE.md` 的 `rss.py` / `items.py` 行、`frontend/CLAUDE.md` 的
  `RssCard` 行、`ios/AGENTS.md` 的 RSS bullet、`kb/docs/database.md` changelog
  （若有迁移）、`kb/docs/status-and-gaps.md` 记录本次改动。
- 分阶段 commit；本文档实施完把状态行改成「已完成」。
