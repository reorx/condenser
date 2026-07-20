import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

/** GET /api/sources — per-source subscription lists with unread counts.
 *  Feeds the aggregate-view unread header (and the Phase 3 sidebar). */
export function useSources() {
  return useQuery({ queryKey: ['sources'], queryFn: api.listSources });
}
