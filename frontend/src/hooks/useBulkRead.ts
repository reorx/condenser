import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';
import type { Source, SourceGroup, Subscription, TimelineItem, TimelinePage } from '@/lib/types';

export interface BulkReadArgs {
  channel_id?: number | null;
  before_date?: string | null;
  /** Narrow the sweep to one source (the /s/:source views); channel_id implies telegram. */
  source?: Source | null;
}

function sweepTimelineRead(qc: QueryClient, args: BulkReadArgs): void {
  const channelId = args.channel_id ?? null;
  const beforeDate = args.before_date ?? null;
  qc.setQueriesData<{ pages: TimelinePage[]; pageParams: unknown[] }>({ queryKey: ['timeline'] }, (data) => {
    if (!data) return data;
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((it: TimelineItem) => {
          const sourceMatch = !args.source || it.source === args.source;
          const channelMatch = channelId == null || it.telegram?.channel_id === channelId;
          const dateMatch = !beforeDate || it.datetime.slice(0, 10) < beforeDate;
          return sourceMatch && channelMatch && dateMatch ? { ...it, is_read: true } : it;
        }),
      })),
    };
  });
}

function zeroUnread(qc: QueryClient, args: BulkReadArgs): void {
  const channelId = args.channel_id ?? null;
  if (args.source !== 'hn') {
    qc.setQueryData<Subscription[]>(['subscriptions'], (subs) =>
      (subs ?? []).map((s) => (channelId == null || s.channel_id === channelId ? { ...s, unread: 0 } : s)),
    );
  }
  // The sidebar + aggregate header read /api/sources; zero the swept scope there too.
  qc.setQueryData<SourceGroup[]>(['sources'], (groups) =>
    groups?.map((g) => {
      if (args.source && g.source !== args.source) return g;
      return {
        ...g,
        subscriptions: g.subscriptions.map((s) =>
          channelId == null || s.channel_id === channelId ? { ...s, unread: 0 } : s,
        ),
      };
    }),
  );
}

export function useBulkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: BulkReadArgs) => api.markReadBulk(args),
    onMutate: (args) => {
      sweepTimelineRead(qc, args);
      // A whole-scope mark lets us zero the badge instantly; a before_date mark
      // can't be counted optimistically, so we let the onSettled refetch correct it.
      if (!args.before_date) zeroUnread(qc, args);
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not mark read')),
    onSuccess: () => toast.success('Marked as read'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['sources'] });
      qc.invalidateQueries({ queryKey: ['timeline'] });
    },
  });
}
