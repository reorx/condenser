import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { Source } from '@/lib/types';

/** Days that have messages (+ counts) for the calendar, optionally scoped to one channel or source. */
export function useTimelineDays(channelId: number | null, enabled = true, source: Source | null = null) {
  return useQuery({
    queryKey: ['timeline-days', channelId ?? null, source ?? null],
    queryFn: () => api.timelineDays(channelId, source),
    enabled,
  });
}
