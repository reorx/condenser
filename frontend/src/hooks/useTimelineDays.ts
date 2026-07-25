import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { Source } from '@/lib/types';

/** Days that have messages (+ counts) for the calendar, optionally scoped to one
 *  channel, source, or feed within a multi-feed source (X). */
export function useTimelineDays(
  channelId: number | null,
  enabled = true,
  source: Source | null = null,
  feed: string | null = null,
) {
  return useQuery({
    queryKey: ['timeline-days', channelId ?? null, source ?? null, feed ?? null],
    queryFn: () => api.timelineDays(channelId, source, feed),
    enabled,
  });
}
