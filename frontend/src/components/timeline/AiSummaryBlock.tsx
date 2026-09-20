// The AI summary as a quote block — the web twin of iOS `AiSummaryBlock`
// (`ios/Condenser/UI/AiSummaryBlock.swift`): a faint indigo ground, a deeper bar
// of the same hue down the left edge (a Markdown blockquote's shape), and the
// 「AI 摘要」 label at the **top, inside the block** — the eye meets "a machine
// wrote this" before the words, and label and words share one box, so whose words
// they are cannot be misread. Shared by every surface that shows a summary
// (`HnCard`, `RssCard`, the detail pane's body). Indigo because the other hues
// are taken — amber is RSS / saved, orange is HN, sky is unread — and it is
// already this app's colour for an annotation on the item (`AnnotationBadge`).
//
// Unlike iOS's card, no line clamp: the column is wide enough, and the summary is
// the reason the card exists.
import { Sparkles } from 'lucide-react';

import { cn } from '@/lib/utils';

interface Props {
  summary: string | null | undefined;
  /** Outer margin only — the block's dress is not the caller's to change. */
  className?: string;
}

/** The summary worth showing: trimmed, or null when nothing is left — Kit's
 *  `displaySummary` rule, for callers that branch on "is there a summary". */
export function displaySummary(summary: string | null | undefined): string | null {
  return summary?.trim() || null;
}

export function AiSummaryBlock({ summary, className }: Props) {
  const text = displaySummary(summary);
  if (!text) return null;
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-lg bg-indigo-500/[0.07] py-2 pr-2.5 pl-[13px] dark:bg-indigo-400/10',
        // The bar is a straight 3px rectangle *clipped* by the block's rounded
        // corners, as on iOS. A `border-l` would instead bend around the radius
        // and taper to a point at both ends — a bracket, not a bar.
        'before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-indigo-500/55 dark:before:bg-indigo-400/55',
        className,
      )}
    >
      <div className="flex items-center gap-1 text-xs font-semibold text-indigo-600 dark:text-indigo-400">
        <Sparkles className="size-3.5" aria-hidden />
        AI 摘要
      </div>
      <p className="mt-1.5 text-sm leading-relaxed break-words text-foreground/90">{text}</p>
    </div>
  );
}
