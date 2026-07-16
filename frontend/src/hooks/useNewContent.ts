import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

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
}: {
  channelId?: number | null;
  headCursor: string | null;
  unreadOnly?: boolean;
  active: boolean;
}) {
  return useQuery({
    queryKey: ['timeline-new', { channel_id: channelId ?? null, head: headCursor, unread_only: !!unreadOnly }],
    queryFn: () => api.timelineNew(headCursor!, channelId ?? null, 1, !!unreadOnly),
    enabled: active && !!headCursor,
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
    staleTime: 0,
  });
}
