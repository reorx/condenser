# 2026-09-07 · Purifier 代码审查（/code-review medium feat/purifier）

审查对象：`feat/purifier` 分支（已于 2026-09-07 `--no-ff` 合并进 master，merge commit
`780a043`，**未 push**）。11 条候选各过一轮独立验证，7 条 CONFIRMED、1 条 PLAUSIBLE，
三条 PLAUSIBLE 被 8 条上限截掉，清理类发现被正确性发现挤出。行号按分支当时的文件。

**处理状态（2026-09-08）：1–8 全部已修**，每条末尾有「处理」一段；后端 862 → 880 例、
前端 288 → 291 例、Kit 322 例全绿，`make build` 通过。截掉的 PLAUSIBLE 与清理类未动。

## CONFIRMED

### 1. `javascript:` 只剥了 `href` — `condenser/purifier.py:399`

`action`、`formaction`、SVG 的 `xlink:href` 原样穿过 sanitizer，代理页可以在 condenser
域名下执行脚本（`allow_js=False` 时不发 CSP）。

复现（已验证）：上游 HTML
`<form action="javascript:alert(1)"><button formaction="javascript:alert(2)">go</button></form><svg><a xlink:href="javascript:alert(3)"><text>y</text></a></svg>`
经 `sanitize_and_rewrite_proxy(allow_js=False)` 逐字节不变。原因：`action` 进了
`rewrite_url`，其 `if parts.scheme not in ('http','https') ... return href` 把值原样退回；
`formaction` 在 `_clean_attributes` 里不命中任何分支；lxml 保留字面名 `xlink:href`，
`lname == 'href'` 永不成立。点一下就在 condenser.reorx.com 上跑 JS——拿 reader cookie
能驱动 `/p/*`，桌面浏览器上持有 `condenser_session` 时能打 `/api/*`。

修法：把 `javascript:`（以及所有非 http(s) scheme）的丢弃规则同样施加于
`action` / `formaction` / `*:href`，或让 `rewrite_url` 对非 http(s) 值**丢弃**而非返回。

**处理（2026-09-08）：已修。** `_clean_attributes` 先对 `_URL_ATTRS`（href / src / action /
formaction / poster / background / cite / longdesc / data，按冒号后的本地名匹配所以 `xlink:href`
也算）做 scheme 检查：`javascript:` / `vbscript:` 一律删属性，导航类（href / action / formaction）
再加 `data:`；比较前先剥 ASCII 控制字符与空白（`java\tscript:` 与浏览器同样处理）。
`formaction` 与 `action` 同样改写进 `/p`，SVG `<image xlink:href>` 进 `/pa`。
测试 `test_proxy_strips_script_schemes_from_every_url_attribute`。

### 2. `/pa` 原样返回 `image/svg+xml`，无 CSP — `condenser/routers/purifier.py:132`

`asset_type_allowed` 接受任何 `image/*`；`render_asset` 把 `AssetResult(raw, mime)` 原样返回；
`purified_asset` 不设 `Content-Security-Policy: sandbox` / `script-src 'none'`、
不设 `X-Content-Type-Options`、不设 `Content-Disposition`。页面里一个
`<link rel=icon href=x.svg>`，或任何人分享 `https://condenser.reorx.com/pa/evil.example/x.svg`，
顶层打开就让 `<svg><script>fetch('/api/…')</script></svg>` 带 cookie 在本域执行。
`GET /api/preview/image?url=` 形状相同但在 `require_auth` 后面；`/pa` 是链接驱动、只要
较弱的 reader cookie 就能到。

修法：`/pa`（顺手也给 preview image proxy）加
`Content-Security-Policy: sandbox; script-src 'none'` + `X-Content-Type-Options: nosniff`，
或直接拒绝 `image/svg+xml`。

**处理（2026-09-08）：已修。** `routers/purifier.py` 的 `ASSET_HEADERS`（`sandbox; script-src
'none'` + `nosniff`）加在每个 `/pa` 响应上，`routers/preview.py` 的 `/api/preview/image` 共用。
没有拒绝 SVG——站点 logo 常是 SVG。测试 `test_asset_responses_are_sandboxed` /
`test_image_proxy_sandboxes_svg`。

### 3. `host_allowed` 放过非规范 loopback 拼写 — `condenser/purifier.py:174`

`host_allowed('127.1')`、`'0x7f.1'`、`'localhost.'`、`'127.0.0.1.'` 全返回 True
（都含点；`ipaddress.ip_address` 不认简写；`name == 'localhost'` 漏了尾点）。
`socket.getaddrinfo` 把前三个解析到 127.0.0.1，`httpx.get('http://127.1:1/')` 抛的是
`ConnectError: Connection refused` 而非 `InvalidURL`——所以 `GET /p/127.1:3459/api/health`
会让服务器抓自己（https 连接失败触发 `fetch_page` 的 http 重试）。

