import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';
import type { DisplayMessage, Subscription, TimelinePage } from '@/lib/types';

export interface BulkReadArgs {
  channel_id?: number | null;
  before_date?: string | null;
}

function sweepTimelineRead(qc: QueryClient, channelId: number | null, beforeDate: string | null): void {
  qc.setQueriesData<{ pages: TimelinePage[]; pageParams: unknown[] }>({ queryKey: ['timeline'] }, (data) => {
    if (!data) return data;
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((m: DisplayMessage) => {
          const channelMatch = channelId == null || m.channel_id === channelId;
          const dateMatch = !beforeDate || m.date.slice(0, 10) < beforeDate;
          return channelMatch && dateMatch ? { ...m, is_read: true } : m;
        }),
      })),
    };
  });
}

function zeroUnread(qc: QueryClient, channelId: number | null): void {
  qc.setQueryData<Subscription[]>(['subscriptions'], (subs) =>
    (subs ?? []).map((s) => (channelId == null || s.channel_id === channelId ? { ...s, unread: 0 } : s)),
  );
}

export function useBulkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: BulkReadArgs) => api.markReadBulk(args),
    onMutate: (args) => {
      sweepTimelineRead(qc, args.channel_id ?? null, args.before_date ?? null);
      // A whole-scope mark lets us zero the badge instantly; a before_date mark
      // can't be counted optimistically, so we let the onSettled refetch correct it.
      if (!args.before_date) zeroUnread(qc, args.channel_id ?? null);
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not mark read')),
    onSuccess: () => toast.success('Marked as read'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['timeline'] });
    },
  });
}
