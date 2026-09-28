# Next up

> 接下来要做的事，按时间排。做完一项就删掉，结果记到条目指定的 kb 文档，这里不留记录。

## 已到期

- **HN 关账后补票的效果复查**：补票在 2026-09-04 随 CI 上线，到现在已超过两周。先从生产导出 `hn_stories`（只读），用 `tmp/2026-09-03-hn-vs-hckrnews/fetch_hck.py` 补抓新的 hckrnews 日数据，再把 `compare.py` 的 `LIVE_FROM` 改成 `2026-09-05` 重跑。预期 Top 20 召回 ≥97%，每天放行 21–22 条。脚本只在本机的 `tmp/` 里。
  → 记到 `kb/plans/2026-09-03-hn-day-close-top-up.md`
- **Purifier X 的生产连通性**：`purifier_x.py` 在 2026-09-20 上线，生产主机能不能连到 `api.fxtwitter.com`（计划风险 1）当时说好上线后实测，还没做。在生产打开一条 `/p/x.com/<user>/status/<id>`，应该渲染出讨论页。如果被拦，把 `CONDENSER_PURIFIER_X_API_BASE` 置空，`/p` 会 302 回原链接。
  → 记到 `kb/plans/2026-09-17-purifier-x-fxembed.md` §8

## For You 标注攒到约 150 条之后（2026-07-29 是 104 条，现在多半已经够了，先数一下）

- **判定通道的负向准入复查**：在**生产库的拷贝**上跑 `scripts/x_verdict_prospective.py --shadow a --sweep`，C、D 也各跑一遍。只看判定在标注之前的样本，对照计划 §9 的门槛：精确率 ≥85%、≥15 次出手、高于基线、没有冤枉收藏过的条目。A 通过的话，再考虑 `CONDENSER_VERDICT_CHANNELS: b,a` + `CONDENSER_VERDICT_A_NEGATIVE_ENABLED`。这两个变量在 ansible role 模板里，改完要跑 ansible，push 不会生效。改生产配置前先问用户。
  → 记到 `kb/docs/x-verdict.md`，计划 `kb/plans/2026-07-27-x-verdict-style-channels.md` 追加一节
