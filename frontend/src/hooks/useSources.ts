import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

/** GET /api/sources — per-source subscription lists with unread counts.
 *  Feeds the aggregate-view unread header (and the Phase 3 sidebar).
 *  `enabled` exists for the auth gate, which asks this question only when
 *  Telegram is disconnected and must not fire it behind the app-password screen. */
export function useSources(options?: { enabled?: boolean }) {
  return useQuery({ queryKey: ['sources'], queryFn: api.listSources, enabled: options?.enabled ?? true });
}
