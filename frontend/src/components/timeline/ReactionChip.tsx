import { SmilePlus } from 'lucide-react';

import type { ReactionCount } from '@/lib/types';
import { cn } from '@/lib/utils';

/** One reaction bucket pill: the emoji glyph ('custom'/'other' kinds degrade to a generic
 *  icon — resolving custom-emoji glyphs needs an extra RPC) + count; `chosen` highlights. */
export function ReactionChip({ reaction }: { reaction: ReactionCount }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
        reaction.chosen ? 'border-primary/40 bg-primary/10 text-foreground' : 'text-muted-foreground',
      )}
    >
      {reaction.kind === 'emoji' && reaction.emoji ? (
        <span aria-hidden>{reaction.emoji}</span>
      ) : (
        <SmilePlus className="size-3" aria-label="custom reaction" />
      )}
      {reaction.count}
    </span>
  );
}
