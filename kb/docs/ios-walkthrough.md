---
created: 2026-11-15
tags:
  - ios
  - mac-catalyst
  - simulator
  - walkthrough
---

# iOS / Mac Catalyst 走查手册

怎么不点一下屏幕就把 app 带到某个界面并截图，以及走查时踩过的坑。2026-11-15 从
`ios/AGENTS.md` 拆出，命令与工程约定仍在那边，功能设计在 `kb/docs/ios.md`。
机型约定：模拟器一律用 `iPhone 17`（Makefile 的 `SIM`），只有商店截图例外。

## 直连本地后端（跳过授权）

验证真实数据的界面时不必走交互式授权：

1. 起本地后端。dev DB 在 `tmp/condenser.db`，有真实消息数据：
   `CONDENSER_DB_PATH=tmp/condenser.db uv run uvicorn condenser.app:create_app --factory --port 8792`
2. `devices` 表里要有调试 token 的 sha256。dev DB 里已有 `iOS Simulator (dev)` 一行，
   token 明文 `devtoken-ios-sim`；换新库时自己插一行。
3. 带 debug 环境变量启动 app。这是 `AuthSession` 的 `#if DEBUG` 注入口，只在内存里，
   不落 Keychain：
   `SIMCTL_CHILD_CONDENSER_DEBUG_SERVER=http://localhost:8792 SIMCTL_CHILD_CONDENSER_DEBUG_TOKEN=devtoken-ios-sim xcrun simctl launch "iPhone 17" com.reorx.condenser`

Info.plist 已配 `NSAllowsLocalNetworking`，`http://localhost` 放行。
截图：`xcrun simctl io booted screenshot <path>.png`。

Mac 上直接跑二进制（`open` 不传环境变量），变量名不带 `SIMCTL_CHILD_` 前缀：

```bash
CONDENSER_DEBUG_SERVER=… CONDENSER_DEBUG_TOKEN=… CONDENSER_DEBUG_ROUTE=… \
  .build/DerivedData/Build/Products/Debug-maccatalyst/Condenser.app/Contents/MacOS/Condenser
```

## Debug 环境变量

全部仅 DEBUG 构建生效。模拟器上加 `SIMCTL_CHILD_` 前缀。

| 变量 | 作用 |
|---|---|
| `CONDENSER_DEBUG_SERVER` + `CONDENSER_DEBUG_TOKEN` | 直连指定后端，跳过授权 |
| `CONDENSER_DEBUG_ROUTE=<route>` | 启动后导航到指定界面，路由表见下 |
| `CONDENSER_DEBUG_SHARE=1` | 配合 `detail/…` 路由，抽屉一出现就自动按「分享图片」。产物在 app 容器的 `tmp/`（`xcrun simctl get_app_container booted com.reorx.condenser data`） |
| `CONDENSER_DEBUG_FOCUS_GAP=<秒>` | 缩短 Mac 窗口 focus 检查新内容的间隔（缺省 10 分钟） |
| `CONDENSER_DEBUG_LOGIN=1` | 只在内存里展示登录页，不清 Keychain |

## Debug 路由表

实现在 `MainView.handleDebugURL`。模拟器窗口收不到合成手势（`System Events` 拿不到它的
window，`cliclick` 也就无从下手），不在当前 Space 时更点不到，所以用启动环境变量直接导航：

```bash
SIMCTL_CHILD_CONDENSER_DEBUG_ROUTE=<route> xcrun simctl launch "iPhone 17" com.reorx.condenser
```

每换一个界面 terminate 再 launch 一次。路由等 timeline 首屏加载完才应用（最多 10 秒）。

