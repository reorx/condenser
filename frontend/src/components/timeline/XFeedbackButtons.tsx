// Thumb up/down on a tweet (plan Phase 3), plus the down-reason chips (v9). The
// click *only* records a label — nothing is hidden, re-ranked or filtered by it.
// Phase 4 trains the For You verdict on exactly these labels, which is why every
// tweet is markable, including followed accounts that will never get a verdict.
//
// The chips exist because a bare thumbs-down labels the whole tweet while the thing
// you disliked is usually one attribute of it — its topic, its marketing voice, its
// AI-slop phrasing, its author. One embedding averages those into a single point, so
// "I hate this tone" is indistinguishable from "I hate this topic". Asking costs one
// tap and is skippable; skipping leaves exactly the bag-level label we had before.
import { useEffect, useState } from 'react';
import { ThumbsDown, ThumbsUp, X } from 'lucide-react';

import { useFeedback } from '@/hooks/useFeedback';
import { FEEDBACK_REASONS } from '@/lib/sources';
import { cn } from '@/lib/utils';
import type { ItemFeedback, ItemFeedbackReason } from '@/lib/types';

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

function ReasonChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="cursor-pointer rounded-full border px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
    >
      {label}
    </button>
  );
}

export function XFeedbackButtons({ itemKey, feedback, className }: Props) {
  const feedbackMutation = useFeedback();
  // Asking is a response to *this* down click, not a property of the card: a
  // down-voted tweet scrolling back into view must not re-open the question, and a
  // permanent row would nag on every labeled card forever.
  const [asking, setAsking] = useState(false);
  useEffect(() => {
    if (feedback !== 'down') setAsking(false);
  }, [feedback]);

  // Clicking the highlighted side again is the undo — the same affordance the
  // save bookmark uses, and it keeps a mislabel one click away from gone.
  const toggle = (verdict: ItemFeedback) => {
    const next = feedback === verdict ? null : verdict;
    feedbackMutation.mutate({ key: itemKey, verdict: next });
    setAsking(next === 'down');
  };

  const pick = (reason: ItemFeedbackReason) => {
    feedbackMutation.mutate({ key: itemKey, verdict: 'down', reason });
    setAsking(false);
  };

  return (
    <div className={cn('flex flex-col items-end gap-1', className)}>
      <div className="flex items-center gap-0.5">
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
      {asking && (
        <div className="flex flex-wrap items-center justify-end gap-1">
          <span className="text-xs text-muted-foreground">为什么？</span>
          {FEEDBACK_REASONS.map((r) => (
            <ReasonChip key={r.value} label={r.label} onClick={() => pick(r.value)} />
          ))}
          <button
            type="button"
            onClick={() => setAsking(false)}
            title="跳过"
            aria-label="跳过"
            className="cursor-pointer rounded p-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            <X className="size-3" />
          </button>
        </div>
      )}
    </div>
  );
}
