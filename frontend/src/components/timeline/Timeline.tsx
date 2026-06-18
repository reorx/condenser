import { useEffect, useMemo, useRef } from 'react';
import { ArrowUp, Inbox } from 'lucide-react';

import { AllChannelsHidden } from '@/components/ChannelFilter';
import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { useNewContent } from '@/hooks/useNewContent';
import { useScrollToRead } from '@/hooks/useScrollToRead';
import { useChannelLabels, useSubscriptions } from '@/hooks/useSubscriptions';
import { dayKey, dayLabel } from '@/lib/format';
import type { DisplayMessage } from '@/lib/types';
import type { TimelineQuery } from '@/hooks/useTimeline';

import { MessageCard } from './MessageCard';
import { TimelineSkeleton } from './TimelineSkeleton';

interface DayGroup {
  day: string;
  items: DisplayMessage[];
}

function groupByDay(items: DisplayMessage[]): DayGroup[] {
  const groups: DayGroup[] = [];
  let current: DayGroup | null = null;
  for (const m of items) {
    const k = dayKey(m.date);
    if (!current || current.day !== k) {
      current = { day: k, items: [] };
      groups.push(current);
    }
    current.items.push(m);
  }
  return groups;
}

interface TimelineProps {
  query: TimelineQuery;
  /** Identifies the current view; changing it resets scroll + re-gates mark-as-read. */
  viewKey: string;
  channelId?: number;
  date?: string;
  /** Every loaded unit (pre-filter); drives the empty-vs-all-hidden distinction. */
  items: DisplayMessage[];
  /** Items after the header's channel filter; equals `items` when unfiltered. */
  visible: DisplayMessage[];
  /** Clears the header's channel filter from the all-hidden recovery state. */
  onClearFilter: () => void;
  /** Shown when there are no messages at all in this view. */
  emptyLabel?: string;
}

export function Timeline({
  query,
  viewKey,
  channelId,
  date,
  items,
  visible,
  onClearFilter,
  emptyLabel,
}: TimelineProps) {
  const observe = useScrollToRead(viewKey);
  const { data: subs } = useSubscriptions();
  const labels = useChannelLabels(subs);

  const groups = useMemo(() => groupByDay(visible), [visible]);

  // New-content poll: anchored to the newest loaded item; disabled in date-filtered views.
  const headCursor = query.data?.pages[0]?.head_cursor ?? null;
  const newContent = useNewContent({ channelId, headCursor, active: !date });
  const newCount = newContent.data?.count ?? 0;

  function jumpToNewest() {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    void query.refetch();
  }

  // Infinite scroll: load more when the sentinel nears the viewport.
  const sentinel = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && query.hasNextPage && !query.isFetchingNextPage) {
          void query.fetchNextPage();
        }
      },
      { rootMargin: '600px 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [query.hasNextPage, query.isFetchingNextPage, query.fetchNextPage]);

  if (query.isPending) {
    return <TimelineSkeleton />;
  }

  if (query.isError) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-sm text-muted-foreground">
        <p>Failed to load the timeline.</p>
        <Button variant="outline" size="sm" onClick={() => query.refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-24 text-center text-muted-foreground">
        <Inbox className="size-8" />
        <p className="text-sm">{emptyLabel ?? 'No messages here yet.'}</p>
      </div>
    );
  }

  // Everything was filtered out — keep a way back.
  if (visible.length === 0) {
    return <AllChannelsHidden icon={Inbox} onClear={onClearFilter} />;
  }

  return (
    <div>
      {newCount > 0 && !query.isRefetching && (
        <button
          type="button"
          onClick={jumpToNewest}
          className="fixed top-14 left-1/2 z-30 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground shadow-lg transition hover:bg-primary/90 md:top-3 md:left-[calc(50%+8rem)]"
        >
          <ArrowUp className="size-4" />
          {newCount} new message{newCount > 1 ? 's' : ''}
        </button>
      )}
      {groups.map((g) => (
        <section key={g.day}>
          {/* Date divider: a static marker between days, not a floating sticky bar. */}
          <div className="px-4 pt-6 pb-2 text-xs font-medium text-muted-foreground sm:px-5">
            {dayLabel(g.items[0].date)}
          </div>
          <div>
            {g.items.map((m) => (
              <MessageCard
                key={`${m.channel_id}:${m.id}`}
                msg={m}
                channelLabel={labels.get(m.channel_id) ?? `Channel ${m.channel_id}`}
                observe={observe}
              />
            ))}
          </div>
        </section>
      ))}

      <div ref={sentinel} />
      {query.isFetchingNextPage && (
        <div className="flex justify-center py-6">
          <Spinner className="text-muted-foreground" />
        </div>
      )}
      {!query.hasNextPage && <p className="py-8 text-center text-xs text-muted-foreground">End of timeline</p>}
    </div>
  );
}
