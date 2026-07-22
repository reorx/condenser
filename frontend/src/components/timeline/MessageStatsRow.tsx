import { Eye, Repeat2 } from 'lucide-react';

import { useMessageStats } from '@/hooks/useMessageStats';
import { compactNumber } from '@/lib/format';
import type { MsgRef } from '@/lib/types';

import { ReactionChip } from './ReactionChip';

/** Live views / forwards / reaction chips for the pane's message. Renders nothing while
 *  pending, on error, or when the channel exposes no stats — the row is auxiliary. */
export function MessageStatsRow({ msgRef }: { msgRef: MsgRef }) {
  const stats = useMessageStats(msgRef);
  const data = stats.data;
  if (!data) return null;
  if (data.views == null && data.forwards == null && data.reactions.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
      {data.views != null && (
        <span className="inline-flex items-center gap-1" title="Views">
          <Eye className="size-3.5" />
          {compactNumber(data.views)}
        </span>
      )}
      {data.forwards != null && (
        <span className="inline-flex items-center gap-1" title="Forwards">
          <Repeat2 className="size-3.5" />
          {compactNumber(data.forwards)}
        </span>
      )}
      {data.reactions.map((r) => (
        <ReactionChip key={`${r.kind}-${r.emoji ?? r.document_id ?? 'other'}`} reaction={r} />
      ))}
    </div>
  );
}
