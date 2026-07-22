import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { MsgRef } from '@/lib/types';

/** Live views/forwards/reactions for a message. Always refetched when the pane opens
 *  (staleTime 0) — the backend reads Telegram in real time and never stores these. */
export function useMessageStats(ref: MsgRef | null) {
  return useQuery({
    queryKey: ['message-stats', ref?.channel_id ?? null, ref?.message_id ?? null],
    queryFn: () => api.messageStats(ref!.channel_id, ref!.message_id),
    enabled: !!ref,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
}
