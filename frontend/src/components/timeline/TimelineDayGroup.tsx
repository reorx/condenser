import { dayLabel } from '@/lib/format';
import type { ReadTarget, TimelineItem } from '@/lib/types';

import { HnCard } from './HnCard';
import { MessageCard } from './MessageCard';
import { XCard } from './XCard';

interface TimelineDayGroupProps {
  /** Items belonging to a single calendar day (UTC), in display order. */
  items: TimelineItem[];
  /** channel_id -> display label, joined client-side (telegram items). */
  labels: Map<number, string>;
  /** Scroll-past-to-read observer, threaded down to each card. */
  observe?: (el: Element | null, target: ReadTarget) => (() => void) | void;
}

/** A day's worth of timeline items under a static date divider, dispatched by source. */
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
          {dayLabel(items[0].datetime)}
        </span>
      </div>
      <div>
        {items.map((it) =>
          it.telegram ? (
            <MessageCard
              key={it.key}
              item={it}
              channelLabel={labels.get(it.telegram.channel_id) ?? `Channel ${it.telegram.channel_id}`}
              observe={observe}
            />
          ) : it.hn ? (
            <HnCard key={it.key} item={it} observe={observe} />
          ) : it.x ? (
            <XCard key={it.key} item={it} observe={observe} />
          ) : null,
        )}
      </div>
    </section>
  );
}
