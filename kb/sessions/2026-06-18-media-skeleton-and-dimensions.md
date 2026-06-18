---
created: 2026-06-18
tags:
  - frontend
  - media
  - animation
  - skeleton
  - telememo
  - schema-migration
  - aspect-ratio
---

# 图片加载 Skeleton 动效 + 端到端持久化媒体宽高

## 概要

用户反馈 timeline 单图消息加载时高度会突变（图片区域先为空，加载完后高度猛地撑开），体验不顺。本次 session 落地一套从 Telegram → DB → API → 前端 的完整方案：

1. **持久化媒体宽高**（方案 B）：通过 Telethon 内置的 `message.file.width/height`（photo / video 都支持，无额外网络调用、不触发 FloodWait），在 telememo 的 `messages` 表新增 `media_width` / `media_height` 两列；condenser SELECT 透传；前端 `MediaItem` 类型加上 `width`/`height`。新消息直接拿到精确比例 → **零跳变**。
2. **Skeleton + 平滑过渡**：单图容器用 inline `aspectRatio` 预留空间（API 有宽高用真实比例，否则 fallback 4/3）；shadcn `Skeleton` 铺底；`<img>` 加载完 `opacity 0→1` 淡入 300ms；容器加 `transition-[aspect-ratio] 300ms`，老消息从 4/3 切到真实比例也是平滑动画而非闪烁。
3. **范围覆盖**：单图（动态 aspect）、多图网格（强制 1/1 保持视觉一致、`lockAspect` 阻止 onLoad 改写）、WebPagePreview 小缩略图（固定尺寸只做淡入）三个场景统一处理。

后端 telememo 18 个 Part A 测试 + condenser 29 个测试、前端 TS 编译 + 14 个 vitest 测试全部通过。

## 修改的文件

### telememo（兄弟仓库，editable dependency）

- `telememo/types.py` — `MessageData` 加 `media_width`/`media_height`；`MediaItem` 加 `width`/`height` (都是 Optional[int])
- `telememo/db.py` — `Message` 表新增 `media_width` / `media_height` (`IntegerField(null=True)`)；既有的 `_migrate_model_columns` 会在 `init_db` 时给老库自动 `ALTER TABLE ADD COLUMN`；`save_message` 和 `save_message_smart` 两条写入路径同步加上新字段
- `telememo/telegram.py` — `convert_message_to_data` 通过 `getattr(message.file, 'width'/'height', None)` 抽取像素尺寸；photo / video 通用，无网络请求
- `telememo/service.py` — `_message_data_to_row` 投影时透传两个字段
- `telememo/utils.py` — `group_messages_to_display` 在 grouped（album）和 standalone 两处构造 `MediaItem(...)` 都传入 `width`/`height`

### condenser backend

- `condenser/timeline.py` — `_SELECT_COLS` 加上 `m.media_width AS media_width, m.media_height AS media_height`
- `condenser/records.py` — `_MSG_COLS` 同步加上两列（让 snapshot 也带宽高，render_record 自然透传）

### frontend

- `frontend/src/lib/types.ts` — `MediaItem` 接口加 `width: number | null` / `height: number | null`
- `frontend/src/components/ui/skeleton.tsx`（新建）— shadcn 标准 Skeleton：`animate-pulse rounded-md bg-muted`
- `frontend/src/components/timeline/MessageMedia.tsx` — `Thumb` 重写：
  - `initialAspect` prop（外部传入：单图算 `${w}/${h}` 或 4/3，多图固定 1/1）
  - `lockAspect` prop（多图网格 true，单图 false）
  - 内联 `style={{ aspectRatio }}` + `transition-[aspect-ratio] duration-300 ease-out`
  - `!loaded` 时绝对定位铺一层 `<Skeleton />`
  - `<img>` 默认 `opacity-0`，`onLoad` 设 `loaded=true` 并（仅当 `!lockAspect && !item.width/height`）用 `naturalWidth/naturalHeight` 覆盖 aspect
  - `failed` (非图片文件) 仍走原来的 file chip 分支，绕过 skeleton
- `frontend/src/components/timeline/WebPagePreview.tsx` — 预览图外包一层 `relative overflow-hidden`，叠加 Skeleton + opacity 淡入；容器尺寸 `size-16 sm:size-20` 固定，所以不需要 aspect 过渡

## 注意事项

### 持久化媒体宽高（telememo 端）