修法（保持五行的体量）：先 `name = name.rstrip('.')`，再拒绝所有 label 都是数字 / 十六进制
的 host；或走 `getaddrinfo` 解析后拒绝 loopback / 私网结果。

**处理（2026-09-08）：已修，取前一种。** `host_allowed` 先 `rstrip('.')`，再用
`_is_numeric_name`（每个 label 都匹配 `^(0x[0-9a-f]*|[0-9]+)$`）拒绝；`1password.com` /
`123.example` 这类含非数字 label 的仍放行。没走 `getaddrinfo`：解析到私网的 DNS 名照旧放行，
与 `preview.py` 同一姿态（单用户、已鉴权）。测试 `test_host_allowed_rejects_non_canonical_loopback_spellings`。

### 4. proxy 模式的 lxml 异常没被错误页边界接住 — `condenser/purifier.py:445`

`sanitize_and_rewrite_proxy('<?xml version="1.0" encoding="utf-8"?><html>…')` 抛
`ValueError: Unicode strings with encoding declaration are not supported`；`''` 抛
`ParserError: Document is empty`。两者既不是 `PurifierError` 也不是 `httpx.HTTPError`，
`_render_proxy` 没有 try/except，`purified_document` 只接
`(purifier.PurifierError, httpx.HTTPError)`。现实路径：readable 在 XHTML / 空页上失败 →
错误页给「试试整页模式 →」（`?_mode=proxy`）→ 点 → SFSafariViewController 里一个裸
`Internal Server Error`，连原链接都没有。readable 模式被它的宽 except 挡住了，proxy 模式
需要同样的映射。两种输入在 proxy 模式下都没有测试。

修法：`_render_proxy` 里接 `(ValueError, lxml.etree.ParserError)` → `UpstreamFetchError`
之类，并在 `document_fromstring` 前剥掉开头的 `<?xml …?>`。

**处理（2026-09-08）：已修，两件都做。** `sanitize_and_rewrite_proxy` 用锚定开头的正则剥
`<?xml …?>`（XHTML 页因此直接能渲染，不再报错）；`_render_proxy` 接 `(ValueError, etree.LxmlError)`
→ `UpstreamFetchError('could not parse page: …')`，router 的 502 页照常带原链接。测试
`test_render_proxy_mode_maps_parser_failures_to_purifier_errors` /
`test_proxy_mode_parser_failure_is_502_html_with_original_link`。

### 5. PWA service worker 吞掉 `/p/…` 导航 — `frontend/vite.config.ts:26`

构建出的 `dist/sw.js`：`NavigationRoute(createHandlerBoundToURL("index.html"), {denylist:[/^\/api\//]})`，
SW scope `/`。`ExternalLink.swift` 的 Mac Catalyst 分支（`if Platform.isMac { app.open(purified) }`）
把 `/p/news.ycombinator.com/item?id=1&_pt=…` 交给系统浏览器——正是开过 SPA、装了 SW 的
地方——workbox 对这个未知路由返回 SPA shell，票据交换根本到不了后端。桌面浏览器里打开
任何 /p 链接同理。`/pa` 子资源请求不受影响（不是 `mode: navigate`）。

修法：`navigateFallbackDenylist: [/^\/api\//, /^\/pa?\//]`。注意已装的 SW 在接受更新提示
前仍用旧 denylist。

**处理（2026-09-08）：已修。** denylist 抽到 `frontend/src/lib/swDenylist.ts`
（`[/^\/api\//, /^\/pa?(\/|$)/]`，裸 `/p/host` 也算），`vite.config.ts` 与 `swDenylist.test.ts`
同一来源；`pnpm build` 后 `dist/sw.js` 里 `denylist:[/^\/api\//,/^\/pa?(\/|$)/]` 已确认。
已装 SW 要等用户接受更新提示才换，这点没法绕。

### 6. reader cookie 签常量、不绑设备、没有吊销路径 — `condenser/crypto.py:72`

`reader_authenticated` 只验签名 + 年龄，从不查 `devices`；`POST /api/auth/logout` 只删
`COOKIE_NAME`（`routers/auth.py` 没 import `READER_COOKIE_NAME`）；
`AuthSession.signOut → Purifier.reset()` 只清内存里的票，cookie 活在共享的 Safari store
里。所以用户在 web 设备页吊销一台手机（项目唯一的吊销路径）后，那台手机仍握着一个
30 天有效的认证抓取代理，烧 pure.md 额度直到 cookie 老化——唯一的杀招是换
`CONDENSER_SECRET_KEY`，那会连加密的 Telegram 会话一起毁掉。plan §2 写了 salt 与 cookie
flag，从没写吊销与票据重放；`sign_purifier_ticket` 也签常量，所以从 access log 或 302 前
URL 里抄到的任何 `_pt` 在 300s 内都能换一张新 cookie，与文档的「一次性」不符。

修法（便宜）：把 `device_id` 签进票据与 cookie，`reader_authenticated` 检查
`db.get_device(id)` 仍存在；logout 加 `delete_cookie(READER_COOKIE_NAME)`；文档
「one-shot」改成「short-lived」。

