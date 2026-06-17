---
created: 2026-06-17
tags:
  - condenser
  - telegram
  - telethon
  - logging
  - debugging
  - security
---

# 排查"无端收到三条 Telegram 登录码" + 给后端日志加时间戳

## 概要

用户在没有操作 condenser 的情况下,连续收到 Telegram 发来的三条 **Login Code** 验证码,怀疑后端在运行中触发了重新验证。本次 session 排查根因,并顺手修复"后端日志没有时间戳"这一痛点。

**结论:登录码不是 condenser 触发的。** condenser 全程处于 `authorized`,从未走过发码路径;真正的来源是另一个对该账号发起登录的客户端(最可能是共用账号的 telememo,或一次非本人发起的登录尝试)。

## 排查过程与证据

关键事实:Telegram 的 **"Login code"** 消息**只可能**是某客户端对账号调用了 `auth.sendCode`(telethon 的 `send_code_request`)的结果。断线重连、新设备上线都**不会**产生这条消息(新设备上线是 "New login" 告警,另一种)。

condenser 里调用 `send_code_request` 的唯一路径:
`前端 TgLogin 提交手机号 → POST /api/tg/send-code → TgManager.send_code → service.send_code()`
(`condenser/tg.py:99`、`routers/tg.py` 的 `/send-code`)。`startup()`/`connect()`/`start_listening()`/backfill 全程都不发码(grep 确认)。

对照用户提供的日志,三点锁死 condenser 无罪:

1. **全程没有 `POST /api/tg/send-code`** —— 日志里全是 GET(timeline/status/subscriptions)。
2. **condenser 始终 `authorized`** —— 前端持续轮询 `/api/timeline` 等并拿 200,而前端只有在 `status==='authorized'`(主视图)时才发这些请求;掉到 `unauthorized` 会切到 TgLogin 并停轮询。故那串 `--reload` 重启期间会话从没掉线、没重登。
3. **reload churn 是红鲱鱼** —— 日志里 4~5 次重启(在改 `timeline.py`/`records.py`)每次只是干净地 `Disconnect → Connect` 同一个 user session,不发码,且会话存活。

排除 condenser 后,真正来源的两种可能:

- **可能性 A —— 自己的另一个客户端(首选 telememo)。** telememo 与 condenser 共用同一 Telegram 账号但**各自独立 session**,其 CLI 走 telethon 交互式 `client.start(phone=...)`(`telememo/telegram.py:175`),只要它那份 session 失效就**自动 `send_code_request`** 并等待输码;跑几次/重试就会连发多条码。但 shell history 显示 telememo 最近一次运行约在 2026-04(~2.5 个月前),不是"刚刚" —— 除非从别的终端/cron/设备跑(history 抓不到),否则证据不足。
- **可能性 B —— 非本人发起的登录尝试(安全)。** "啥也没干却收到登录码"是别人尝试登录账号的典型信号。建议:Telegram → Settings → Devices 查陌生会话;确认已开 two-step verification(云密码)。

## 改动(本仓库)

### 新增 `condenser/logconf.py`
完整的 `logging.dictConfig`(基于 uvicorn 默认 config 扩展),给**所有**日志加时间戳 —— 包括之前 `basicConfig` 管不到的 uvicorn server / access 行(uvicorn 的 logger 自带 handler+formatter 且 `propagate=False`)。三套 formatter:
- `default` —— uvicorn server 行,无 logger 名;
- `access` —— uvicorn access 行;
- `named` —— 其它(`condenser.*` / `telethon.*`),带 logger 名。

格式:`2026-06-17 18:15:12 INFO:     condenser.tg: ...`。两种启动方式(`uvicorn` CLI 与 `python -m condenser`)都覆盖,因为本模块在 uvicorn 配置好自身 logging 之后才被 import,`dictConfig` 会重配已注册的 uvicorn logger。

### `condenser/app.py`
用 `from .logconf import configure_logging` + `configure_logging()` 替换原 `logging.basicConfig(level=logging.INFO)`。

### `condenser/tg.py`(可观测性)
- `send_code()` 入口加 `log.info('requesting telegram login code for %s (this sends a code to the account)', phone)` —— 下次再出现"莫名收到登录码",直接看(现在带时间戳的)日志即可确认是不是 condenser 干的。
- `startup()` 加 session 恢复结果日志:成功 `info('telegram session restored (authorized) ...')`,失效 `warning('stored telegram session is no longer authorized; re-login required')`。

## 验证
- `condenser/logconf.py` 冒烟测试:uvicorn 行简洁、condenser/telethon 行带名、全部带时间戳。
- `uv run pytest` —— 24 passed。

## 备注 / 后续
- 建议:只调前端时用不带 `--reload` 的 `uv run python -m condenser` 跑后端,避免每次存盘把 Telegram user session 断开重连。虽然这次会话扛住了,但反复重连一个 MTProto user session 不是好习惯。
- 注:本 session 期间观察到 `routers/tg.py` 已新增 `/refresh`、`/refresh/{id}`、`/fetch-older/{id}` 端点,`tg.py` 的 `_backfill_channel` 改为返回 ingest 行数(应为另一支未提交工作,非本次改动)。
