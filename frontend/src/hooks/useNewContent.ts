import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

const POLL_INTERVAL_MS = 30_000;

/** Poll /timeline/new for items arriving after the feed's head cursor.
 *  Pauses while the tab is hidden; disabled in date-filtered views (no live head). */
export function useNewContent({
  channelId,
  headCursor,
  active,
}: {
  channelId?: number | null;
  headCursor: string | null;
  active: boolean;
}) {
  return useQuery({
    queryKey: ['timeline-new', { channel_id: channelId ?? null, head: headCursor }],
    queryFn: () => api.timelineNew(headCursor!, channelId ?? null, 1),
    enabled: active && !!headCursor,
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
    staleTime: 0,
  });
}