| route | 效果 |
|---|---|
| `tab/{timeline\|subs\|saved}` | 切 tab。`channels` 是订阅 tab 的旧别名 |
| `tab/subs/<source>` | 进订阅 tab 并滚到该信源分组。订阅列表已经长到一屏放不下 |
| `settings` | 切设置 tab |
| `channel/<id>` | push 单频道 timeline |
| `hn` | push HN feed timeline |
| `x[/<feed>]` | push 某个 X feed，缺省第一条 X 订阅 |
| `rss[/<第几个订阅>]` | push 某个 RSS feed。**用下标不是 key**：这个源的 feed key 是整个 URL，塞不进路径段 |
| `detail/<cid>/<mid>` | 弹 Telegram 消息详情。消息须在 timeline 首页内 |
| `viewer/<cid>/<mid>` | 全屏图片浏览器，同样要求消息在首页内 |
| `detail/x/<feed>[/<tweet id>]` | 弹推文详情，单独走一次网络查，条目不必在聚合流里。省略 id 时挑该 feed 第一条有判定的，判定证据是这个界面最值得看的部分 |
| `detail/hn[/<story id>]` | 弹 story 详情。省略 id 时挑第一条 self-post，自文正文和预览卡是这个界面最值得看的部分 |
| `detail/rss[/<条目 id>]` | 弹条目详情，单独查并且**翻页**（最多 8 页）：归档按时间倒序，值得看的怪例（中文长文、缺字段的）都排在两百多位。省略 id 时挑第一条有正文的 |
| `forward/<item key>[/<comment>]` | 直接弹转发 dialog，只用 key，条目不必在首页内。例：`forward/tg:-1001:123`、`forward/hn:44123`、`forward/x:2080…` |

- Mac 上 `detail/…` 一律进右侧详情栏，不弹 sheet。
- ⚠️ `forward/…` 带第 3 段则 1 秒后自动提交，**真实转发落地目标频道**。`-` 表示不带评论，
  中文评论要 percent-encode。
- `detail/x/foryou/<id>` 在聚合流为空的库上要等满 10 秒才生效，截图别早于 15 秒左右。
- 也支持 `xcrun simctl openurl booted "condenser://debug/<route>"`，但系统会弹
  "Open in Condenser?" 确认框，而且这个框跨 app 重启存活，误触发后要
  `simctl shutdown && boot` 才能清掉。无人值守走查一律用环境变量形式。

## 模拟器走查的坑

- 用 cliclick 点模拟器里的东西（比如蓝色胶囊）时，坐标要按 `screencapture -R` 的**窗口**
  截图换算。窗口有标题栏和机身边框，按 simctl 截图等比缩放会偏约 60pt，点到导航栏上。
- 别的会话的 Chrome 会抢前台。点之前先 `activate` 并确认 frontmost 是 Simulator。
- X 深链（`twitter://`）有没有真的落进 X app 只能在装了 X 的真机上验（`make device`）。
  模拟器没有 X app，走的永远是回落分支。
- 改了返回 `some View` 的函数、底层类型变了之后，走查前先 `make clean`
  （原因见 `ios/AGENTS.md`「命令」）。

## Mac Catalyst 走查

先读 `~/.claude/docs/DESKTOP_APP_TESTING.md`。这个 app 自己踩过的：

1. 退出用 `osascript -e 'tell application id "com.reorx.condenser" to quit'`，**不要 pkill**。
   SIGTERM 被记成异常退出，下次启动先弹模态的「quit unexpectedly」把窗口挡住。
   `make run-mac` 已经这样做。
2. 别留第二份 DerivedData 里的 Condenser.app。`tell application id … to activate` 会被
   LaunchServices 解析到旧那份并把它启动起来，跑的是老代码。
3. 截图前先把窗口拉到前台。`screencapture -R` 截的是屏幕区域，被终端盖住截到的就是终端。
4. `tell app to activate` 不一定抢得到前台（Sequoia 起限制），要
   `tell application "System Events" to set frontmost of process "Condenser" to true`。
5. 自己 post 的 CGEvent 点击点不动 SwiftUI 工具栏按钮（列表行、普通按钮都能点），
   `tell application "System Events" to click at {x, y}` 才行。
