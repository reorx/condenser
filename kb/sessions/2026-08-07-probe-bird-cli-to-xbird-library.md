---
created: 2026-08-07
tags:
  - x-source
  - probe
  - xbird
  - dependency-management
  - uv
  - production-verification
---

# probe 从 bird CLI 换成 xbird 库：形状不变、语义翻转、上游易主

## 概要

probe 读 X 的方式一直是 `subprocess` 调 `@steipete/bird` CLI 再解析 stdout。用户自己写了
[xbird](https://github.com/reorx/xbird)（bird v0.8.1 的忠实 Python 重写，CLI + 库双形态），
这个 session 把 probe 换成 `import xbird` 直接用库。

替换面比预期小得多：**所有 bird 调用都集中在 `probe/condenser_probe/bird.py` 一个文件（97 行）**，
而 `runner.py` 早就把 `fetch` / `fetch_following` 做成了可注入参数，测试全部打桩。所以
runner / cache / client / scheduler 的逻辑一行没动，新模块 `xsource.py` 顶替 `bird.py` 即可。

五个调用点的映射：`home` → `get_home_timeline`、`--following` → `get_home_latest_timeline`、
`user-tweets` → `get_user_id_by_username` + `get_user_tweets_paged`、`following --all` →
`get_current_user` + 分页 `get_following` 循环、`whoami` → `get_current_user`。后两条各多一次
HTTP 请求（拿 user_id），但 CLI 内部本来就是这么做的，总请求数不变。

**四件事刻意保持不变**，每一件都有具体理由（见「注意事项」）：推送的 JSON 形状、逐 feed
的失败隔离、关注列表的全有或全无、翻页之间的 1 秒限速。

验收走的是最硬的路径：用新代码抓真实数据，再喂给**服务端自己的 parser**——三种 feed kind
共 25 条真实推文过 `condenser.x.parse_tweet`，**0 条无法入键、0 warning**，关注列表 100/100
成功入键。随后对生产跑了一轮真实 push（两条 feed 各 0 parse errors），并重启了 launchd
agent，迁移已在生产生效。

## 修改的文件

**probe（核心改动）**

| 文件 | 改了什么 |
|---|---|
| `probe/condenser_probe/xsource.py` | **新建**，顶替 `bird.py`。`XSourceError` + `fetch_feed` / `fetch_following_users` / `check_auth`；client 每次调用新建并关闭 |
| `probe/condenser_probe/bird.py` | **删除** |
| `probe/condenser_probe/runner.py` | import 换成 `xsource`；`bird_bin` / `timeout` 参数换成 `timeout_ms`；`BirdError` → `XSourceError`，隔离逻辑不变 |
| `probe/condenser_probe/config.py` | 去掉 `bird_bin`，新增 `x_timeout_ms`（默认 20000，每个 X API 请求）；`timeout` 收窄为「每个 condenser HTTP 请求」 |
| `probe/condenser_probe/__main__.py` | `check` 改用 `xsource.check_auth`；`--no-cache` 帮助文案去 bird 化 |
| `probe/condenser_probe/__init__.py` / `cache.py` / `scheduler.py` | docstring 里描述当前机制的 bird 措辞更正（历史测量记录保留） |
| `probe/pyproject.toml` | `requires-python` 抬到 `>=3.11`（xbird 要求）；加 `xbird>=1.0.0` + `[tool.uv.sources]` git 源 |
| `probe/uv.lock` | 锁定 xbird commit `7cff6cf`，新增传递依赖 click / cryptography / pydantic / pyjson5 |
| `probe/README.md` | 安装章节重写（不再需要装 CLI）、凭据说明、配置项、本地联调 overlay 章节、测试文件分工 |
| `probe/com.condenser.probe.plist.example` | PATH 注释更正：不再是「node/bird」，而是 `/usr/bin` 下的 `security`（解密 Chrome cookie 用） |

**测试**

| 文件 | 改了什么 |
|---|---|
| `probe/tests/test_xsource.py` | **新建**，17 条适配器行为测试（feed kind 映射、返回值型失败、wire shape、关注列表分页/全有或全无/页数上限） |
| `probe/tests/test_probe.py` | 删掉 7 条命令行拼装测试（已被上面取代），`BirdError` → `XSourceError`，config 测试改测 `x_timeout_ms` |
| `probe/tests/test_scheduler.py` | 注释措辞 |

**文档**

- `AGENTS.md` — probe 章节新增迁移说明段落；`x.py` 表格行、schema v11 段落、`raw` 描述等
  **描述当前机制**的 bird 引用更正（dated 的历史段落一律不动）

**未改动**：服务端一行没动（435 tests 仍全绿），Dockerfile 无关（probe 不在镜像里）。

## 注意事项

### 换库时最该守住的是「wire shape」，不是代码

服务端把每条 entry **原样存进 `x_tweets.raw`**，并按 camelCase key 解析。所以推给服务端的
不是 pydantic 模型，而是 `xbird.types.to_json(tweet)`——和 `xbird … --json` CLI 打印的是同
一个 dict。改成 pydantic 原生 snake_case 会**孤立所有历史行**，且 `quote_of` /
`author_handle` / 判定通道 A 全部受影响。

这条在 `xsource.py` 的模块 docstring 里写死了，因为它是「和归档共享的契约」，不是实现细节。

**验收方式值得复用**：不要自己写断言比对字段，直接**用服务端自己的 parser 跑真实数据**
（`tmp/2026-08-06-xbird-migration/verify_parse.py`），报 0 unkeyable + 0 warning 才算过。

### 「错误是返回值」的库，接进「错误是异常」的调用方时最危险

xbird 的库 API 从不为远程失败抛异常，返回 tagged union（`result.success` / `result.error`）。
如果直接 `return result.tweets`，一次 401 会读作**空 feed**——`runner` 会把这轮报成 ok，
一个失效的 X 会话可以就此永远藏下去。所以 `xsource` 把每一个 `success=False` 都抛成
`XSourceError`，恢复 CLI 非零退出码原本给出的信号，`runner` 的逐 feed 隔离一字不用改。

（唯一会抛的是 `iter_*` 的 `PaginationError`，本次没用到那些生成器。）

### 关注列表必须全有或全无

服务端是**整表替换**，且会把不在列表里的作者的推文当广告丢弃。所以推半份列表比不推更糟：
缺失的账号会被静默当成广告。`fetch_following_users` 中途失败直接抛，不返回已收集的部分——
服务端那份旧列表还能继续工作到下一轮。这也是没用 `iter_following` 的原因之一。

### 没用 `iter_following` 的另一个原因：限速

CLI 的 `--all` 在翻页之间 sleep 1 秒，而 `iter_following` 不暴露 `page_delay_ms`。X 对自动化
阅读比 Telegram 严格得多，而关注列表爬取是 probe 唯一一处**突发请求**（~15 次）。去掉限速
等于悄悄改变了对 X 的请求强度，所以手写了一个 15 行的分页循环把 1 秒保留下来。

### uv 没有「开发用 path、构建锁 git」的一等公民开关

实测结论（uv 0.9.17）：

- `uv.toml` **不支持** `[sources]`，直接报错「sources is only applicable in the context of a project」
- 带 PEP 508 `marker` 的多源**可行**，两条分支都会进 lock（git 那条带精确 commit）——但这
  把「开发 vs 构建」错位编码成了「操作系统」
- `--no-sources` 要求包在 index 上，xbird 不在 PyPI，走不通

最终选了仓库**已有的 telememo 模式**：pyproject 锁 git，本地用 editable overlay 覆盖
（`uv pip install -e ../../xbird` + `export UV_NO_SYNC=1`，`uv sync` 解除）。好处是 lock 只
有一种形态、不会来回摆。

### 私有仓库 git 依赖 + launchd：先测 SSH

xbird 是私有仓库，依赖 URL 必须走 SSH（`ssh://git@github.com/reorx/xbird`）。而 launchd
的环境里**没有 `SSH_AUTH_SOCK`**——如果密钥需要 passphrase 且依赖 ssh-agent，`uv sync` 会
在后台静默失败，probe 再也起不来。

上线前用 `env -u SSH_AUTH_SOCK git ls-remote` 和 `env -u SSH_AUTH_SOCK uv run` 实测过，
冷热路径都通。**这类风险不要推理，要实测**。

### 一个顺带的观察

launchd 下 Safari cookie 读不到（日志里 `grant Full Disk Access`），自动 fallback 到 Chrome
成功——这是 xbird 设计的降级链在工作。但如果哪天 Chrome 也失效，那两行 warning 就是唯一
线索。

## 遗留问题

- **`kb/plans/2026-07-30-x-expanded-urls.md` 的阻塞性质变了，plan 文本未更新。** 该 plan §0
  写着「依赖上游:bird 需要先在简化 JSON 里输出 `urls`，在 bird 发布该功能之前本 plan 不可
  开工」。现在上游是自己的仓库了，不再需要等别人；但 xbird 是 v0.8.1 的忠实移植，同样还没
  有 `urls` 字段，所以仍需**先改 xbird**。本次没有动那个 plan 文件，改不改待定。
- **xbird master 上有 1.0.0 之后的未发布改动**（CHANGELOG `[Unreleased]`：刷新了 13 个轮换过
  的 query id、修了 `lists`）。当前锁的是 master 的 `7cff6cf`，拿到了这些修复；但 xbird 至今
  **没有任何 git tag**，所以升级只能靠 `uv lock --upgrade-package xbird`。若日后想按 tag 钉，
  需要先在 xbird 仓库补打 tag。
- **probe 的 seen cache 让推文的互动数冻结在首次抓取时刻**（plan decision 2 的既有取舍，本次
  未触及）。on-demand 刷新仍是 follow-up。

## 相关文档

- [X 源本地 probe 开发计划](../plans/2026-07-24-x-source-local-probe.md) — probe 的起源计划，本次替换了它的 fetch 半边
- [X Following 时间线计划](../plans/2026-07-30-x-following-feed.md) — 关注列表爬取与广告过滤的由来，本次保持其全有或全无语义
- [X 推文短链展开计划](../plans/2026-07-30-x-expanded-urls.md) — 其上游阻塞因本次换库而性质改变（见「遗留问题」）
- [bird expanded URLs feature request](../notes/2026-07-30-bird-expanded-urls-feature-request.md) — 上述阻塞的背景笔记
