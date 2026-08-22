import { useCallback, useMemo } from 'react';
import { CheckCheck, Inbox, RefreshCw, Send, Sparkles } from 'lucide-react';
import { Navigate, useParams, useSearchParams } from 'react-router-dom';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { ChannelFilter } from '@/components/ChannelFilter';
import { CalendarPopover } from '@/components/CalendarPopover';
import { HnFeedRulesMenu } from '@/components/HnFeedRulesMenu';
import { HnGlyph } from '@/components/HnGlyph';
import { RssGlyph } from '@/components/RssGlyph';
import { IconBadge, PageHeader } from '@/components/PageHeader';
import { Timeline } from '@/components/timeline/Timeline';
import { Button } from '@/components/ui/button';
import { XAvatar } from '@/components/XAvatar';
import { XGlyph } from '@/components/XGlyph';
import { useBulkRead } from '@/hooks/useBulkRead';
import { useChannelFilter } from '@/hooks/useChannelFilter';
import { hnFeedRulesOf } from '@/hooks/useHnFeedRules';
import { useRefreshAll, useRefreshChannel } from '@/hooks/useRefresh';
import { useSources } from '@/hooks/useSources';
import { useChannelLabels, useSubscriptions } from '@/hooks/useSubscriptions';
import { useTimeline } from '@/hooks/useTimeline';
import { channelName } from '@/lib/format';
import { isSource, isXSyntheticFeed, rssFeedLabel, sourceLabel, subRowLabel } from '@/lib/sources';
import type { TimelineItem } from '@/lib/types';
import { cn } from '@/lib/utils';

export function TimelineView() {
  const { channelId, source: sourceParam, feed: feedParam } = useParams();
  const [sp, setSp] = useSearchParams();
  const cid = channelId ? Number(channelId) : undefined;
  const source = isSource(sourceParam) ? sourceParam : undefined;
  // X and RSS are the multi-feed sources; the route segment is ignored elsewhere.
  // RSS keys on the feed URL, which React Router hands back already decoded.
  const feed = source === 'x' || source === 'rss' ? feedParam : undefined;
  // Channel + source views are "scoped": they show everything unless "?unread=1"
  // narrows them. The aggregate view defaults to Unread ("/"); "?all=1" shows all.
  const scoped = cid != null || source != null;
  const unreadOnly = scoped ? sp.get('unread') === '1' : sp.get('all') !== '1';
  const date = sp.get('date');
  const { data: subs } = useSubscriptions();
  const { data: sources } = useSources();
  const labels = useChannelLabels(subs);
  const bulkRead = useBulkRead();
  const refreshChannel = useRefreshChannel();
  const refreshAll = useRefreshAll();

  const sub = cid != null ? subs?.find((s) => s.channel_id === cid) : undefined;
  // The /s/x/:feed views name themselves after the feed's subscription row.
  const feedSub = feed
    ? sources?.find((g) => g.source === source)?.subscriptions.find((s) => String(s.channel_id) === feed)
    : undefined;
  const title =
    cid != null
      ? sub
        ? channelName(sub)
        : `Channel ${cid}`
      : feed
        ? feedSub
          ? subRowLabel(source!, feedSub)
          : source === 'rss'
            ? rssFeedLabel(feed)
            : `@${feed}`
        : source
          ? sourceLabel(source)
          : unreadOnly
            ? 'Unread'
            : 'All';

  // Unread count for the header: the channel's own count, one feed's (/s/:source/:feed),
  // one source group's sum (/s/:source), or the sum across every source for the
  // All / Unread aggregate views.
  const unreadCount =
    cid != null
      ? (sub?.unread ?? 0)
      : feed
        ? (feedSub?.unread ?? 0)
        : (sources ?? [])
            .filter((g) => !source || g.source === source)
            .flatMap((g) => g.subscriptions)
            .reduce((n, s) => n + (s.enabled ? s.unread : 0), 0);

  // The timeline query lives here (not in <Timeline>) so the header can build the
  // channel-filter control from the loaded items.
  const query = useTimeline({ channelId: cid, unreadOnly, date: date ?? undefined, source, feed });
  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const channelOf = useCallback((it: TimelineItem) => it.telegram?.channel_id ?? null, []);
  const nameOf = useCallback(
    (it: TimelineItem) => {
      const cid2 = it.telegram?.channel_id;
      return cid2 != null ? (labels.get(cid2) ?? `Channel ${cid2}`) : 'Hacker News';
    },
    [labels],
  );
  const filter = useChannelFilter(items, channelOf, nameOf);
  const showFilter = filter.channels.length > 1;
  // With a single channel present there's nothing to filter — show everything.
  const visible = showFilter ? filter.visible : items;

  // Per-channel view re-pulls that one channel synchronously; the All/Unread view fans the
  // refresh out across every enabled channel in the background. HN has no manual pull —
  // the sampling loop is the only ingest — X is push-only (the local probe decides when
  // data arrives), and RSS polls on its own schedule, so all three hide the button.
  const showRefresh = source !== 'hn' && source !== 'x' && source !== 'rss';
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

  // A bad /s/:source segment has nothing to render — bounce home.
  if (sourceParam && !source) return <Navigate to="/" replace />;

  const icon =
    cid != null ? (
      <ChannelAvatar channelId={cid} name={title} className="size-9 text-sm" />
    ) : source === 'x' && feed && !isXSyntheticFeed(feed) ? (
      <XAvatar handle={feed} name={title} className="size-9 text-sm" />
    ) : source === 'x' ? (
      <XGlyph className="size-9 rounded-full text-base" />
    ) : source === 'hn' ? (
      <HnGlyph className="size-9 rounded-full text-base" />
    ) : source === 'rss' ? (
      <RssGlyph className="size-9 rounded-full text-base" />
    ) : source === 'telegram' ? (
      <IconBadge icon={<Send className="size-5" />} />
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
            {source === 'hn' && <HnFeedRulesMenu rules={hnFeedRulesOf(sources)} />}
            <CalendarPopover
              channelId={cid ?? null}
              source={source}
              feed={feed}
              date={date}
              onSelect={(d) => patchParams((p) => (d ? p.set('date', d) : p.delete('date')))}
            />
            {showRefresh && (
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
            )}
            <Button
              size="icon"
              variant="ghost"
              className="size-8 text-muted-foreground"
              onClick={() => bulkRead.mutate({ channel_id: cid ?? null, source: source ?? null, feed: feed ?? null })}
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
                  if (scoped) {
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
        viewKey={`${source ?? ''}/${feed ?? ''}:${cid ?? 'all'}:${unreadOnly ? 'unread' : 'all'}:${date ?? ''}`}
        channelId={cid}
        source={source}
        feed={feed}
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
