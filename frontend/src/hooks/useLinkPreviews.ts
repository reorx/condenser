import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { MsgRef } from '@/lib/types';

/** Link previews for a message; fetches only while the pane is open, cached across reopens. */
export function useLinkPreviews(ref: MsgRef | null) {
  return useQuery({
    queryKey: ['link-previews', ref?.channel_id ?? null, ref?.message_id ?? null],
    queryFn: () => api.messagePreviews(ref!.channel_id, ref!.message_id),
    enabled: !!ref,
    // Previews change rarely and the backend caches them anyway; keep them warm across opens.
    staleTime: 5 * 60_000,
  });
}
