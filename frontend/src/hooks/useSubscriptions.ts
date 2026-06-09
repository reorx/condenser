import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { channelName } from '@/lib/format';
import type { Subscription } from '@/lib/types';

export function useSubscriptions() {
  return useQuery({ queryKey: ['subscriptions'], queryFn: api.listSubscriptions });
}

/** Map channel_id -> display label, for joining timeline items to channel names. */
export function useChannelLabels(subs: Subscription[] | undefined) {
  return useMemo(() => {
    const m = new Map<number, string>();
    for (const s of subs ?? []) m.set(s.channel_id, channelName(s));
    return m;
  }, [subs]);
}
