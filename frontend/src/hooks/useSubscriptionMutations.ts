import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';
import type { Subscription } from '@/lib/types';

function patchSubscription(
  qc: QueryClient,
  channelId: number,
  patch: Partial<Subscription>,
): Subscription[] | undefined {
  const prev = qc.getQueryData<Subscription[]>(['subscriptions']);
  qc.setQueryData<Subscription[]>(['subscriptions'], (subs) =>
    (subs ?? []).map((s) => (s.channel_id === channelId ? { ...s, ...patch } : s)),
  );
  return prev;
}

export function useSetSubscriptionEnabled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, enabled }: { channelId: number; enabled: boolean }) =>
      api.setSubscriptionEnabled(channelId, enabled),
    onMutate: ({ channelId, enabled }) => ({ prev: patchSubscription(qc, channelId, { enabled }) }),
    onError: (e, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(['subscriptions'], ctx.prev);
      toast.error(errorMessage(e, 'Could not update channel'));
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['timeline'] });
    },
  });
}

export function useDeleteSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (channelId: number) => api.deleteSubscription(channelId),
    onMutate: (channelId) => {
      const prev = qc.getQueryData<Subscription[]>(['subscriptions']);
      qc.setQueryData<Subscription[]>(['subscriptions'], (subs) =>
        (subs ?? []).filter((s) => s.channel_id !== channelId),
      );
      return { prev };
    },
    onError: (e, _channelId, ctx) => {
      if (ctx?.prev) qc.setQueryData(['subscriptions'], ctx.prev);
      toast.error(errorMessage(e, 'Could not unsubscribe'));
    },
    onSuccess: () => toast.success('Unsubscribed'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['timeline'] });
    },
  });
}
