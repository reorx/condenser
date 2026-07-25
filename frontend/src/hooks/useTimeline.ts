import { useInfiniteQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { Source, TimelinePage } from '@/lib/types';

export interface TimelineQueryParams {
  channelId?: number;
  unreadOnly?: boolean;
  date?: string;
  /** Narrow to one source (the /s/:source views); channelId already implies telegram. */
  source?: Source;
  /** Narrow further inside a multi-feed source (the /s/x/:feed views). */
  feed?: string;
}

/**
 * The timeline infinite query, lifted out of the Timeline component so the page
 * shell (TimelineView) can observe the loaded items — it needs them to build the
 * channel-filter control that now lives in the top bar.
 */
export function useTimeline({ channelId, unreadOnly, date, source, feed }: TimelineQueryParams) {
  return useInfiniteQuery({
    queryKey: [
      'timeline',
      {
        channel_id: channelId ?? null,
        unread_only: !!unreadOnly,
        date: date ?? null,
        source: source ?? null,
        feed: feed ?? null,
      },
    ],
    queryFn: ({ pageParam }) =>
      api.timeline({
        cursor: pageParam,
        channel_id: channelId ?? null,
        unread_only: unreadOnly,
        date: date ?? null,
        source: source ?? null,
        feed: feed ?? null,
        limit: 30,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last: TimelinePage) => last.next_cursor ?? undefined,
  });
}

export type TimelineQuery = ReturnType<typeof useTimeline>;
