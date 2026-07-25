import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { Source } from '@/lib/types';

const POLL_INTERVAL_MS = 30_000;

/** Poll /timeline/new for items arriving after the feed's head cursor.
 *  Pauses while the tab is hidden; disabled in date-filtered views (no live head).
 *  `unreadOnly` must mirror the polled view: the unread view's head anchors the newest
 *  *unread* unit, so an unqualified poll would count read messages the view never shows. */
export function useNewContent({
  channelId,
  headCursor,
  unreadOnly,
  active,
  source,
  feed,
}: {
  channelId?: number | null;
  headCursor: string | null;
  unreadOnly?: boolean;
  active: boolean;
  /** Mirrors the view's source scope into the poll. */
  source?: Source | null;
  /** Mirrors the view's feed scope (the /s/x/:feed views) into the poll. */
  feed?: string | null;
}) {
  return useQuery({
    queryKey: [
      'timeline-new',
      {
        channel_id: channelId ?? null,
        head: headCursor,
        unread_only: !!unreadOnly,
        source: source ?? null,
        feed: feed ?? null,
      },
    ],
    queryFn: () => api.timelineNew(headCursor!, channelId ?? null, 1, !!unreadOnly, source ?? null, feed ?? null),
    enabled: active && !!headCursor,
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
    staleTime: 0,
  });
}
