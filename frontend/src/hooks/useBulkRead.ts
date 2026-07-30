import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';
import type { Source, SourceGroup, SourceSub, Subscription, TimelineItem, TimelinePage } from '@/lib/types';

export interface BulkReadArgs {
  channel_id?: number | null;
  before_date?: string | null;
  /** Narrow the sweep to one source (the /s/:source views); channel_id implies telegram. */
  source?: Source | null;
  /** Narrow further inside a multi-feed source (the /s/x/:feed views). */
  feed?: string | null;
}

/** Does this sweep clear the whole of the given subscription row?
 *
 *  Mirrors db.mark_read_bulk, which burns exactly what the timeline showed. For an
 *  unscoped sweep that is the *aggregate's* share of each X feed, and how big that
 *  share is depends on a per-feed setting: a feed set to 不进主时间线 contributes
 *  nothing, and For You in 只进推荐的 contributes only what the verdict admitted.
 *  Rather than duplicating that rule here, compare the two counts the server
 *  already sends — equal means the aggregate showed everything this feed had, so
 *  the badge can be zeroed on the spot; otherwise leave it to the refetch. */
function coversSub(args: BulkReadArgs, source: string, sub: SourceSub): boolean {
  const channelId = sub.channel_id;
  if (args.channel_id != null) return channelId === args.channel_id;
  if (args.source && source !== args.source) return false;
  if (args.feed) return String(channelId) === args.feed;
  if (!args.source && source === 'x') return sub.aggregate_unread === sub.unread;
  return true;
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
          const feedMatch = !args.feed || it.x?.feed === args.feed;
          const dateMatch = !beforeDate || it.datetime.slice(0, 10) < beforeDate;
          return sourceMatch && channelMatch && feedMatch && dateMatch ? { ...it, is_read: true } : it;
        }),
      })),
    };
  });
}

function zeroUnread(qc: QueryClient, args: BulkReadArgs): void {
  const channelId = args.channel_id ?? null;
  // The legacy TG-only cache; other sources never appear in it.
  if (!args.source || args.source === 'telegram') {
    qc.setQueryData<Subscription[]>(['subscriptions'], (subs) =>
      (subs ?? []).map((s) => (channelId == null || s.channel_id === channelId ? { ...s, unread: 0 } : s)),
    );
  }
  // The sidebar + aggregate header read /api/sources; zero the swept scope there too.
  qc.setQueryData<SourceGroup[]>(['sources'], (groups) =>
    groups?.map((g) => ({
      ...g,
      subscriptions: g.subscriptions.map((s) =>
        coversSub(args, g.source, s) ? { ...s, unread: 0, aggregate_unread: 0 } : s,
      ),
    })),
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
