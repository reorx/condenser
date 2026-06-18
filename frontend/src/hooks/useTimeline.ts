import { useInfiniteQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { TimelinePage } from '@/lib/types';

export interface TimelineQueryParams {
  channelId?: number;
  unreadOnly?: boolean;
  date?: string;
}

/**
 * The timeline infinite query, lifted out of the Timeline component so the page
 * shell (TimelineView) can observe the loaded items — it needs them to build the
 * channel-filter control that now lives in the top bar.
 */
export function useTimeline({ channelId, unreadOnly, date }: TimelineQueryParams) {
  return useInfiniteQuery({
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
}

export type TimelineQuery = ReturnType<typeof useTimeline>;
