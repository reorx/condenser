import { MessageSquareText } from 'lucide-react';

import { hasNotes } from '@/lib/annotate';
import type { TimelineItem } from '@/lib/types';

/**
 * 「我在这条上写过东西」的角标（条目评论或高亮任一即算，schema v18），画在四张卡片的
 * 时间那一行，`ForwardedBadge` 的兄弟。只是记号不是按钮 —— 打开详情抽屉才能读和改，
 * 和 iOS 卡片上的 `AnnotationBadge` 一致。靛蓝是评论/标注一族的颜色（抽屉里的评论
 * 按钮同色）。提示文案用 native `title`，理由同 `ForwardedBadge`。
 */
export function AnnotationBadge({ item }: { item: TimelineItem }) {
  if (!hasNotes(item)) return null;
  return (
    <span
      title="有评论或高亮"
      aria-label="有评论或高亮"
      className="inline-flex shrink-0 items-center text-indigo-500/80 dark:text-indigo-400/80"
    >
      <MessageSquareText className="size-3.5" />
    </span>
  );
}
