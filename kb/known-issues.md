# Known Issues

> 当前 app 已知、待后续处理的问题：缺陷、简化实现、未验收项、待建流程。只反映最新状态——解决了就删掉条目，经过记到 `kb/sessions/`。

## X 判定：分类器未经前瞻验证，负向判定全关，C / D / A 只在影子模式

- 记录：2026-07-28（`kb/plans/2026-07-27-x-verdict-style-channels.md` §9、§10.5；`kb/docs/x-verdict.md`）
- 生产只有通道 B 投票（`CONDENSER_VERDICT_CHANNELS=b`），`condenser_verdict_negative_enabled=false`；影子通道 `c,d,a` 只打分归档、不出徽标。2026-07-28 的前瞻样本里 B 的正向徽标 0/2。回测在 60–100 条标注上的数字有选择偏差，不能当证据。
- 通道 C 实际只是 `promo_cta` 检测器：其余 flag 只有 1–3 次观测，正向从没出过手，读者说的「AI 腔」和抽取器的 `ai_slop` 只对齐 1/3。
- 处理方向：标注攒够后跑前瞻回放，按 §9 逐个通道准入负向（见 `kb/next-up.md`）。

## 存储：HN 归档、`link_previews`、被隐藏的 X / RSS 条目只增不删

- 记录：2026-08-07（X 每日清理上线时；`kb/sessions/2026-08-07-x-archive-daily-cleanup.md`）
- `cleanup.py` 只有 X 和 RSS 两条保留规则。HN 约 130 条/天；`link_previews` 只在读的时候判 TTL，行本身从来不删；隐藏条目按用户决定豁免清理，所以一直累积。
- 处理方向：给 HN / `link_previews` 各加一个规则对象，清理循环不用动。

## Telegram：退订时不能连带删除消息；回填批次之间不主动 sleep

- 记录：2026-06-09（`kb/sessions/2026-06-09-backend-remaining-work.md`）
- `DELETE /api/subscriptions/{id}` 只有「保留消息」一种行为，spec Q4 的 `?purge=1` 没做。
- 回填已经分批，也有 FloodWait 退避，但批次之间不 sleep，回填大频道更容易撞限流。

## Telegram：已退出的私有频道，重启后解析不了

- 记录：2026-06-24
- 没有用户名的频道靠 `TgManager._warm_entity_cache` 在启动时遍历 dialogs，重新登记 access_hash。已经不在 dialogs 里的 peer（退出了但本地还有消息的私有频道）重启后 `get_entity(int)` 会失败，媒体和头像代理也跟着失败。
- 处理方向：自己持久化 access_hash / `InputPeerChannel`。

## HN：同一轮放行的条目共用 `qualified_at`，一批里的名次显示乱序

- 记录：2026-08-14（`kb/plans/2026-08-14-hn-story-admission.md` §5.4i）
- 同一轮盖章的条目按 id 打破平局（`pack_pos` 的约定），所以一批里的名次数字不按顺序排。这是有意接受的外观代价，不是 bug。

## X 长文：渲染和覆盖还有五处缺口

- 记录：2026-09-16（`kb/plans/2026-09-16-x-article-full-content.md` §9）
- 表格被 xbird 拆成几行 `| a | b |`，中间隔着空行，GFM 解析不出来。这是 xbird 侧的问题，合并相邻的 MARKDOWN block 就能修。
- 有 article 时拿不到推文自己那句话，因为 xbird 的 `extract_tweet_text` 会短路。
- `inlineStyleRanges` 被忽略，粗体、斜体和行内代码都丢了。
- 引用一篇长文时，quote 卡片看不出它是长文：`sources/x.py` 的联表投影里没有 `q_article`。
- 内联抓取在 2026-09-20 上线，之前被 probe 见过的长文只有预览。服务端不能直连 X，只能靠 `condenser-probe run --no-cache` 补当时窗口里的那些。

## iOS：文章正文的块管线不画小标题样式

- 记录：2026-09-16
- `ArticleBlocks` 只分文本块和图片块，没有标题块类型，h1–h6 按普通文本输出。X 长文和 RSS 全文都受影响。Web 的 `ARTICLE_PROSE` 已经有标题样式。

## iOS：阅读现场恢复只做了主时间线

- 记录：2026-09-07（`kb/plans/2026-09-07-ios-state-restore-new-content-pill.md`）
- 推入的单 feed 视图不存快照，只恢复「进到了哪个 feed」和首页内的锚点。蓝色新内容胶囊不会自己消失，只能点掉。两处都是简化实现。

## iOS：订阅页看不到 RSS 坏源的状态

- 记录：2026-09-16（`kb/plans/2026-09-16-rss-failure-backoff.md`）
- Web 的订阅页有「异常」徽标、错误原文、下次检查时间和 Refresh。API 只加了字段，iOS 没接，在手机上看不出哪些 feed 已经坏了、正在退避。

## iOS 构建：`make build-mac MAC_SIGN=adhoc` 过不了 provisioning 检查

- 记录：2026-09-16
- Makefile 注释推荐的「只想编译」入口在编译开始前就失败。当时用 `CODE_SIGNING_ALLOWED=NO` 绕过去，只验证了能编译。

## Purifier：code review 截掉的两条 PLAUSIBLE 和清理项还没处理

- 记录：2026-09-08（`kb/reviews/2026-09-07-purifier-code-review.md`「截掉的 PLAUSIBLE」「清理类」）
- CSS 里的 `[src=…]` 选择器按样式表自己的 URL 改写，而不是页面的 URL。样式表和页面不在同一目录时会失配，HN 不受影响。
- iOS 票据的过期时间按收到时算，没有 cookie 的第一次打开有一个 RTT 宽的窗口。
- 清理类：`PuremdUnavailable` 没有用处，`mode_override` 重复，content-type 有一次到不了的复检，`_render_puremd` 的解析和渲染跑在事件循环上，charset / sign 辅助函数有重复。

## Purifier：生产的 pure.md 兜底可能没开

- 记录：2026-09-07（`kb/plans/2026-09-07-purifier.md`）
- 没配 `CONDENSER_PUREMD_API_KEY` 时，readable 抽取失败就没有兜底可走。落地时生产 `.env` 还没加这把 key，之后有没有加没核实过。
- 处理方向：用 envops 查生产 `.env`，再决定要不要配。改 `.env` 后要重建容器才生效。

## 未验收：iOS 标注的三段手势没在真机上走过

- 记录：2026-08-24（`kb/plans/2026-08-24-annotations.md`）
- 「选中 → 高亮」「点高亮弹菜单」「条目评论抽屉」这三段模拟器自动化不了，还需要在真机上手动走一遍。

## 未验收：Purifier 没在真机上用过

- 记录：2026-09-07（`kb/plans/2026-09-07-purifier.md`）
- 模拟器和 Mac Catalyst 上走通了，真机和弱网是这个功能要服务的场景，但还没验证。

## 未验收：Vibe Reader Phase D 的状态角标没和真实扩展联调

- 记录：2026-09-05（`kb/plans/2026-09-02-vibe-reader-link-mode-and-hn-summary.md` §5）
- 前端按扩展走查时确认的消息序列（`extracting → generating{modes} → done`）写死在测试里，只在 `preview.html` 里用 postMessage 模拟过。

## 未验收：转发记录没用一次真实转发验证

- 记录：2026-08-23（`kb/plans/2026-08-23-forward-records.md`）
- 真转一条会往 `@reorx_share` 发消息，所以留给用户自己来。写入路径只有后端测试覆盖。验证方法：真转一条，看 `/forwards` 里有没有这条记录，包括评论和当时的目标频道。
