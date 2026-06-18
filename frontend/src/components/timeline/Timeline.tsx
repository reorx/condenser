import { useEffect, useMemo, useRef } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { ArrowUp, Inbox } from 'lucide-react';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { useNewContent } from '@/hooks/useNewContent';
import { useScrollToRead } from '@/hooks/useScrollToRead';
import { useChannelLabels, useSubscriptions } from '@/hooks/useSubscriptions';
import { api } from '@/lib/api';
import { dayKey, dayLabel } from '@/lib/format';
import type { DisplayMessage, TimelinePage } from '@/lib/types';

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

export function Timeline({ channelId, unreadOnly, date }: { channelId?: number; unreadOnly?: boolean; date?: string }) {
  // Identifies the current view; changing it resets scroll + re-gates mark-as-read.
  const viewKey = `${channelId ?? 'all'}:${unreadOnly ? 'unread' : 'all'}:${date ?? ''}`;
  const observe = useScrollToRead(viewKey);
  const { data: subs } = useSubscriptions();
  const labels = useChannelLabels(subs);

  const query = useInfiniteQuery({
    queryKey: ['timeline', { channel_id: channelId ?? null, unread_only: !!unreadOnly, date: date ?? null }],
    queryFn: ({ pageParam }) =>
      api.timeline({
        cursor: pageParam,
        channel_id: channelId ?? null,
        unread_only: unreadOnly,
        date: date ?? null,
        limit: 30,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last: TimelinePage) => last.next_cursor ?? undefined,
  });

  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const groups = useMemo(() => groupByDay(items), [items]);

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
  }, [query.hasNextPage, query.isFetchingNextPage, query.fetchNextPage, query]);

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
        <p className="text-sm">{unreadOnly ? 'Nothing unread. You are all caught up.' : 'No messages here yet.'}</p>
      </div>
    );
  }

  return (
    <div>
      {newCount > 0 && !query.isRefetching && (
        <button
          type="button"
          onClick={jumpToNewest}
          className="fixed top-14 left-1/2 z-30 -translate-x-1/2 inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground shadow-lg transition hover:bg-primary/90 md:top-3 md:left-[calc(50%+8rem)]"
        >
          <ArrowUp className="size-4" />
          {newCount} new message{newCount > 1 ? 's' : ''}
        </button>
      )}
      {groups.map((g) => (
        <section key={g.day}>
          <div className="sticky top-12 z-10 border-b bg-background/80 px-4 py-1.5 text-xs font-medium text-muted-foreground backdrop-blur sm:px-5 md:top-0">
            {dayLabel(g.items[0].date)}
          </div>
          <div className="divide-y divide-border/50">
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