6. 开着详情抽屉的实例 AppleScript quit 会报「User canceled」，而且**同 bundle 的第二个实例
   起不来**，看起来像新构建没生效。先 `key code 53`（Esc）关抽屉再 quit。
7. quit 和 ⌘Q 都没反应时先看 `%cpu`。吃满一个核多半是布局死循环（详情栏宽度的坑，见
   `kb/docs/ios.md`「Mac Catalyst」的「工程细节」），只能 `kill -9`。
8. Mac 版是沙盒 app，`defaults write` 要写进
   `~/Library/Containers/com.reorx.condenser/Data/Library/Preferences/` 里的 plist，写到
   外面开关不生效（Purifier 开关 `condenser.purifier`、侧栏 `condenser.mac.sidebarHidden`）。
9. 换签名后首次启动 macOS 会问「differs from previously opened versions」，点 Open Anyway 一次。

截图脚本的旧例子在 `tmp/2026-09-04-mac-catalyst/`（`tmp/` 不入库，可能已归档）。

## 商店截图的造法

不碰生产数据、不需要任何账号，因为临时后端**只开 HN 源**就能填满界面（公开数据，
一分钟内 200+ 条，含 hckrnews 历史回填）：

1. 临时后端指向全新 DB：`CONDENSER_DB_PATH=tmp/<date>-appstore-shots/condenser.db uv run
   uvicorn condenser.app:create_app --factory --port 8793`。
2. 往 `devices` 表插调试 token 的 sha256，再
   `POST /api/sources/hn/subscriptions {"channel_id":"front"}`。订阅即 kick 一轮采样。
3. 6.9" 模拟器（iPhone 17 Pro Max）。本机默认没有，先
   `xcrun simctl create "iPhone 17 Pro Max" com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max`，
   闲置 7 天后 `mac-dev-cleanup` 会自动删掉。装 Debug 构建，盖状态栏，用
   `SIMCTL_CHILD_CONDENSER_DEBUG_ROUTE` 逐屏截图，`simctl ui <udid> appearance dark` 出深色版。
4. `asc screenshots sizes` 说 iPhone 只有 **`APP_IPHONE_65`**（1284×2778）必填。6.9" 出图是
   1320×2868，`sips -z 2789 1284` 等比放大后 `sips -c 2778 1284` 居中裁。上传用
   `--version-localization <版本本地化资源 id>`（**不是** `en-US`，id 在私密 KB）。

状态栏要把信号一起盖掉，只给时间和电量的话信号是「....」，几张图对不上：

```bash
xcrun simctl status_bar <udid> override --time 9:41 --batteryState charged --batteryLevel 100 \
  --cellularMode active --cellularBars 4 --dataNetwork wifi --wifiMode active --wifiBars 3
```

⚠️ **设置页要单独拍**，别用上面这条临时后端的流水线：它第一行就是服务器地址，截出来印着
`http://localhost:8793`。让模拟器直连 **demo server**，截出来的地址就是审核员会看到的那个
域名。token 不必碰数据库，用公开 API 现铸现销：`POST /api/auth/login`（密码走 envops，
别落盘）拿 cookie → `POST /api/auth/device` 拿 token → 用 `CONDENSER_DEBUG_SERVER` /
`_TOKEN` / `_ROUTE=settings` 启动 → 截图 → `DELETE /api/auth/devices/{id}`。

2026-08-16 的定稿是四张：浅色时间线、深色时间线、收藏页、设置页。设置页截图里有两处
已知但没修的东西，重拍前先看一眼是不是已经解决：tab 栏 `Timeline` 是英文而另外三个是
中文（2026-11-15 仍如此）；半透明 tab 栏下面会透出「设备」区的红色删除按钮残影（iOS 原生
半透明栏的正常表现，不是渲染 bug，但静态图里看着像）。