- **Telethon 提供 `message.file.width` / `.height`**：photo 通过 `PhotoSize.w/h`，video 通过 `DocumentAttributeVideo.w/h`，**都随消息一起送达**，不需要额外 API 调用。Telethon v1.22 修复了 photo 场景的 bug，当前可靠。
- **`message.file` 可能为 None**（无 media 的纯文本消息）：用 `getattr(message, 'file', None)` 防御，再 `getattr(file, 'width', None)` 二段取，避免 attribute 报错。
- **migration 走 `_migrate_model_columns` 即可**：telememo 已经有按 Peewee model 字段 diff 现有列并 `ALTER TABLE ADD COLUMN` 的自动迁移机制（之前 A2 forward 字段就是用它落的）；新加的字段是 `IntegerField(null=True)`，无默认值，老行 NULL 即可。
- **不破坏 extension-column 契约**：`media_width` / `media_height` 是 telememo **native** 字段（写入路径完全归 telememo 管），不是像 `is_filtered` 那种 condenser 叠加的 overlay 列；按 telememo 自己的约定走，不会影响 `is_filtered` 的存续。
- **历史消息保持 NULL**：迁移后老行 `media_width`/`media_height` 一直是 NULL（除非重新拉一遍），前端通过 fallback 路径（4/3 占位 + onLoad 后用 naturalWidth 切换）平滑展示，是预期行为。

### aspect-ratio CSS 过渡的几个坑

- **inline style 比 Tailwind class 更顺手**：动态 aspect 通过 `style={{ aspectRatio: \`${w} / ${h}\` }}` 比 Tailwind 的 `aspect-[w/h]` 更易控制（避免 JIT 类名爆炸 / 字符串拼接不安全）。
- **过渡需要显式 `transition-[aspect-ratio]`**：现代浏览器（Chrome 96+ / Firefox 89+）支持 aspect-ratio 过渡，但默认 `transition-all` 不会包含它（受 Tailwind 的 `transition-property` 限制），要写明 `transition-[aspect-ratio]`。
- **`max-h` 必须挂在和 aspect-ratio 同一元素上**：portrait（高瘦）图片如果只在 wrapper 上加 `max-h-[28rem]`、aspectRatio 在内部，inner 会撑出 wrapper（aspect-ratio 不响应外层的 max-h）。把 `max-h-[28rem]` 直接放在 `<button>`（aspect-ratio 所在元素）上，`object-cover` 自然裁掉超出部分；完整图片靠 Lightbox 看。
- **网格里要锁定 aspect**：多图网格希望恒定 1/1 美观，所以 `lockAspect=true` 阻止 `onLoad` 用 naturalWidth 覆盖；只让单图（外层容器）跑动态 aspect 路径。

### Skeleton + 淡入的实现要点

- **Skeleton 绝对定位铺满容器**：`<Skeleton className="absolute inset-0 rounded-none" />`，容器自身 `relative overflow-hidden`，`<img>` 也 `absolute inset-0 h-full w-full object-cover`；`<img>` opacity 切换时 Skeleton 自然被盖住，淡出体感来自 `<img>` 的淡入而不是 Skeleton 主动淡出。
- **`onLoad` 只 setState 一次**：图片解码完触发；不要在 useEffect 里轮询自然尺寸（会 jitter）。`naturalWidth > 0 && naturalHeight > 0` 防御性判断避开 broken-image。

### 后端测试套路

- telememo 的 integration 测试需要真 Telegram 凭据 + 交互式 stdin（3 个用例），跑 `pytest` 时会失败但与 schema 改动无关；用 `pytest tests/test_part_a.py` 跑非 integration 套件即可验证 schema/types 的正确性。

## 遗留问题

- **历史消息不回填宽高**：迁移后老行 `media_width/height` 仍是 NULL；想全量精确需要对每个 channel 触发一次 backfill（telememo 的 `_iter_backfill` 会用新的 `convert_message_to_data` 把宽高写回）。当前接受 fallback 4/3 + onLoad 切换的方案，性价比足够。
- **未做浏览器手测**：本次 session 完成了代码、类型检查、所有 backend / frontend 测试，但没有启动 dev 服务跑视觉验证。建议下次 dev 启动时观察：
  - 单图（横/竖图都看一下）从 4/3 占位过渡到真实比例的平滑度
  - 多图网格的 1/1 锁定 + Skeleton + 淡入是否一致
  - WebPage 预览图的小缩略图淡入
  - 慢速网络下 Skeleton 的视觉感受（Chrome DevTools Network 节流）
- **video 类的 `naturalWidth` 不可用**：当前实现只处理图片缩略图（thumb=true 的代理走的还是缩略图）；video 的 lightbox 全屏播放走另一条路。如果将来 video 也要做加载占位，要单独走 `<video>` 的 `onLoadedMetadata` 事件读 `videoWidth/videoHeight`。
- **Skeleton 一闪而过**：图片从 HTTP 缓存命中时 onLoad 立即触发，Skeleton 几乎不显示，可能略显突兀。如果想做"最小展示时长"可以用 `setTimeout` 延迟切换 `loaded`，但目前默认不加。

## 相关文档

- [当前最新 session（forward 源名解析）](2026-06-18-forward-source-name-resolution.md) — 上一个 session，给本次涉及的 telememo native-column 迁移路径（`_migrate_model_columns`）做了铺垫
- [内容更新机制](../docs/content-update-mechanism.md) — 参考 backfill / realtime 写入路径，确认新加的 `media_width/height` 在两条路径上都会被写入
