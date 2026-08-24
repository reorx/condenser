import { useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ArrowUp, Inbox } from 'lucide-react';

import { AllChannelsHidden } from '@/components/ChannelFilter';
import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { useInfiniteScrollSentinel } from '@/hooks/useInfiniteScrollSentinel';
import { useNewContent } from '@/hooks/useNewContent';
import { useScrollToRead } from '@/hooks/useScrollToRead';
import { useChannelLabels, useSubscriptions } from '@/hooks/useSubscriptions';
import { dayKey } from '@/lib/format';
import type { Source, TimelineItem } from '@/lib/types';
import type { TimelineQuery } from '@/hooks/useTimeline';

import { TimelineDayGroup } from './TimelineDayGroup';
import { TimelineSkeleton } from './TimelineSkeleton';

interface DayGroup {
  day: string;
  items: TimelineItem[];
}

function groupByDay(items: TimelineItem[]): DayGroup[] {
  const groups: DayGroup[] = [];
  let current: DayGroup | null = null;
  for (const it of items) {
    const k = dayKey(it.datetime);
    if (!current || current.day !== k) {
      current = { day: k, items: [] };
      groups.push(current);
    }
    current.items.push(it);
  }
  return groups;
}

interface TimelineProps {
  query: TimelineQuery;
  /** Identifies the current view; changing it resets scroll + re-gates mark-as-read. */
  viewKey: string;
  channelId?: number;
  /** Mirrors the view's source scope into the new-content poll. */
  source?: Source;
  /** Mirrors the view's feed scope (the /s/x/:feed views) into the new-content poll. */
  feed?: string;
  date?: string;
  /** Mirrors the view's unread filter into the new-content poll. */
  unreadOnly?: boolean;
  /** Every loaded unit (pre-filter); drives the empty-vs-all-hidden distinction. */
  items: TimelineItem[];
  /** Items after the header's channel filter; equals `items` when unfiltered. */
  visible: TimelineItem[];
  /** Clears the header's channel filter from the all-hidden recovery state. */
  onClearFilter: () => void;
  /** Shown when there are no messages at all in this view. */
  emptyLabel?: string;
}

export function Timeline({
  query,
  viewKey,
  channelId,
  source,
  feed,
  date,
  unreadOnly,
  items,
  visible,
  onClearFilter,
  emptyLabel,
}: TimelineProps) {
  const qc = useQueryClient();
  const { observe, pendingKeys, disarm } = useScrollToRead(viewKey);
  const { data: subs } = useSubscriptions();
  const labels = useChannelLabels(subs);

  const groups = useMemo(() => groupByDay(visible), [visible]);

  // New-content poll: anchored to the newest loaded item; disabled in date-filtered views.
  const headCursor = query.data?.pages[0]?.head_cursor ?? null;
  const newContent = useNewContent({ channelId, headCursor, unreadOnly, active: !date, source, feed });
  const newCount = newContent.data?.count ?? 0;

  function jumpToNewest() {
    window.scrollTo(0, 0);
    // Back at the top with fresh content: re-gate mark-as-read until the user
    // scrolls again, or the new first screen would be swept read instantly.
    disarm();
    // Trim this view's cache to its first page before refetching: refetch then re-pulls
    // just the fresh head instead of replaying every loaded page, and the updated
    // head_cursor re-keys the poll query, which dismisses the banner.
    qc.setQueriesData<{ pages: unknown[]; pageParams: unknown[] }>(
      { queryKey: ['timeline'], type: 'active' },
      (data) => data && { pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) },
    );
    void query.refetch();
  }

  const sentinel = useInfiniteScrollSentinel(query);

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
        <TimelineDayGroup key={g.day} items={g.items} labels={labels} observe={observe} pendingKeys={pendingKeys} />
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