**处理（2026-09-08）：已修，取便宜修法。** `sign_purifier_ticket` / `sign_reader_cookie` 都签
`device_id`，`verify_*` 返回 `Optional[int]`；新增 `db.get_device(id)`；ticket 端点改
`require_device`（只认 Bearer——web 会话本来就用自己的 cookie 开 `/p`，cookie 会话请求票据得
401）；换票与 `reader_authenticated` 都查设备仍在；`/api/auth/logout` 删 reader cookie。
iOS 侧契约不变（票据仍是不透明串），只改注释；Kit 322 例、`make build` 通过。文档
「one-shot」→「short-lived」（crypto / router docstring、plan §2、CLAUDE.md、ios.md）。测试
`test_revoking_the_device_kills_its_reader_cookie` / `test_logout_clears_the_reader_cookie_too` /
`test_forged_expired_or_orphaned_ticket_is_401` / `test_ticket_endpoint_requires_a_device_and_binds_the_ticket_to_it`。

### 7. IDN host 原样进 `/p/<host>`，上游抓取 502 — `condenser/purifier.py:229`

`rewrite_url('https://例え.jp/x', …)` → `/p/例え.jp/x`；Safari 请求
`/p/%E4%BE%8B%E3%81%88.jp/x`；`split_raw_path`（刻意不解码）+ `parse_target` 得到
`Target.url == 'https://%e4%be%8b%e3%81%88.jp/x'`，`host_allowed` 放行，
`httpx.URL(...).raw_host == b'%e4%be%8b%e3%81%88.jp'`（httpx 不解码也不 IDNA 编码百分号
host）→ DNS 失败 → http 重试同样失败 → 错误页。`PurifierLink.swift` 用同样方式插入
`comps.host`。少见，但正好是 `detect_charset` 为之而加的 CJK 人群。

修法：`parse_target` 里对 host 段 `unquote`（httpx 随后会正确 IDNA 编码），或
`rewrite_url` 里输出 `netloc.encode('idna')`。

**处理（2026-09-08）：已修，取前一种。** `parse_target` 对 host 段 `unquote`，随后拒绝含
`/ \\ ? # % @` 或控制字符的 host（否则 `a%2Fb.example` 解码后会把 `b.example` 推进路径、让
裸名 `a` 绕过 `host_allowed`）。`httpx.URL('https://例え.jp/x').raw_host == b'xn--r8jz45g.jp'`
在测试里 pin 住。测试 `test_idn_hosts_round_trip_through_the_proxy_path` /
`test_idn_host_is_fetched_as_unicode_url`。

## PLAUSIBLE

### 8. 全局 `GZipMiddleware` 把二进制代理响应也压了一遍 — `condenser/app.py:95`

默认 compresslevel 9，Starlette 1.2.1 只排除 `text/event-stream`，于是 `/api/media` 流式
分块、`/api/preview/image`、两个头像代理、`/pa` 图片都在单事件循环上同步 gzip，体积零
收益。实测 3MB `image/jpeg` + `Accept-Encoding: gzip`：42ms vs 无中间件 8ms
（约 14ms/MB 的循环 CPU，输出还大约 1KB）。iOS 每次滚缩略图都在 Telethon ingest 共用的
循环上乘这个数。「破坏 Safari seek」的另一半被否定：`StreamingResponse` 从没带过
Content-Length。

修法：包一层 / 子类化 `GZipMiddleware` 跳过 `image/*`、`video/*`、`audio/*`、`font/*`
（或在二进制代理响应上设 `Content-Encoding: identity`），HTML 考虑 `compresslevel=6`。

**处理（2026-09-08）：已修。** `app.py` 的 `SelectiveGZipMiddleware`：子类化 Starlette 的
`GZipMiddleware` + `GZipResponder`，在 `http.response.start` 后按 content-type
（`image/* video/* audio/* font/*` + 字体 / zip / gzip / pdf / octet-stream）把
`content_type_is_excluded` 置真，走 identity；`compresslevel=6`。测试
`test_binary_responses_are_not_gzipped`（image/png、svg、woff2 不压，text/css 仍压）。

## 截掉的 PLAUSIBLE（供参考）

- CSS 属性选择器改写按样式表自身 URL 解析而不是页面 URL——只在样式表与页面不同目录时失配
  （HN 安全，没找到会坏的站）。
- `forward.py` 产出的 `fixupx.com` 推文链接现在会被代理而不是在 Safari 里打开——取决于
  用户是否订阅了自己的转发频道。
- iOS 票据过期按收到时间算——无 cookie 的首次打开有一个 RTT 宽的窗口。

## 清理类（被挤出，未验证）

未使用的 `PuremdUnavailable`、重复的 `mode_override`、不可达的 content-type 复检、
`_render_puremd` 没在 worker 线程上、重复的 charset / sign 辅助函数。
