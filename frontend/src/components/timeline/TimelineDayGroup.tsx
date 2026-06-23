import { dayLabel } from '@/lib/format';
import type { DisplayMessage, MsgRef } from '@/lib/types';

import { MessageCard } from './MessageCard';

interface TimelineDayGroupProps {
  /** Messages belonging to a single calendar day (UTC), in display order. */
  items: DisplayMessage[];
  /** channel_id -> display label, joined client-side. */
  labels: Map<number, string>;
  /** Scroll-past-to-read observer, threaded down to each card. */
  observe?: (el: Element | null, ref: MsgRef) => (() => void) | void;
}

/** A day's worth of timeline messages under a static date divider. */
export function TimelineDayGroup({ items, labels, observe }: TimelineDayGroupProps) {
  return (
    <section>
      {/* Date divider: a static marker between days, not a floating sticky bar. */}
      <div className="px-4 pt-6 pb-2 text-xs font-medium text-muted-foreground sm:px-5">{dayLabel(items[0].date)}</div>
      <div>
        {items.map((m) => (
          <MessageCard
            key={`${m.channel_id}:${m.id}`}
            msg={m}
            channelLabel={labels.get(m.channel_id) ?? `Channel ${m.channel_id}`}
            observe={observe}
          />
        ))}
      </div>
    </section>
  );
}
