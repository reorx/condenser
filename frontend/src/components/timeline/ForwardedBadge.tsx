import { Repeat2 } from 'lucide-react';

import type { TimelineItem } from '@/lib/types';

/**
 * 「我转发过这条」的角标，画在四张卡片的时间那一行。
 *
 * 用 `Repeat2` 是为了和 `MessageStatsRow` 里表示「转发数」的图标保持同一套语汇 ——
 * 那里是别人转了多少次，这里是我转过。
 *
 * ⚠️ 判据是 `forwarded_by_me`，不是 `telegram.is_forwarded`：后者方向相反，指的是
 * 「这条消息是从别处转发进这个频道的」。两个字段同时存在于一张卡片上，所以名字必须
 * 各不相同 —— 详见 `lib/types.ts` 的注释。
 *
 * 提示文案用 native `title`（不是 shadcn Tooltip），和头部动作栏同一个理由：
 * 避免 Radix `asChild` 的嵌套。
 */
export function ForwardedBadge({ item }: { item: TimelineItem }) {
  if (!item.forwarded_by_me) return null;
  return (
    <span
      title="已转发到我的频道"
      aria-label="已转发到我的频道"
      className="inline-flex shrink-0 items-center text-muted-foreground/80"
    >
      <Repeat2 className="size-3.5" />
    </span>
  );
}
