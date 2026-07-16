import { useCallback, useMemo } from 'react';
import { CheckCheck, Inbox, RefreshCw, Sparkles } from 'lucide-react';
import { useParams, useSearchParams } from 'react-router-dom';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { ChannelFilter } from '@/components/ChannelFilter';
import { CalendarPopover } from '@/components/CalendarPopover';
import { IconBadge, PageHeader } from '@/components/PageHeader';
import { Timeline } from '@/components/timeline/Timeline';
import { Button } from '@/components/ui/button';
import { useBulkRead } from '@/hooks/useBulkRead';
import { useChannelFilter } from '@/hooks/useChannelFilter';
import { useRefreshAll, useRefreshChannel } from '@/hooks/useRefresh';
import { useChannelLabels, useSubscriptions } from '@/hooks/useSubscriptions';
import { useTimeline } from '@/hooks/useTimeline';
import { channelName } from '@/lib/format';
import type { DisplayMessage } from '@/lib/types';
import { cn } from '@/lib/utils';

export function TimelineView() {
  const { channelId } = useParams();
  const [sp, setSp] = useSearchParams();
  const cid = channelId ? Number(channelId) : undefined;
  // Aggregate view defaults to Unread ("/" is the home view); "?all=1" shows everything.
  // Channel views keep showing everything unless "?unread=1" narrows them.
  const unreadOnly = cid != null ? sp.get('unread') === '1' : sp.get('all') !== '1';
  const date = sp.get('date');
  const { data: subs } = useSubscriptions();
  const labels = useChannelLabels(subs);
  const bulkRead = useBulkRead();
  const refreshChannel = useRefreshChannel();
  const refreshAll = useRefreshAll();

  const sub = cid != null ? subs?.find((s) => s.channel_id === cid) : undefined;
  const title = cid != null ? (sub ? channelName(sub) : `Channel ${cid}`) : unreadOnly ? 'Unread' : 'All';

  // Unread count for the header: the channel's own count, or the sum across enabled
  // channels for the All / Unread aggregate views.
  const unreadCount =
    cid != null ? (sub?.unread ?? 0) : (subs ?? []).reduce((n, s) => n + (s.enabled ? s.unread : 0), 0);

  // The timeline query lives here (not in <Timeline>) so the header can build the
  // channel-filter control from the loaded items.
  const query = useTimeline({ channelId: cid, unreadOnly, date: date ?? undefined });
  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const nameOf = useCallback((m: DisplayMessage) => labels.get(m.channel_id) ?? `Channel ${m.channel_id}`, [labels]);
  const filter = useChannelFilter(items, nameOf);
  const showFilter = filter.channels.length > 1;
  // With a single channel present there's nothing to filter — show everything.
  const visible = showFilter ? filter.visible : items;

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

  const icon =
    cid != null ? (
      <ChannelAvatar channelId={cid} name={title} className="size-9 text-sm" />
    ) : (
      <IconBadge icon={unreadOnly ? <Sparkles className="size-5" /> : <Inbox className="size-5" />} />
    );

  return (
    <>
      <PageHeader
        icon={icon}
        title={title}
        meta={unreadCount > 0 ? `${unreadCount.toLocaleString()} unread` : undefined}
        actions={
          <>
            <CalendarPopover
              channelId={cid ?? null}
              date={date}
              onSelect={(d) => patchParams((p) => (d ? p.set('date', d) : p.delete('date')))}
            />
            <Button
              size="icon"
              variant="ghost"
              className="size-8 text-muted-foreground"
              onClick={onRefresh}
              disabled={refreshing}
              title={cid != null ? 'Fetch new posts for this channel' : 'Fetch new posts across all channels'}
            >
              <RefreshCw className={cn('size-4', refreshing && 'animate-spin')} />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="size-8 text-muted-foreground"
              onClick={() => bulkRead.mutate({ channel_id: cid ?? null })}
              disabled={bulkRead.isPending}
              title="Mark all read"
            >
              <CheckCheck className="size-4" />
            </Button>
            {showFilter && (
              <ChannelFilter
                className="h-8 px-2"
                channels={filter.channels}
                hidden={filter.hidden}
                onToggle={filter.toggle}
                onClear={filter.clear}
              />
            )}
            <Button
              size="icon"
              variant={unreadOnly ? 'default' : 'ghost'}
              className={cn('size-8', !unreadOnly && 'text-muted-foreground')}
              onClick={() =>
                patchParams((p) => {
                  if (cid != null) {
                    if (unreadOnly) p.delete('unread');
                    else p.set('unread', '1');
                  } else {
                    if (unreadOnly) p.set('all', '1');
                    else p.delete('all');
                  }
                })
              }
              title={unreadOnly ? 'Show all messages' : 'Show unread only'}
            >
              <Sparkles className="size-4" />
            </Button>
          </>
        }
      />
      <Timeline
        query={query}
        viewKey={`${cid ?? 'all'}:${unreadOnly ? 'unread' : 'all'}:${date ?? ''}`}
        channelId={cid}
        date={date ?? undefined}
        unreadOnly={unreadOnly}
        items={items}
        visible={visible}
        onClearFilter={filter.clear}
        emptyLabel={unreadOnly ? 'Nothing unread. You are all caught up.' : undefined}
      />
    </>
  );
}
