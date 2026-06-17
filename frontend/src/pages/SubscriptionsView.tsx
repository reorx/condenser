import { useState } from 'react';
import { CheckCheck, Filter, History, MoreVertical, RefreshCw, Search, Trash2 } from 'lucide-react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Spinner } from '@/components/Spinner';
import { BrowseChannelsDialog } from '@/components/subscriptions/BrowseChannelsDialog';
import { KeywordFilterDialog } from '@/components/subscriptions/KeywordFilterDialog';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Switch } from '@/components/ui/switch';
import { useBulkRead } from '@/hooks/useBulkRead';
import { useFetchOlder, useRefreshChannel } from '@/hooks/useRefresh';
import { useDeleteSubscription, useSetSubscriptionEnabled } from '@/hooks/useSubscriptionMutations';
import { useSubscriptions } from '@/hooks/useSubscriptions';
import { channelName } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { Subscription } from '@/lib/types';

const OLDER_FETCH_COUNT = 200;

function SubscriptionRow({ sub }: { sub: Subscription }) {
  const setEnabled = useSetSubscriptionEnabled();
  const del = useDeleteSubscription();
  const bulkRead = useBulkRead();
  const refresh = useRefreshChannel();
  const fetchOlder = useFetchOlder();
  const [keywordsOpen, setKeywordsOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const label = channelName(sub);
  // Both pull synchronously and can take a few seconds, so reflect progress on the row.
  const fetching = refresh.isPending || fetchOlder.isPending;

  return (
    <li className="flex items-center gap-3 px-4 py-3 sm:px-5">
      <ChannelAvatar channelId={sub.channel_id} name={label} />
      <div className="min-w-0">
        <div className="truncate text-sm font-medium">{label}</div>
        {sub.username && <div className="truncate text-xs text-muted-foreground">@{sub.username}</div>}
      </div>

      <div className="ml-auto flex items-center gap-2">
        {fetching && <Spinner className="size-3.5 text-muted-foreground" />}
        {!sub.backfill_done && <span className="text-xs text-amber-500">backfilling…</span>}
        <Switch
          checked={sub.enabled}
          onCheckedChange={(enabled) => setEnabled.mutate({ channelId: sub.channel_id, enabled })}
          aria-label={sub.enabled ? 'Disable channel' : 'Enable channel'}
        />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="size-8" aria-label="Channel actions">
              <MoreVertical className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem disabled={fetching} onClick={() => refresh.mutate(sub.channel_id)}>
              <RefreshCw className={cn(refresh.isPending && 'animate-spin')} />
              重新获取数据
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={fetching}
              onClick={() => fetchOlder.mutate({ channelId: sub.channel_id, count: OLDER_FETCH_COUNT })}
            >
              <History />
              继续向更早获取（{OLDER_FETCH_COUNT} 条）
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => setKeywordsOpen(true)}>
              <Filter />
              Keywords
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => bulkRead.mutate({ channel_id: sub.channel_id })}>
              <CheckCheck />
              Mark all read
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={() => setConfirmOpen(true)}>
              <Trash2 />
              Unsubscribe
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <KeywordFilterDialog
        channelId={sub.channel_id}
        channelLabel={label}
        open={keywordsOpen}
        onOpenChange={setKeywordsOpen}
      />
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`Unsubscribe from ${label}?`}
        description="Already-fetched messages are kept; the channel stops syncing and leaves your timeline. Saved items are never affected."
        destructive
        confirmLabel="Unsubscribe"
        pending={del.isPending}
        onConfirm={() => del.mutate(sub.channel_id, { onSuccess: () => setConfirmOpen(false) })}
      />
    </li>
  );
}

export function SubscriptionsView() {
  const { data: subs, isPending } = useSubscriptions();
  const [browseOpen, setBrowseOpen] = useState(false);

  return (
    <>
      <div className="flex items-start justify-between gap-3 border-b px-4 py-3 sm:px-5">
        <div>
          <h1 className="text-base font-semibold tracking-tight">Manage channels</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Toggle to pause syncing, set exclude keywords, or unsubscribe.
          </p>
        </div>
        <Button variant="outline" size="sm" className="shrink-0" onClick={() => setBrowseOpen(true)}>
          <Search className="size-4" />
          Browse channels
        </Button>
      </div>

      <BrowseChannelsDialog open={browseOpen} onOpenChange={setBrowseOpen} />

      {isPending ? (
        <div className="flex justify-center py-16">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      ) : (
        <ul className="divide-y divide-border/50">
          {(subs ?? []).map((s) => (
            <SubscriptionRow key={s.channel_id} sub={s} />
          ))}
          {(subs ?? []).length === 0 && (
            <li className="px-4 py-16 text-center text-sm text-muted-foreground">No channels yet.</li>
          )}
        </ul>
      )}
    </>
  );
}
