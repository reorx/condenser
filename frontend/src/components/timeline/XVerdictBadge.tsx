// The machine's read on a For You tweet (plan Phase 4), sitting on the card footer
// opposite the reader's own thumbs — "what it thinks" facing "what you think".
//
// Phase 4 badges and does not hide: an algorithm trained on a few hundred labels
// will be wrong, and a wrong verdict you cannot see is one you can never correct.
// So `neutral` renders nothing (it is the default answer, not a finding), only
// positive/negative appear, and the badge is a button into the detail pane where
// the neighbours that voted are listed.
import { Meh, Sparkles } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { XVerdict, XVerdictMeta } from '@/lib/types';

interface Props {
  verdict: XVerdict | null;
  meta: XVerdictMeta | null;
  /** Opens the detail pane, where the evidence lives. */
  onOpen?: () => void;
  className?: string;
}

const STYLES: Record<'positive' | 'negative', { label: string; icon: typeof Sparkles; className: string }> = {
  positive: {
    label: 'Recommended',
    icon: Sparkles,
    className: 'text-emerald-600 dark:text-emerald-400',
  },
  negative: {
    label: 'Likely not for you',
    icon: Meh,
    className: 'text-rose-500 dark:text-rose-400',
  },
};

/** "matches 3 tweets you marked 👎" — the one-line why, for the hover tooltip. */
function explain(meta: XVerdictMeta | null): string | undefined {
  const neighbors = meta?.neighbors;
  if (!neighbors?.length) return undefined;
  const downs = neighbors.filter((n) => n.label === 'down').length;
  const ups = neighbors.length - downs;
  const parts = [ups > 0 ? `${ups} you liked or saved` : null, downs > 0 ? `${downs} you marked down` : null].filter(
    Boolean,
  );
  const score = typeof meta?.score === 'number' ? ` · score ${meta.score.toFixed(2)}` : '';
  return `Closest labeled tweets: ${parts.join(', ')}${score}`;
}

export function XVerdictBadge({ verdict, meta, onOpen, className }: Props) {
  if (verdict !== 'positive' && verdict !== 'negative') return null;
  const { label, icon: Icon, className: tone } = STYLES[verdict];

  return (
    <button
      type="button"
      onClick={onOpen}
      title={explain(meta)}
      aria-label={`Verdict: ${label}`}
      className={cn(
        'inline-flex shrink-0 cursor-pointer items-center gap-1 rounded transition-colors hover:underline',
        tone,
        className,
      )}
    >
      <Icon className="size-3.5" />
      <span>{label}</span>
    </button>
  );
}
