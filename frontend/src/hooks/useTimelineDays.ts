import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

/** Days that have messages (+ counts) for the calendar, optionally scoped to one channel. */
export function useTimelineDays(channelId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['timeline-days', channelId ?? null],
    queryFn: () => api.timelineDays(channelId),
    enabled,
  });
}
