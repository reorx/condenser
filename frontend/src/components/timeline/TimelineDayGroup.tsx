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
      {/* Date divider: a full-width rule between days (not a floating sticky bar) with the
          day label floating ON the line (z-axis) — the line runs edge-to-edge behind the
          label, which masks its own slice with the page background. Symmetric py keeps the
          rule centered on the text via top-1/2 (no magic offsets). */}
      <div className="relative px-4 py-4 sm:px-5">
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border" />
        <span className="relative inline-block bg-background pr-3 text-xs font-medium text-muted-foreground">
          {dayLabel(items[0].date)}
        </span>
      </div>
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
