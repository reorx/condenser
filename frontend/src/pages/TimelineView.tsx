import { CheckCheck, RefreshCw } from 'lucide-react';
import { useParams, useSearchParams } from 'react-router-dom';

import { CalendarPopover } from '@/components/CalendarPopover';
import { Timeline } from '@/components/timeline/Timeline';
import { Button } from '@/components/ui/button';
import { useBulkRead } from '@/hooks/useBulkRead';
import { useRefreshAll, useRefreshChannel } from '@/hooks/useRefresh';
import { useSubscriptions } from '@/hooks/useSubscriptions';
import { channelName } from '@/lib/format';
import { cn } from '@/lib/utils';

export function TimelineView() {
  const { channelId } = useParams();
  const [sp, setSp] = useSearchParams();
  const cid = channelId ? Number(channelId) : undefined;
  const unreadOnly = sp.get('unread') === '1';
  const date = sp.get('date');
  const { data: subs } = useSubscriptions();
  const bulkRead = useBulkRead();
  const refreshChannel = useRefreshChannel();
  const refreshAll = useRefreshAll();

  const sub = cid != null ? subs?.find((s) => s.channel_id === cid) : undefined;
  const title = cid != null ? (sub ? channelName(sub) : `Channel ${cid}`) : unreadOnly ? 'Unread' : 'All';

  // Per-channel view re-pulls that one channel synchronously; the All/Unread view fans the
  // refresh out across every enabled channel in the background.
  const refreshing = cid != null ? refreshChannel.isPending : refreshAll.isPending;
  const onRefresh = () => (cid != null ? refreshChannel.mutate(cid) : refreshAll.mutate());

  function patchParams(mutate: (p: URLSearchParams) => void) {
    setSp(
      (prev) => {
        const next = new URLSearchParams(prev);
        mutate(next);
        return next;
      },
      { replace: true },
    );
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3 sm:px-5">
        <h1 className="text-base font-semibold tracking-tight">{title}</h1>
        <div className="ml-auto flex items-center gap-2">
          <CalendarPopover
            channelId={cid ?? null}
            date={date}
            onSelect={(d) => patchParams((p) => (d ? p.set('date', d) : p.delete('date')))}
          />
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-muted-foreground"
            onClick={onRefresh}
            disabled={refreshing}
            title={cid != null ? 'Fetch new posts for this channel' : 'Fetch new posts across all channels'}
          >
            <RefreshCw className={cn('size-4', refreshing && 'animate-spin')} />
            Refresh
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-muted-foreground"
            onClick={() => bulkRead.mutate({ channel_id: cid ?? null })}
            disabled={bulkRead.isPending}
          >
            <CheckCheck className="size-4" />
            Mark read
          </Button>
          <Button
            size="sm"
            variant={unreadOnly ? 'default' : 'outline'}
            className="h-7"
            onClick={() => patchParams((p) => (unreadOnly ? p.delete('unread') : p.set('unread', '1')))}
          >
            Unread only
          </Button>
        </div>
      </div>
      <Timeline channelId={cid} unreadOnly={unreadOnly} date={date ?? undefined} />
    </>
  );
}
