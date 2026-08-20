import { HnCard } from '@/components/timeline/HnCard';
import { MessageCard } from '@/components/timeline/MessageCard';
import { RssCard } from '@/components/timeline/RssCard';
import { XCard } from '@/components/timeline/XCard';
import { channelName, fullDateLabel } from '@/lib/format';
import type { TimelineItem } from '@/lib/types';

/**
 * One item under a full date line, dispatched by source.
 *
 * The row shape for the two views that are not a timeline — Saved and Search.
 * Both list items that jump across days and sources, so each one states its own
 * date instead of sitting under a shared day divider.
 */
export function DatedItemRow({ item }: { item: TimelineItem }) {
  return (
    <div>
      <div className="px-4 pt-2 text-[11px] text-muted-foreground/70 sm:px-5">{fullDateLabel(item.datetime)}</div>
      {item.telegram ? <MessageCard item={item} channelLabel={channelName(item.telegram.channel)} /> : null}
      {item.hn ? <HnCard item={item} /> : null}
      {item.x ? <XCard item={item} /> : null}
      {item.rss ? <RssCard item={item} /> : null}
    </div>
  );
}
