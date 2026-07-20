import { HnCard } from '@/components/timeline/HnCard';
import { MessageCard } from '@/components/timeline/MessageCard';
import { channelName, fullDateLabel } from '@/lib/format';
import type { TimelineItem } from '@/lib/types';

/** A saved item in the Saved view: a full date line above the source's card. */
export function SavedMessageItem({ item }: { item: TimelineItem }) {
  return (
    <div>
      <div className="px-4 pt-2 text-[11px] text-muted-foreground/70 sm:px-5">{fullDateLabel(item.datetime)}</div>
      {item.telegram ? <MessageCard item={item} channelLabel={channelName(item.telegram.channel)} /> : null}
      {item.hn ? <HnCard item={item} /> : null}
    </div>
  );
}
