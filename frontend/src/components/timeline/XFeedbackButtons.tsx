// Thumb up/down on a tweet (plan Phase 3). The click *only* records a label —
// nothing is hidden, re-ranked or filtered by it. Phase 4 trains the For You
// verdict on exactly these labels, which is why every tweet is markable,
// including followed accounts that will never get a verdict of their own.
import { ThumbsDown, ThumbsUp } from 'lucide-react';

import { useFeedback } from '@/hooks/useFeedback';
import { cn } from '@/lib/utils';
import type { ItemFeedback } from '@/lib/types';

interface Props {
  itemKey: string;
  /** The current label; null/undefined = unlabeled. */
  feedback?: ItemFeedback | null;
  className?: string;
}

function ThumbButton({
  icon,
  label,
  active,
  activeClass,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  activeClass: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={cn(
        // the hover text color is inactive-only: a `hover:` utility would otherwise
        // win over the active color and turn the chosen thumb plain black on hover
        'cursor-pointer rounded p-1 transition-colors hover:bg-accent',
        active ? activeClass : 'text-muted-foreground hover:text-accent-foreground',
      )}
    >
      {icon}
    </button>
  );
}

export function XFeedbackButtons({ itemKey, feedback, className }: Props) {
  const feedbackMutation = useFeedback();
  // Clicking the highlighted side again is the undo — the same affordance the
  // save bookmark uses, and it keeps a mislabel one click away from gone.
  const toggle = (verdict: ItemFeedback) =>
    feedbackMutation.mutate({ key: itemKey, verdict: feedback === verdict ? null : verdict });

  return (
    <div className={cn('flex items-center gap-0.5', className)}>
      <ThumbButton
        icon={<ThumbsUp className={cn('size-3.5', feedback === 'up' && 'fill-current')} />}
        label="More like this"
        active={feedback === 'up'}
        activeClass="text-emerald-600 dark:text-emerald-400"
        onClick={() => toggle('up')}
      />
      <ThumbButton
        icon={<ThumbsDown className={cn('size-3.5', feedback === 'down' && 'fill-current')} />}
        label="Less like this"
        active={feedback === 'down'}
        activeClass="text-rose-500 dark:text-rose-400"
        onClick={() => toggle('down')}
      />
    </div>
  );
}
