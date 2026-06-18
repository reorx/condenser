---
created: 2026-06-18
tags:
  - forward
  - telegram
  - entity-cache
  - backfill
  - telethon
  - bugfix
---

# Forward 来源名落地 + backfill 卡死与 entity 解析修复

## 概要

用户发现转发消息的 UI 里有些不显示来源用户名/频道名。定位到根因是 telememo 的
`extract_forward_info` 只从 Telethon 的隐藏来源字段（`fwd.from_name` /
`forward_header.from_name`）取名字，对最常见的「公开频道转发」「公开用户转发」
只存了 `from_id` 整数，没存名字。

讨论后选定方案：**入库时按三层级联补 name**——优先免费数据（Telethon 已随响应返回的
实体 `message.forward.chat` / `forward.sender`），命中持久缓存，最后才打 `get_entity` API。
同时新增一份磁盘 JSON 缓存（`condenser_entity_cache.json`）避免重启后重复调用。
Realtime 路径严格只读缓存、不发请求，防止 FloodWait 在事件 handler 里炸锅。

UI 端：转发盒子里加上来源名（盒子内首行小号粗体），盒子上方的 "Forwarded" 不再带
"from"。

实施后用户跑 reset channel 又触发了第二个问题：Telethon 的 `get_entity(int)` 报
`Could not find input entity for PeerUser`，且前端 channel 永远卡在 "backfilling…"
状态。诊断为：

1. **`StringSession` 不持久化 entity cache**（只存 auth_key + DC），重启后内存里没有
   access_hash → 给纯 int 解析会失败。最初误判为「用户清库导致」，用户澄清是用应用内
   reset 功能触发的，问题与清库无关，是 Telethon 自身限制。
2. **`_backfill_channel` 的 except 路径不调 `set_backfill_done`**，导致失败后 UI
   永远显示 "backfilling…"。

修复：

- `_backfill_channel` 把 `set_backfill_done(True)` 移进 `finally`，无论成败都标记。
- 新增 `_channel_handle(channel_id)`：查 telememo 的 `channels.username`，有就传
  `@username`（Telethon 解析字符串走 resolveUsername，与 entity cache 无关），没有
  fallback int（私有频道继续受限）。`_backfill_channel` 和 `fetch_older` 都过这个
  helper。`reset_channel` 通过 `_backfill_channel` 自动受益。

所有测试通过（telememo 27/27 含 9 个新增，condenser 29/29）。

## 修改的文件

### telememo（独立仓库，`../telememo/telememo`）

- `utils.py` — `extract_forward_info` 追加从 `raw_message.forward.chat.title` /
  `forward.sender` 读名字；新增 `_display_name_from_user(user)` 把 first/last/username
  组合成显示名。可见实体优先于隐藏 fallback。
- `entity_cache.py` **（新文件）** — `EntityNameCache(path)`：磁盘 JSON 持久化的
  `channel_id` / `user_id` → name 映射；原子写（tmp + rename）；不做 negative cache
  和 TTL（早期开发简化）。
- `telegram.py` — 新增 `async resolve_forward_entity_names(md, client, cache, allow_network)`：
  已知名 → 喂缓存；miss → 看缓存；allow_network 时才 `await client.get_entity(id)`。
  无 try/except，异常上抛。
- `service.py` — `TelegramService.__init__` 新增 `entity_cache` 参数；`_iter_backfill`
  调 resolver `allow_network=True`（外层 FloodWait 重试兜得住）；`_handle_new_message`
  调 resolver `allow_network=False`（realtime 严禁打 API）。
- `tests/test_part_a.py` — `_raw()` 加 `forward=` 参数；新增 3 个解析测试（可见 channel /
  可见 user / 隐藏 fallback）。
- `tests/test_forward_resolver.py` **（新文件）** — 6 个测试覆盖 `EntityNameCache` 持久化
  + `resolve_forward_entity_names` 的所有分支（命中、miss×allow_network on/off、喂缓存）。

### condenser

- `config.py` — 新增设置 `condenser_entity_cache_path: str = 'condenser_entity_cache.json'`。
- `tg.py` — `TgManager.__init__` 实例化 `EntityNameCache`；`_new_service` 透传给
  `TelegramService`。新增 `_channel_handle(channel_id) -> str|int` helper（用 username
  解决 Telethon entity 不在 cache 时的失败）。`_backfill_channel` 改用 `try/finally`
  保证 `set_backfill_done(True)` 一定执行；`_backfill_channel` 和 `fetch_older` 调
  `service.backfill` 前过 `_channel_handle`。
- `frontend/src/components/timeline/MessageCard.tsx` — 转发 UI 调整：盒子上方只剩
  `Forwarded`（去掉 `from X`），来源名移到盒子内首行（小号、稍粗）。`forwardSource`
  helper 改为 `forwardSourceName` 只返回名字。

## 注意事项

- **Telethon `StringSession` 不持久化 entity cache**（只存 auth_key + DC）。任何依赖
  `get_entity(int)` 的代码路径都得能容忍「重启后 access_hash 暂时丢失」的状态。
  能用 `@username` / handle string 时永远优先；纯 int 只对当前会话已 resolve 过的 peer
  可靠。
- **`message.forward.chat` / `forward.sender` 是同步缓存读，不发请求**——Telethon 在
  构造 `Forward` 对象时从响应里附带的 entities 字典直接赋值，拿不到就是 None。利用这条
  几乎覆盖了大多数转发场景。
- **realtime 事件 handler 里禁止发任何会 FloodWait 的请求**：handler 本身没有重试机制，
  一旦抛 FloodWait 整个事件就丢了，且 Telethon 的内部 task 也会污染。所以 resolver
  在 realtime 路径强制 `allow_network=False`。
- **「尝试已结束」≠「成功」**：`backfill_done` 字段的语义在这次重新定义为「跑过一次了」，
  失败也算（UI 不再卡住）。如果将来要区分错误状态，需要新增字段，不要复用这个布尔。
- **持久缓存写策略选了 set-once-flush**：每次 `set_*` 都原子写盘。对当前规模（几千条
  forward 来源）数据小、不是热路径，写盘开销可忽略；将来量大可改为定期 flush。

## 遗留问题

- **私有频道（无 username）的 entity 解析仍可能失败**：`_channel_handle` 对没有 username
  的 channel 只能 fallback int，遇上「进程刚起、缓存空、reset 私有频道」组合还是会挂。
  根治需要持久化 access_hash（自己存一份 InputPeerChannel 而不是依赖 Telethon session
  内存缓存）。先记账。
- **失败状态对用户不透明**：现在 backfill 失败 UI 只是把 "backfilling…" 撤掉，不显示
  错误，用户只能凭「点了 reset 但没消息」推断出错。后续可以加 `backfill_error` 字段
  和一个错误徽标。
- **forward user 没有 backfill 路径**：telememo 没有 users 表，存量数据里 `fwd_from_user_name`
  为空的旧消息无法靠 join 补回去。当前因为还在早期开发，用户清库重拉即可。
- **负缓存缺失**：`EntityNameCache` 不存 None 值，所以一个真的无法 resolve 的 channel
  id 每次 backfill 都会再尝试一次 `get_entity`（被 FloodWait 兜底，不会风暴，但浪费）。
  可后续加。

## 相关文档

- [content-update-mechanism](../docs/content-update-mechanism.md) — 本次 session 修改的
  ingest / backfill / reset 路径，是这份文档描述的机制；改动后可能需要在文档里补一段
  forward-name 解析的说明（本次未更新）。
